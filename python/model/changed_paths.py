"""
What a change of a stored file changes in the web API (#549): the GET routes whose answer may now be different, as their paths (`/api/settings/system`).
A page that keeps the answers it read by their address asks again for every one a path is the start of, by whole segments: `/api/schedule` is every
schedule route, `/api/datasources/rss` the RSS Feed's settings and lookups, and `/api` (`EVERYTHING`) all of them.

The watcher is the source, not the routes: a file saved by the device's command line, edited by hand or written by a restore changes the answers as a
save through the API does. So the paths are worked out from the file alone:
- a device setting (`settings/system-settings.json`) is its route; the system settings also choose the providers that `from` lookups read and the zone
  of the timeline, and the display settings choose which of the header's pins are the panel's (`/api/system/gpio-pins`);
- a schedule file is every schedule route (a file's name does not say which document it holds, and a deleted file cannot be read to find out);
- a plugin's or data source's `settings.json` is its routes (a data source's own router's too); a provider's (a data source with `api` features) also changes the device's choices of each
  capability it supplies (`/api/lookups/providers/<data-*>`) and every lookup that reads its lists (`"from"` its id or one of its capabilities);
- what the device keeps for itself (kept lists, downloads, answers, sign-in tokens, the `state` area) is no route's answer: nothing.

A path is made of our own names: a plugin or data source by the id its descriptor declares, a device setting or schema only when its name is a leaf name.
Never a value, so the telemetry link that carries them says nothing a GET would not.
"""
import os
from typing import Any, Callable, Iterable, Mapping

from .configuration_manager import CollectInfoDict, ConfigurationManager, leaf_name

EVERYTHING = "/api"
# more than this many is everything: a telemetry event's lists are short (`telemetry_hub.MAX_ITEMS`)
MAX_PATHS = 20
SETTINGS_SUFFIX = "-settings.json"
ITEM_SETTINGS = "settings.json"

def _leaf(name: str) -> str|None:
	try:
		return leaf_name(name)
	except ValueError:
		return None

def _capabilities(info: Any) -> list[str]:
	"""What a provider supplies: its `data-*` features, when it is a provider (`api`)."""
	features = [str(f) for f in (info.get("features") or [])]
	return [f for f in features if f.startswith("data-")] if "api" in features else []

def _from_lookups(items: Iterable[tuple[str, CollectInfoDict]], wanted: Callable[[str], bool]) -> list[str]:
	"""The lookup routes of every plugin and data source whose `settings` lookup reads another's list (`"from"`) for which `wanted(from)` holds."""
	paths: list[str] = []
	for kind, item in items:
		info: Mapping[str, Any] = item["info"]
		owner = info.get("id")
		if not isinstance(owner, str):
			continue
		for section in ("settings", "instanceSettings"):
			lookups = ((info.get(section) or {}).get("schema") or {}).get("lookups") or {}
			for name, lookup in lookups.items():
				if isinstance(lookup, dict) and isinstance(lookup.get("from"), str) and wanted(lookup["from"]):
					paths.append(f"/api/{kind}/{owner}/lookups/{name}")
	return paths

def _items(cm: ConfigurationManager) -> list[tuple[str, CollectInfoDict]]:
	return [("plugins", p) for p in cm.enum_plugins()] + [("datasources", d) for d in cm.enum_datasources()]

def _declared(items: list[CollectInfoDict], folder: str) -> CollectInfoDict|None:
	"""The descriptor whose declared id is this folder's name (a data source's folder is its id), or None: a folder of no installed item."""
	return next((x for x in items if x["info"].get("id") == folder), None)

def _unique(paths: list[str]) -> list[str]:
	kept = list(dict.fromkeys(paths))
	return kept if len(kept) <= MAX_PATHS else [EVERYTHING]

def changed_paths(cm: ConfigurationManager, path: str|bytes) -> list[str]:
	"""The paths of the API routes a change of this stored file (created, modified, moved onto or deleted) may change; none for a file no route reads."""
	rel = os.path.relpath(os.fsdecode(path), cm.STORAGE_PATH).replace("\\", "/")
	if rel.startswith(".."):
		return []
	parts = rel.split("/")
	area, name = parts[0], parts[-1]
	if area == "schedules" and len(parts) == 2 and name.endswith(".json"):
		return ["/api/schedule"]
	if area == "settings" and len(parts) == 2 and name.endswith(SETTINGS_SUFFIX):
		stem = _leaf(name[:-len(SETTINGS_SUFFIX)])
		if stem is None:
			return []
		if stem == "access":
			# the password's hash is no route's answer; whether the device asks for a sign-in is
			return ["/api/access"]
		paths = [f"/api/settings/{stem}"]
		if stem == "system":
			# the device's provider of a capability is a system setting, and the timeline is in the device's zone
			paths += _from_lookups(_items(cm), lambda source: source.startswith("data-"))
			paths.append("/api/schedule/tasks")
		if stem == "display":
			# the header's pins a button may use depend on the display type the settings choose (the panel's lines are not available)
			paths.append("/api/system/gpio-pins")
		return _unique(paths)
	if area == "schemas" and len(parts) == 2 and name.endswith(".json"):
		stem = _leaf(name[:-len(".json")])
		return [f"/api/schemas/{stem}"] if stem is not None else []
	if area in ("plugins", "datasources") and len(parts) == 3 and name == ITEM_SETTINGS:
		items = _items(cm)
		item = _declared([x for kind, x in items if kind == area], parts[1])
		if item is None:
			return []
		declared = str(item["info"]["id"])
		if area == "plugins":
			return [f"/api/plugins/{declared}"]
		capabilities = _capabilities(item["info"])
		# its settings and lookups, and the routes of its own router when it has one (a provider's model lists are read with its saved key)
		paths = [f"/api/datasources/{declared}"] + ([f"/api/datasource/{declared}"] if item["info"].get("router") else [])
		paths += [f"/api/lookups/providers/{c}" for c in capabilities]
		paths += _from_lookups(items, lambda source: source == declared or source in capabilities)
		return _unique(paths)
	return []
