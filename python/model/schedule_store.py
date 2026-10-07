"""
Incremental changes to the stored timer tasks: one task, or one whole tasks document, at a time.

A tasks document is a file with its own `id` (the file name is not the id) holding `items`, the timer tasks.
Every change is a read-modify-write of the raw JSON under a lock for that file, written atomically by `_internal_save`,
so anything in the file this code does not touch is kept.

Revisions (`_rev`) are hashes of the parsed form (`to_dict()`), the same value the list and render endpoints report:
a document's revision covers the whole file, a task's revision covers that task only, so changing task A is not a
conflict with somebody else having changed task B.
"""
import copy
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .configuration_manager import HASH_KEY, _internal_save, create_hash
from .schedule import SCHEMA_PLAYLIST, SCHEMA_TASKS, Playlist, TimerTasks, validate_trigger
from .schedule_loader import ScheduleLoader
from .schedule_manager import ScheduleManager

logger = logging.getLogger(__name__)

ITEM_KEYS = ("id", "title", "enabled", "trigger", "task")
TASK_KEYS = ("plugin_name", "content")

class ScheduleStoreError(Exception):
	"""Base of the errors the store reports; the web layer maps them to HTTP statuses."""

class NotFound(ScheduleStoreError):
	def __init__(self, what: str):
		super().__init__(what)
		self.what = what

class Ambiguous(ScheduleStoreError):
	"""More than one stored file declares the same id."""

class Conflict(ScheduleStoreError):
	def __init__(self, rev: str|None):
		super().__init__("revision mismatch")
		self.rev = rev

class Invalid(ScheduleStoreError):
	def __init__(self, errors: list[dict]):
		super().__init__("invalid")
		self.errors = errors

# an item validator reports problems beyond the shape (the plugin exists, its `content` follows its settings); it returns
# [{ "path": [...], "message": str }] relative to the task
ItemValidator = Callable[[dict], list[dict]]

def _no_extra_validation(item: dict) -> list[dict]:
	return []

def document_rev(raw: dict, kind: "Kind|None" = None) -> str:
	return create_hash((kind or TASKS).parse(raw).to_dict())

def _error(path: list[str], message: str) -> dict:
	return { "path": path, "message": message }

def check_item_shape(item: Any, *, partial: bool = False) -> list[dict]:
	"""Our own rules for the shape of a task (`partial` for a merge patch, where absent keys are fine). Messages never echo values."""
	if not isinstance(item, dict):
		return [_error([], "Expected an object")]
	errors: list[dict] = []
	for key in item:
		if key not in ITEM_KEYS and key != HASH_KEY:
			errors.append(_error([str(key)], "Unknown property"))
	if "title" in item and not isinstance(item["title"], str):
		errors.append(_error(["title"], "Expected text"))
	if "enabled" in item and not isinstance(item["enabled"], bool):
		errors.append(_error(["enabled"], "Expected true or false"))
	if "trigger" in item:
		for problem in validate_trigger(item["trigger"]):
			errors.append(_error(["trigger"], problem))
	elif not partial:
		errors.append(_error(["trigger"], "Required"))
	task = item.get("task")
	if "task" in item and not isinstance(task, dict):
		errors.append(_error(["task"], "Expected an object"))
	elif isinstance(task, dict):
		for key in task:
			if key not in TASK_KEYS:
				errors.append(_error(["task", str(key)], "Unknown property"))
		if "plugin_name" in task and not (isinstance(task["plugin_name"], str) and task["plugin_name"]):
			errors.append(_error(["task", "plugin_name"], "Required"))
		elif "plugin_name" not in task and not partial:
			errors.append(_error(["task", "plugin_name"], "Required"))
		if "content" in task and not isinstance(task["content"], dict):
			errors.append(_error(["task", "content"], "Expected an object"))
		elif "content" not in task and not partial:
			errors.append(_error(["task", "content"], "Required"))
	elif not partial:
		errors.append(_error(["task"], "Required"))
	return errors

PLAYLIST_ITEM_KEYS = ("id", "type", "title", "plugin_name", "content")
PLAYLIST_ITEM_TYPE = "PlaylistSchedule"

