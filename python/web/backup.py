"""
What a restore does with the documents of an opened backup, before anything is written (#368): check each by the rules of the route that would have saved it, and say what would change.
Nothing in an archive is trusted. A problem is reported by the archive's file name and the field's path, **never by a value** (a document can hold a key); the summary is names only.
"""
import logging
from typing import Any, Mapping

from ..model.configuration_manager import ConfigurationManager, backup_file, create_hash
from ..model.schedule import SCHEMA_PLAYLIST, SCHEMA_TASKS
from ..model.schedule_store import PLAYLISTS, TASKS, Kind
from .documents import find_non_finite, load_schema_lookups, load_schema_properties, validate_properties
from .routers.settings import DEVICE_SETTINGS

logger = logging.getLogger(__name__)

# the settings whose change only shows after the device starts again (the panel is set up once)
RESTART_FOR = ("settings/display-settings.json",)

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

def check_documents(cm: ConfigurationManager, documents: Mapping[str, dict]) -> tuple[dict[str, dict], list[str], list[dict]]:
	"""
	`(accepted, left out, problems)`: the documents this device can take, the names it has no place for (a plugin or data source that is not installed, a settings document it does not have), and
	what is wrong with the others (`{ path: [file name, ...], message }`, the shape of a 422's `errors`). With any problem nothing is to be written.
	"""
	plugins = {p["info"].get("id"): p for p in cm.enum_plugins()}
	datasources = {d["info"].get("id"): d for d in cm.enum_datasources()}
	accepted: dict[str, dict] = {}
	left_out: list[str] = []
	problems: list[dict] = []
	for name, document in documents.items():
		parsed = backup_file(name)
		if parsed is None:
			left_out.append(name)
			continue
		found = [_problem(name, e["path"], e["message"]) for e in find_non_finite(document)]
		if parsed.area == "settings":
			device = parsed.stem.removesuffix("-settings")
			if not parsed.stem.endswith("-settings") or device not in DEVICE_SETTINGS:
				left_out.append(name)
				continue
			schema = cm.read_schema(device)
			found += _rules(name, document, load_schema_properties(schema), load_schema_lookups(schema))
		elif parsed.area == "schedules":
			found += _schedule_problems(name, document)
		else:
			owners = plugins if parsed.area == "plugins" else datasources
			if parsed.owner not in owners:
				left_out.append(name)
				continue
			if parsed.stem == "settings":
				properties, lookups = _settings_schema(owners[parsed.owner])
				found += _rules(name, document, properties, lookups)
		if found:
			problems += found
		else:
			accepted[name] = document
	return accepted, sorted(left_out), problems

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

def summarize(cm: ConfigurationManager, accepted: Mapping[str, dict]) -> dict:
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
	return { "files": files, "unchanged": same, "restartNeeded": any(f["name"] in RESTART_FOR for f in files) }
