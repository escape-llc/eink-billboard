"""
What a restore does with the documents of an opened backup, before anything is written (#368): check each by the rules of the route that would have saved it, and say what would change.
Nothing in an archive is trusted. A problem is reported by the archive's file name and the field's path, **never by a value** (a document can hold a key); the summary is names only.
"""
import json
import logging
from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from ..datasources.calendar_sources.accounts import TOKENS_VERSION
from ..model.configuration_manager import BackupFile, ConfigurationManager, backup_file, create_hash
from ..model.migrations import MigrationGap, TooNew, migrate
from ..model.schedule import SCHEMA_PLAYLIST, SCHEMA_TASKS
from ..model.schema_versions import VERSION_KEY, SchemaId, file_version, schema_id_of
from ..plugins.kept_list import KEPT_LIST_VERSION
from ..model.schedule_store import PLAYLISTS, TASKS, Kind
from .documents import find_non_finite, load_schema_lookups, load_schema_properties, validate_properties
from .routers.settings import DEVICE_SETTINGS

logger = logging.getLogger(__name__)

# the settings whose change only shows after the device starts again (the panel is set up once)
RESTART_FOR = ("settings/display-settings.json",)

MANIFEST = "MANIFEST.json"
MANIFEST_FORMAT = 1

class Manifest(BaseModel):
	"""
	What a backup says about itself, as a member of the archive (the documents are what is checked, never this): its `format`, when it was `created` and the version each file carried (its `_schema`, or
	`_version N`). It lets the preview say where a backup came from and refuse a format this version cannot read.
	"""
	format: int = MANIFEST_FORMAT
	created: str
	files: dict[str, str]

def make_manifest(files: Mapping[str, bytes]) -> bytes:
	"""The manifest of the files about to be sealed (bytes, to be a member of the archive)."""
	versions: dict[str, str] = {}
	for name, content in files.items():
		try:
			document = json.loads(content)
		except ValueError:
			continue
		found = schema_id_of(document)
		versions[name] = str(found) if found is not None else f"{VERSION_KEY} {file_version(document)}"
	return Manifest(created=datetime.now().astimezone().isoformat(timespec="seconds"), files=versions).model_dump_json().encode("utf-8")

def take_manifest(files: dict[str, bytes]) -> Manifest|None:
	"""Remove the manifest from an opened archive's files and read it: None when there is none (a backup made before there were manifests) or it cannot be read (it only informs)."""
	raw = files.pop(MANIFEST, None)
	if raw is None:
		return None
	try:
		return Manifest.model_validate_json(raw)
	except ValidationError:
		return None

def _problem(name: str, path: list[str], message: str) -> dict:
	return { "path": [name, *path], "message": message }

def _rules(name: str, document: dict, properties: list[dict], lookups: dict) -> list[dict]:
	"""
	What the route that saves the document would say, except "Required": a backup holds what the device held, and a device keeps a setting that is not set yet (a data source's API key is `null` until it is typed in)
	though the form will not save without one. A value that is there still has to be the right kind, in range and in the expected format.
	"""
	return [_problem(name, e["path"], e["message"]) for e in validate_properties(document, properties, lookups) if e["message"] != "Required"]

def _settings_schema(item: Mapping[str, Any]|None) -> tuple[list[dict], dict]:
	"""The properties and lookups of a plugin's or data source's settings, as its descriptor gives them."""
	settings = ((item or {}).get("info") or {}).get("settings") or {}
	schema = settings.get("schema") or {}
	return schema.get("properties") or [], schema.get("lookups") or {}

def _schedule_problems(name: str, document: dict) -> list[dict]:
	"""A schedule document must be one the layers can load, and each of its entries the right shape (the plugins' own settings are not checked: a track that fails shows its error page, as ever)."""
	kinds: dict[Any, Kind] = { SCHEMA_TASKS: TASKS, SCHEMA_PLAYLIST: PLAYLISTS }
	kind = kinds.get(document.get("_schema"))
	if kind is None:
		return [_problem(name, ["_schema"], "Not a known kind of schedule")]
	items = document.get("items", [])
	if not isinstance(items, list):
		return [_problem(name, ["items"], "Expected a list")]
	problems: list[dict] = []
	for index, entry in enumerate(items):
		problems += [_problem(name, ["items", str(index), *p["path"]], p["message"]) for p in kind.check_shape(entry)]
	if not problems:
		try:
			kind.parse(document)
		except Exception:
			problems.append(_problem(name, [], "Does not load as a schedule"))
	return problems

# the files that have no source schema, by the start of their name: the integer `_version` this version of the code writes (`python/model/schema_versions.py`)
FILE_VERSIONS = (("list-", KEPT_LIST_VERSION), ("tokens", TOKENS_VERSION))

def _source_of(cm: ConfigurationManager, parsed: BackupFile, document: dict, owners: Mapping[str, Any]) -> tuple[str|None, dict|None]:
	"""The `_schema` and the defaults of the source of a settings or schedule document (None: it has no source schema, or this device has no such source)."""
	if parsed.area == "settings":
		schema = cm.read_schema(parsed.stem.removesuffix("-settings")) or {}
		return schema.get("_schema"), schema.get("default")
	if parsed.area == "schedules":
		found = schema_id_of(document)
		current = { SchemaId.parse(urn).family: urn for urn in (SCHEMA_PLAYLIST, SCHEMA_TASKS) if SchemaId.parse(urn) is not None }  # type: ignore[union-attr]
		return (current.get(found.family) if found is not None else None), None
	if parsed.stem == "settings":
		settings = ((owners.get(parsed.owner or "") or {}).get("info") or {}).get("settings") or {}
		return settings.get("_schema"), settings.get("default")
	return None, None