def check_track_shape(item: Any, *, partial: bool = False) -> list[dict]:
	"""Our own rules for the shape of a playlist track (`partial` for a merge patch)."""
	if not isinstance(item, dict):
		return [_error([], "Expected an object")]
	errors: list[dict] = []
	for key in item:
		if key not in PLAYLIST_ITEM_KEYS and key != HASH_KEY:
			errors.append(_error([str(key)], "Unknown property"))
	if "type" in item and item["type"] != PLAYLIST_ITEM_TYPE:
		errors.append(_error(["type"], "Unknown track type"))
	if "title" in item and not isinstance(item["title"], str):
		errors.append(_error(["title"], "Expected text"))
	if "plugin_name" in item and not (isinstance(item["plugin_name"], str) and item["plugin_name"]):
		errors.append(_error(["plugin_name"], "Required"))
	elif "plugin_name" not in item and not partial:
		errors.append(_error(["plugin_name"], "Required"))
	if "content" in item and not isinstance(item["content"], dict):
		errors.append(_error(["content"], "Expected an object"))
	elif "content" not in item and not partial:
		errors.append(_error(["content"], "Required"))
	return errors

def _finish_task(item: dict) -> dict:
	item.setdefault("title", "")
	item.setdefault("enabled", True)
	return item

def _finish_track(item: dict) -> dict:
	item.setdefault("title", "")
	item["type"] = PLAYLIST_ITEM_TYPE
	return item

@dataclass(frozen=True)
class Kind:
	"""What differs between the stored kinds of schedule documents. Timer tasks are changed one task at a time; a playlist is saved whole."""
	name: str
	schema: str
	entries_key: str		# the key of ScheduleManager.load()
	document_class: type
	parse: Callable[[dict], Any]
	check_shape: Callable[..., list[dict]]
	finish: Callable[[dict], dict]	# defaults for an item that was accepted

TASKS = Kind("tasks", SCHEMA_TASKS, "tasks", TimerTasks, ScheduleLoader.parseTimerTasks, check_item_shape, _finish_task)
PLAYLISTS = Kind("playlist", SCHEMA_PLAYLIST, "playlists", Playlist, ScheduleLoader.parsePlaylist, check_track_shape, _finish_track)

def merge_patch(target: Any, patch: Any) -> Any:
	"""RFC 7396 JSON Merge Patch: objects merge, `null` removes a key, anything else (a list included) replaces."""
	if not isinstance(patch, dict):
		return copy.deepcopy(patch)
	result = dict(target) if isinstance(target, dict) else {}
	for key, value in patch.items():
		if value is None:
			result.pop(key, None)
		else:
			result[key] = merge_patch(result.get(key), value)
	return result

class ScheduleStore:
	"""The timer-task documents of one storage root. Cheap to create: one per request."""
	_locks: dict[str, threading.RLock] = {}
	_locks_guard = threading.Lock()

	def __init__(self, manager: ScheduleManager, validate_item: ItemValidator = _no_extra_validation, kind: Kind = TASKS):
		self._kind = kind
		self._manager = manager
		self._root = manager.ROOT_PATH
		self._validate_item = validate_item

	@classmethod
	def _lock_for(cls, path: str) -> threading.RLock:
		key = os.path.realpath(path)
		with cls._locks_guard:
			lock = cls._locks.get(key)
			if lock is None:
				lock = cls._locks[key] = threading.RLock()
			return lock

	# --- reading

	def _entries(self) -> list[dict]:
		return self._manager.load()[self._kind.entries_key]

	def _find(self, doc_id: str) -> str:
		"""The path of the file whose declared id is `doc_id`. The id from the URL only selects; the path is the scanned entry's."""
		paths = []
		for entry in self._entries():
			info = entry.get("info")
			if isinstance(info, self._kind.document_class) and info.id == doc_id:
				paths.append(entry["path"])
		if not paths:
			raise NotFound("schedule")
		if len(paths) > 1:
			raise Ambiguous(doc_id)
		return paths[0]

	@staticmethod
	def _read(path: str) -> dict:
		with open(path, "r", encoding="utf-8") as f:
			raw = json.load(f)
		if not isinstance(raw, dict):
			raise ValueError("not an object")
		return raw

	def get_document(self, doc_id: str) -> dict:
		path = self._find(doc_id)
		with self._lock_for(path):
			return self._present(self._read(path))

	def get_item(self, doc_id: str, item_id: str) -> dict:
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
		idx = self._index(raw, item_id)
		return self._present_item(raw, raw["items"][idx])

	def _parsed(self, raw: dict) -> dict:
		return self._kind.parse(raw).to_dict()

	def _present(self, raw: dict) -> dict:
		doc = self._parsed(raw)
		doc[HASH_KEY] = create_hash(doc)
		doc["items"] = [dict(x, **{ HASH_KEY: create_hash(x) }) for x in doc["items"]]
		return doc

	def _present_item(self, raw: dict, item: dict) -> dict:
		parsed = self._kind.parse({ **raw, "items": [item] }).items[0].to_dict()
		return { **parsed, HASH_KEY: create_hash(parsed), "schedule": raw.get("id"), "schedule_rev": document_rev(raw, self._kind) }

	@staticmethod
	def _index(raw: dict, item_id: str) -> int:
		for idx, item in enumerate(raw.get("items", [])):
			if isinstance(item, dict) and item.get("id") == item_id:
				return idx
		raise NotFound("task")

	# --- writing

	def _write(self, path: str, raw: dict) -> None:
		raw["_schema"] = self._kind.schema
		self._kind.parse(raw)	# what is saved must load again
		_internal_save(path, raw)

	def _validated_item(self, item: dict, *, partial: bool = False) -> dict:
		errors = self._kind.check_shape(item, partial=partial)
		if not errors:
			errors = self._validate_item(item)
		if errors:
			raise Invalid(errors)
		return item

	def _check_items(self, items: Any) -> list[dict]:
		if not isinstance(items, list):
			raise Invalid([_error(["items"], "Expected a list")])
		result: list[dict] = []
		seen: set[str] = set()
		errors: list[dict] = []
		for index, entry in enumerate(items):
			problems = self._kind.check_shape(entry)
			if not problems:
				problems = self._validate_item(entry)
			errors.extend(_error(["items", str(index), *p["path"]], p["message"]) for p in problems)
			if isinstance(entry, dict):
				entry = self._kind.finish({k: v for k, v in entry.items() if k != HASH_KEY})
				entry.setdefault("id", str(uuid.uuid4()))
				if entry["id"] in seen:
					errors.append(_error(["items", str(index), "id"], "Duplicate id"))
				seen.add(entry["id"])
				result.append(entry)
		if errors:
			raise Invalid(errors)
		return result

	def create_document(self, body: dict) -> dict:
		if not isinstance(body, dict):
			raise Invalid([_error([], "Expected an object")])
		errors = [_error([str(k)], "Unknown property") for k in body if k not in ("name", "items")]
		name = body.get("name")
		if not isinstance(name, str) or not name.strip():
			errors.append(_error(["name"], "Required"))
		if errors:
			raise Invalid(errors)
		items = self._check_items(body.get("items", []))
		doc_id = f"{self._kind.name}-{uuid.uuid4().hex}"
		# the file name is ours too; nothing from the request builds a path
		path = os.path.join(self._root, f"{doc_id}.json")
		with self._lock_for(path):
			self._write(path, { "id": doc_id, "name": name.strip(), "_schema": self._kind.schema, "items": items })
			return self._present(self._read(path))

	def _check_rev(self, current: str, rev: Any) -> None:
		if not isinstance(rev, str) or rev != current:
			raise Conflict(current)

	def replace_document(self, doc_id: str, body: dict, rev: Any) -> dict:
		if not isinstance(body, dict):
			raise Invalid([_error([], "Expected an object")])
		errors = [_error([str(k)], "Unknown property") for k in body if k not in ("name", "items", "id", "_schema", HASH_KEY)]
		if body.get("id", doc_id) != doc_id:
			errors.append(_error(["id"], "ID mismatch"))
		name = body.get("name")
		if not isinstance(name, str) or not name.strip():
			errors.append(_error(["name"], "Required"))
		if errors:
			raise Invalid(errors)
		items = self._check_items(body.get("items", []))
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			self._check_rev(document_rev(raw, self._kind), rev)
			self._write(path, { **raw, "name": name.strip(), "items": items })
			return self._present(self._read(path))

	def rename_document(self, doc_id: str, body: dict, rev: Any) -> dict:
		if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not body["name"].strip():
			raise Invalid([_error(["name"], "Required")])
		extra = [_error([str(k)], "Unknown property") for k in body if k not in ("name", HASH_KEY)]
		if extra:
			raise Invalid(extra)
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			self._check_rev(document_rev(raw, self._kind), rev)
			self._write(path, { **raw, "name": body["name"].strip() })
			return self._present(self._read(path))

	def delete_document(self, doc_id: str, rev: Any) -> None:
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			self._check_rev(document_rev(raw, self._kind), rev)
			os.remove(path)

	def _tasks_only(self) -> None:
		if self._kind is not TASKS:
			raise ScheduleStoreError("single-item changes are only for timer tasks")

	def add_item(self, doc_id: str, body: dict) -> dict:
		self._tasks_only()
		item = self._validated_item(body)
		if "id" in item:
			raise Invalid([_error(["id"], "Ids are generated by the server")])
		item = {k: v for k, v in item.items() if k != HASH_KEY}
		item.setdefault("title", "")
		item.setdefault("enabled", True)
		item["id"] = str(uuid.uuid4())
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			self._write(path, { **raw, "items": [*raw.get("items", []), item] })
			return self._present_item(self._read(path), item)

	def replace_item(self, doc_id: str, item_id: str, body: dict) -> dict:
		self._tasks_only()
		rev = body.get(HASH_KEY) if isinstance(body, dict) else None
		item = self._validated_item(body)
		if item.get("id", item_id) != item_id:
			raise Invalid([_error(["id"], "ID mismatch")])
		new = {k: v for k, v in item.items() if k != HASH_KEY}
		new.setdefault("title", "")
		new.setdefault("enabled", True)
		new["id"] = item_id
		return self._change_item(doc_id, item_id, rev, lambda old: new)

	def patch_item(self, doc_id: str, item_id: str, patch: dict) -> dict:
		self._tasks_only()
		rev = patch.get(HASH_KEY) if isinstance(patch, dict) else None
		if not isinstance(patch, dict):
			raise Invalid([_error([], "Expected an object")])
		errors = check_item_shape(patch, partial=True)
		if "id" in patch and patch["id"] != item_id:
			errors.append(_error(["id"], "ID mismatch"))
		# a required part cannot be removed with null
		errors.extend(_error([k], "Required") for k in ("trigger", "task") if k in patch and patch[k] is None)
		for key in ("title", "enabled"):
			if key in patch and patch[key] is None:
				errors.append(_error([key], "Required"))
		task = patch.get("task")
		if isinstance(task, dict):
			errors.extend(_error(["task", k], "Required") for k in TASK_KEYS if k in task and task[k] is None)
		if errors:
			raise Invalid(errors)
		body = {k: v for k, v in patch.items() if k not in (HASH_KEY, "id", "trigger")}
		def apply(old: dict) -> dict:
			merged = merge_patch(old, body)
			if "trigger" in patch:
				merged["trigger"] = copy.deepcopy(patch["trigger"])	# a trigger is replaced whole, not merged
			return merged
		# the plugin and its content are only checked when the patch touches them: renaming or pausing a task whose stored
		# content is already incomplete must still work
		return self._change_item(doc_id, item_id, rev, apply, validate_result=True, validate_task="task" in patch)

	def _change_item(self, doc_id: str, item_id: str, rev: Any, make: Callable[[dict], dict], validate_result: bool = False, validate_task: bool = True) -> dict:
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			idx = self._index(raw, item_id)
			current = self._present_item(raw, raw["items"][idx])
			self._check_rev(current[HASH_KEY], rev)
			new = make(raw["items"][idx])
			if validate_result:
				candidate = { k: v for k, v in new.items() if k != HASH_KEY }
				errors = check_item_shape(candidate) or (self._validate_item(candidate) if validate_task else [])
				if errors:
					raise Invalid(errors)
			items = list(raw["items"])
			items[idx] = new
			self._write(path, { **raw, "items": items })
			return self._present_item(self._read(path), new)

	def delete_item(self, doc_id: str, item_id: str, rev: Any) -> dict:
		self._tasks_only()
		path = self._find(doc_id)
		with self._lock_for(path):
			raw = self._read(path)
			idx = self._index(raw, item_id)
			self._check_rev(self._present_item(raw, raw["items"][idx])[HASH_KEY], rev)
			items = [x for i, x in enumerate(raw["items"]) if i != idx]
			self._write(path, { **raw, "items": items })
			return self._present(self._read(path))