def _brought_up(name: str, parsed: BackupFile, document: dict, source: str|None, defaults: dict|None) -> tuple[dict, list[dict], dict|None]:
	"""
	The document as this version holds it: `(document, problems, what changed)`. A document with a source is migrated up to the source's number (`python/model/migrations.py`, the same function the
	start uses), so an old backup restores current-shaped; one from a **newer** version is a problem (it is not trusted and nothing is written). A file with only an integer `_version` is refused when
	it is newer than the code writes.
	"""
	if source is not None:
		try:
			upgraded, steps = migrate(source, document, defaults)
		except TooNew:
			return document, [_problem(name, [], "Made by a newer version of the app than this one: update the app, then restore it")], None
		except (MigrationGap, ValueError):
			return document, [_problem(name, [], "Cannot be brought up to this version")], None
		before = schema_id_of(document)
		after = SchemaId.parse(source)
		return upgraded, [], ({ "from": before.version if before is not None else 1, "to": after.version } if steps and after is not None else None)
	for prefix, current in FILE_VERSIONS:
		if parsed.stem.startswith(prefix) and file_version(document) > current:
			return document, [_problem(name, [VERSION_KEY], "Made by a newer version of the app than this one: update the app, then restore it")], None
	return document, [], None

def check_documents(cm: ConfigurationManager, documents: Mapping[str, dict]) -> tuple[dict[str, dict], list[str], list[dict], dict[str, dict]]:
	"""
	`(accepted, left out, problems, upgraded)`: the documents this device can take (brought up to this version first), the names it has no place for (a plugin or data source that is not installed, a
	settings document it does not have), what is wrong with the others (`{ path: [file name, ...], message }`, the shape of a 422's `errors`; one from a newer version is one), and which were upgraded
	(`{ name: { from, to } }`). With any problem nothing is to be written.
	"""
	plugins = {p["info"].get("id"): p for p in cm.enum_plugins()}
	datasources = {d["info"].get("id"): d for d in cm.enum_datasources()}
	accepted: dict[str, dict] = {}
	left_out: list[str] = []
	problems: list[dict] = []
	upgraded: dict[str, dict] = {}
	for name, document in documents.items():
		parsed = backup_file(name)
		if parsed is None:
			left_out.append(name)
			continue
		found = [_problem(name, e["path"], e["message"]) for e in find_non_finite(document)]
		if parsed.area == "settings" and (not parsed.stem.endswith("-settings") or parsed.stem.removesuffix("-settings") not in DEVICE_SETTINGS):
			left_out.append(name)
			continue
		if parsed.area in ("plugins", "datasources") and parsed.owner not in (plugins if parsed.area == "plugins" else datasources):
			left_out.append(name)
			continue
		source, defaults = _source_of(cm, parsed, document, plugins if parsed.area == "plugins" else datasources)
		document, stale, changed = _brought_up(name, parsed, document, source, defaults)
		found += stale
		if changed is not None:
			upgraded[name] = changed
		if stale:
			# from a newer version: nothing else is said about a document that is not ours to read
			problems += found
			continue
		if parsed.area == "settings":
			schema = cm.read_schema(parsed.stem.removesuffix("-settings"))
			found += _rules(name, document, load_schema_properties(schema), load_schema_lookups(schema))
		elif parsed.area == "schedules":
			found += _schedule_problems(name, document)
		else:
			owners = plugins if parsed.area == "plugins" else datasources
			if parsed.stem == "settings":
				properties, lookups = _settings_schema(owners[parsed.owner or ""])
				found += _rules(name, document, properties, lookups)
		if found:
			problems += found
		else:
			accepted[name] = document
	return accepted, sorted(left_out), problems, upgraded

def _label(name: str, document: Mapping[str, Any]) -> str:
	parsed = backup_file(name)
	if parsed is None:
		return "Unknown file"
	if parsed.area == "settings":
		return f"Settings: {parsed.stem.removesuffix('-settings')}"
	if parsed.area == "schedules":
		title = document.get("name")
		kind = "Timer tasks" if document.get("_schema") == SCHEMA_TASKS else "Playlist"
		return f"{kind}: {title[:80]}" if isinstance(title, str) and title else kind
	what = { "settings": "settings", "state": "state", "tokens": "sign-ins" }.get(parsed.stem, "kept list" if parsed.stem.startswith("list-") else "file")
	return f"{'Plugin' if parsed.area == 'plugins' else 'Data source'} {parsed.owner}: {what}"

def summarize(cm: ConfigurationManager, accepted: Mapping[str, dict], upgraded: Mapping[str, dict]|None = None) -> dict:
	"""
	What a restore would do, by name: each file that is new or would change, and how many are the same as what is here. Nothing a value could be read from (a revision hash is compared, not shown).
	`restartNeeded`: a changed document is only applied when the device starts again.
	"""
	files: list[dict] = []
	same = 0
	for name, document in accepted.items():
		target = cm.backup_target(name)
		current = target.get()[1] if target is not None else None
		if current is not None and create_hash(current) == create_hash(document):
			same += 1
			continue
		files.append({ "name": name, "label": _label(name, document), "status": "new" if current is None else "changed" })
	# the ones that come from an older version, by name and the numbers (the preview says they are brought up to date)
	older = [{ "name": f["name"], "label": f["label"], **(upgraded or {})[f["name"]] } for f in files if f["name"] in (upgraded or {})]
	return { "files": files, "unchanged": same, "upgraded": older, "restartNeeded": any(f["name"] in RESTART_FOR for f in files) }
