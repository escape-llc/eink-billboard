"""
Helpers for the settings documents served by the API: secret handling, validation, optimistic concurrency.

A document is a dict stored as JSON. The API adds `_id` and `_rev` (a hash of the stored content) on the way out,
and requires the same `_rev` on the way back in; a stale `_rev` is a 409 conflict.
"""
import copy
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable

from ..model.configuration_manager import ConfigurationObject, HASH_KEY, ID_KEY
from .errors import ApiError
from .visibility import hidden_names, null_hidden

logger = logging.getLogger(__name__)

NOT_FINITE = "Must be a finite number"
ENTER_THE_KEY = "Enter the key"

NOT_A_LIST = "Expected a list"
NOT_AN_OBJECT = "Expected an object"
NOT_UNIQUE = "Must be unique"

# What clients see instead of a stored secret. Sending it back unchanged means "keep the stored value".
SECRET_MASK = "********"

@dataclass(frozen=True)
class Secrets:
	"""
	The `writeOnly` fields of a descriptor: `names` at the top of the document, and `rows` for a list of objects whose rows hold some
	(the list's name: its `items.key`, which matches a row sent back to the stored row it came from, and the row's secret fields).
	"""
	names: frozenset[str] = frozenset()
	rows: dict[str, tuple[str|None, frozenset[str]]] = field(default_factory=dict)

def secret_fields(properties: Iterable[dict]|None) -> Secrets:
	"""The properties flagged `"writeOnly": true` in a schema descriptor, and those of the rows of its lists."""
	names: set[str] = set()
	rows: dict[str, tuple[str|None, frozenset[str]]] = {}
	for p in properties or []:
		if not isinstance(p, dict) or "name" not in p:
			continue
		if p.get("writeOnly") is True:
			names.add(p["name"])
		items = p.get("items") if p.get("type") == "array" else None
		if isinstance(items, dict):
			inner = frozenset(f["name"] for f in items.get("properties") or [] if isinstance(f, dict) and f.get("writeOnly") is True and "name" in f)
			if inner:
				rows[p["name"]] = (items.get("key"), inner)
	return Secrets(frozenset(names), rows)

def _mask(values: dict, names: Iterable[str]) -> dict:
	out = dict(values)
	for name in names:
		if out.get(name):
			out[name] = SECRET_MASK
	return out

def redact(document: dict, secrets: Secrets) -> dict:
	"""A copy of the document where non-empty secret values (in the rows of a list too) are replaced with the mask."""
	out = _mask(document, secrets.names)
	for list_name, (_, inner) in secrets.rows.items():
		if isinstance(out.get(list_name), list):
			out[list_name] = [_mask(row, inner) if isinstance(row, dict) else row for row in out[list_name]]
	return out

def _restore(values: dict, stored: dict|None, names: Iterable[str]) -> dict:
	out = dict(values)
	for name in names:
		if out.get(name, SECRET_MASK) == SECRET_MASK and stored is not None and name in stored:
			out[name] = stored[name]
	return out

def restore_secrets(document: dict, stored: dict|None, secrets: Secrets) -> dict:
	"""
	A copy of the incoming document where masked or omitted secrets are replaced by the stored values.
	A row of a list takes its secrets from the stored row with the same key (its position may have changed); a row whose key is new
	has nothing to restore. A mask with no stored value to restore is left as it is: `unrestored_masks` reports it, so the literal mask
	is never stored as a secret.
	"""
	out = _restore(document, stored, secrets.names)
	for list_name, (key, inner) in secrets.rows.items():
		rows = out.get(list_name)
		if not isinstance(rows, list):
			continue
		before = (stored or {}).get(list_name)
		by_key = { row.get(key): row for row in (before if isinstance(before, list) else []) if key and isinstance(row, dict) and isinstance(row.get(key), str) }
		out[list_name] = [_restore(row, by_key.get(row.get(key)) if key else None, inner) if isinstance(row, dict) else row for row in rows]
	return out

def unrestored_masks(document: dict, secrets: Secrets) -> list[dict]:
	"""Errors for secrets that still hold the literal mask after `restore_secrets` (nothing stored to keep): the user must type the value."""
	errors = [{ "path": [name], "message": ENTER_THE_KEY } for name in sorted(secrets.names) if document.get(name) == SECRET_MASK]
	for list_name, (_, inner) in sorted(secrets.rows.items()):
		rows = document.get(list_name)
		for index, row in enumerate(rows if isinstance(rows, list) else []):
			if isinstance(row, dict):
				errors.extend({ "path": [list_name, str(index), name], "message": ENTER_THE_KEY } for name in sorted(inner) if row.get(name) == SECRET_MASK)
	return errors

def find_non_finite(value: Any, path: list[str]|None = None) -> list[dict]:
	"""
	Errors for every NaN or infinity anywhere in the value (unknown keys and nested lists/objects included).
	Python's JSON parser accepts them (NaN, Infinity, 1e999) but they cannot be sent back out, so a stored one would break every later GET.
	"""
	path = path or []
	if isinstance(value, float) and not math.isfinite(value):
		return [{ "path": path, "message": NOT_FINITE }]
	found: list[dict] = []
	if isinstance(value, dict):
		for k, v in value.items():
			found += find_non_finite(v, path + [str(k)])
	elif isinstance(value, list):
		for i, v in enumerate(value):
			found += find_non_finite(v, path + [str(i)])
	return found

def _is_number(v) -> bool:
	return isinstance(v, (int, float)) and not isinstance(v, bool)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# `format: "uri"`: a scheme, `://`, then a host part with no space. One expression here and in FormValidation.ts, so both sides read an address the same way.
_URI = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://([^/?#\s]+)(\S*)$")
DEFAULT_SCHEMES = ("http", "https")
# `format: "color"`: `#rgb` or `#rrggbb` (the same expression in FormValidation.ts)
_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
NOT_A_COLOR = "Enter a color like #3366cc"

def _is_uri(value: str, schemes: Iterable[str]|None) -> bool:
	found = _URI.match(value)
	return found is not None and found.group(1).lower() in (schemes or DEFAULT_SCHEMES)

def _is_iso_date(v) -> bool:
	if not isinstance(v, str) or not _ISO_DATE.match(v):
		return False
	try:
		date.fromisoformat(v)
		return True
	except ValueError:
		return False

def _is_location(v) -> str|None:
	"""None when `v` is a `{latitude, longitude}` pair in range, else the message."""
	if not isinstance(v, dict) or not _is_number(v.get("latitude")) or not _is_number(v.get("longitude")):
		return "Expected location"
	if not -90 <= v["latitude"] <= 90:
		return "Latitude is -90 to 90"
	if not -180 <= v["longitude"] <= 180:
		return "Longitude is -180 to 180"
	return None

def _check_value(prop: dict, value: Any, lookups: dict) -> str|None:
	"""The message when `value` (not null) breaks the field's rules, else None. These are the rules of `FormValidation.ts` (see AGENTS.md)."""
	ptype = prop.get("type")
	if ptype == "string":
		if not isinstance(value, str):
			return "Expected string"
		if prop.get("format") == "date":
			return None if value == "" or _is_iso_date(value) else "Expected a date (YYYY-MM-DD)"
		if prop.get("format") == "uri" and value != "" and not _is_uri(value, prop.get("schemes")):
			return "Enter a valid URL"
		if prop.get("format") == "color" and value != "" and not _COLOR.match(value):
			return NOT_A_COLOR
		# a write-only field's mask stands for the stored value (restored before a save is checked; one that cannot be is `unrestored_masks`'s)
		if value != "" and not (prop.get("writeOnly") is True and value == SECRET_MASK):
			if prop.get("minLength") is not None and len(value) < prop["minLength"]:
				return f"At least {prop['minLength']} characters"
			if prop.get("maxLength") is not None and len(value) > prop["maxLength"]:
				return f"At most {prop['maxLength']} characters"
			if prop.get("pattern") and not re.search(prop["pattern"], value):
				return "Not in the expected format"
		allowed = prop.get("enum")
		closed = False
		if not allowed:
			lookup = lookups.get(prop.get("lookup")) if prop.get("lookup") else None
			items = lookup.get("items") if isinstance(lookup, dict) else None
			allowed = [i.get("value") for i in items if isinstance(i, dict)] if isinstance(items, list) else None
			# a lookup resolved from stored settings is the whole truth: when it offers nothing, nothing is allowed
			closed = isinstance(lookup, dict) and lookup.get("closed") is True and allowed is not None
		if value != "" and (allowed or closed) and value not in (allowed or []):
			return "Not one of the allowed values"
	elif ptype == "boolean":
		if not isinstance(value, bool):
			return "Expected boolean"
	elif ptype in ("number", "integer"):
		if not _is_number(value):
			return f"Expected {ptype}"
		if isinstance(value, float) and not math.isfinite(value):
			return NOT_FINITE
		if ptype == "integer" and isinstance(value, float) and not value.is_integer():
			return "Whole numbers only"
		if prop.get("minimum") is not None and value < prop["minimum"]:
			return f"Minimum {prop['minimum']:g}"
		if prop.get("maximum") is not None and value > prop["maximum"]:
			return f"Maximum {prop['maximum']:g}"
	elif ptype == "location":
		return _is_location(value)
	elif ptype == "schema":
		if not isinstance(value, str):
			return "Expected string"
	return None

def is_multi_select(prop: dict) -> bool:
	"""An `array` of strings: the values chosen from the field's `lookup` or from `items.enum`."""
	return prop.get("type") == "array" and isinstance(prop.get("items"), dict) and prop["items"].get("type") == "string"

def _array_errors(prop: dict, value: Any, lookups: dict) -> list[dict]:
	"""
	Errors for the value of an `array` property, with paths relative to the property: `[]` for the list as a whole,
	`[index, name]` for a field of one item. The items' fields follow the same rules as any other property, and a row's
	`visibleIf` reads the fields of that row. `items.key` names the field whose value identifies an item: it must be unique
	(the later item is the one reported). A multi-select (`items.type` string) is a list of chosen values: `[index]` for one that is not a choice.
	"""
	if not isinstance(value, list):
		return [{ "path": [], "message": NOT_A_LIST }]
	errors: list[dict] = []
	minimum, maximum = prop.get("minItems"), prop.get("maxItems")
	if minimum is not None and len(value) < minimum:
		errors.append({ "path": [], "message": f"At least {minimum} items" })
	if maximum is not None and len(value) > maximum:
		errors.append({ "path": [], "message": f"At most {maximum} items" })
	items = prop.get("items") or {}
	if is_multi_select(prop):
		choice = { "type": "string", "enum": items.get("enum"), "lookup": prop.get("lookup") }
		for index, chosen in enumerate(value):
			message = _check_value(choice, chosen, lookups) if chosen is not None else "Required"
			if message:
				errors.append({ "path": [str(index)], "message": message })
		return errors
	item_props = items.get("properties") or []
	key = items.get("key")
	seen: set = set()
	for index, item in enumerate(value):
		if not isinstance(item, dict):
			errors.append({ "path": [str(index)], "message": NOT_AN_OBJECT })
			continue
		for e in validate_properties(item, item_props, lookups):
			errors.append({ "path": [str(index), *e["path"]], "message": e["message"] })
		identity = item.get(key) if key else None
		if isinstance(identity, str) and identity != "":
			if identity in seen:
				errors.append({ "path": [str(index), key], "message": NOT_UNIQUE })
			seen.add(identity)
	return errors

def validate_properties(document: dict, properties: Iterable[dict]|None, lookups: dict|None = None) -> list[dict]:
	"""
	Check the values the schema declares against the same rules the form applies: type, `required`, `enum` / `items` lookup membership,
	`minimum` / `maximum`, `integer`, `format: date`, `minLength` / `maxLength` / `pattern` and `location`. Properties hidden by `visibleIf` are skipped. Unknown properties are kept untouched.
	`null` (and "" for strings and dates) means unset: valid unless the property is `required`.
	Returns a list of `{ "path": [name], "message": str }`; empty when valid.
	"""
	errors: list[dict] = []
	lookups = lookups or {}
	properties = list(properties or [])
	hidden = hidden_names(properties, document)
	for prop in properties:
		name = prop.get("name") if isinstance(prop, dict) else None
		if not name or prop.get("type") == "header" or name in hidden:
			continue
		value = document.get(name)
		if value is None or value == "":
			if prop.get("required") is True:
				errors.append({ "path": [name], "message": "Required" })
			continue
		if prop.get("type") == "array":
			errors.extend({ "path": [name, *e["path"]], "message": e["message"] } for e in _array_errors(prop, value, lookups))
			continue
		message = _check_value(prop, value, lookups)
		if message:
			errors.append({ "path": [name], "message": message })
	return errors

def load_schema_properties(schema: dict|None) -> list[dict]:
	"""The `schema.properties` list of a schema document (`ConfigurationManager.read_schema`), or empty when there is none."""
	return ((schema or {}).get("schema") or {}).get("properties", [])

def get_document(id: str, cob: ConfigurationObject, secrets: Secrets|None = None, declared: Iterable[str]|None = None) -> dict:
	"""
	The stored document (secrets masked) with `_id` and `_rev` added; 404 when nothing is stored. With `declared` (the schema's property names),
	a value whose key the schema does not declare is masked too: a key left by a setting that moved away (the schema that marked it write-only is
	another's now) must not be sent as it is. The form lists such a key by name, under "No longer used", and leaves it out on save.
	"""
	rev, document = cob.get()
	if document is None:
		raise ApiError(404, f"{id}: not found", id, rev=None)
	secrets = secrets or Secrets()
	if declared is not None:
		known = set(declared)
		secrets = Secrets(secrets.names | { k for k in document if k not in known and not k.startswith("_") }, secrets.rows)
	document = redact(document, secrets)
	document[HASH_KEY] = rev
	document[ID_KEY] = id
	return document

def put_document(id: str, body: dict[str, Any], cob: ConfigurationObject, properties: Iterable[dict]|None = None, secrets: Secrets|None = None, lookups: dict|None = None) -> dict:
	"""
	Validate and store the incoming document.
	`_id` is optional, but when present it must match. `_rev` must match the stored revision (absent when nothing is stored yet).
	A `settings` lookup among `lookups` chooses from a list of this same document: the one being saved.
	"""
	secrets = secrets or Secrets()
	xid = body.get(ID_KEY, None)
	rev = body.get(HASH_KEY, None)
	if xid is not None and xid != id:
		raise ApiError(400, "ID mismatch", id, rev=rev)
	if rev is not None and not isinstance(rev, str):
		raise ApiError(400, f"{HASH_KEY} must be a string", id, rev=None)
	document = { k: v for k, v in body.items() if k not in (HASH_KEY, ID_KEY) }
	_, stored = cob.get()
	document = restore_secrets(document, stored, secrets)
	document = null_hidden(document, properties or [])
	errors = find_non_finite(document) + unrestored_masks(document, secrets)
	reported = { tuple(e["path"]) for e in errors }
	errors += [e for e in validate_properties(document, properties, resolve_settings_lookups(lookups or {}, document)) if tuple(e["path"]) not in reported]
	if errors:
		raise ApiError(422, "Settings validation failed", id, errors=errors)
	committed, new_rev = cob.save(rev, document)
	if not committed:
		current_rev, _ = cob.get()
		raise ApiError(409, "Revision mismatch: the settings changed since they were loaded.", id, rev=current_rev)
	return { "id": id, "success": True, "message": "Success", "rev": new_rev }

def load_schema_lookups(schema: dict|None) -> dict:
	"""The `schema.lookups` map of a schema document (`ConfigurationManager.read_schema`), or empty when there is none."""
	return ((schema or {}).get("schema") or {}).get("lookups", {}) or {}

def settings_lookup_items(lookup: Any, settings: dict|None) -> list[dict]:
	"""
	The choices of a `settings` lookup, `{"settings": "feeds", "value": "name", "label": "name"}`: one `{name, value}` per item of the list
	that the declaring plugin or data source keeps in its own stored settings. Empty when nothing is stored or the list is not one.
	"""
	if not isinstance(lookup, dict) or not isinstance(lookup.get("settings"), str):
		return []
	listed = (settings or {}).get(lookup["settings"])
	value_key = lookup.get("value", "name")
	label_key = lookup.get("label", value_key)
	return [
		{ "name": str(item.get(label_key, item.get(value_key))), "value": item.get(value_key) }
		for item in (listed if isinstance(listed, list) else [])
		if isinstance(item, dict) and isinstance(item.get(value_key), str) and item.get(value_key) != ""
	]

def resolve_settings_lookups(lookups: dict, settings: dict|None, settings_from: Callable[[str], dict|None]|None = None) -> dict:
	"""
	The lookups with every `settings` lookup turned into a closed `items` lookup of the stored choices (validation then checks membership).
	A lookup with `"from": "<data source id>"` chooses from the list another data source keeps (the Reminder Overlay's calendars are the Calendar's): `settings_from(id)` gives those settings,
	and without it the list is empty.
	"""
	def items(lk: dict) -> dict:
		own = lk.get("from")
		return { "items": settings_lookup_items(lk, settings if own is None else (settings_from(str(own)) if settings_from else None)), "closed": True }
	return { name: (items(lk) if isinstance(lk, dict) and "settings" in lk else lk) for name, lk in (lookups or {}).items() }

def instance_properties(item: dict) -> tuple[list[dict], dict]:
	"""The `instanceSettings` properties and lookups a plugin or datasource declares for a task's `content`."""
	schema = ((item["info"].get("instanceSettings") or {}).get("schema")) or {}
	return schema.get("properties") or [], schema.get("lookups") or {}

def _offers(source: dict, lookup: Any) -> bool:
	"""The data source has one of the `features` the lookup asks for (the choices the form offers: see `schemaFilterFeatures` in `BasicForm.vue`)."""
	wanted = lookup.get("features") if isinstance(lookup, dict) else None
	have = source["info"].get("features") or []
	if not have:
		return False
	return not wanted or any(f in have for f in wanted)

# how deep a choice inside a choice goes (a plugin's data source, then the parts a data source chooses: the Generated Image's text and image sources)
MAX_CHOICE_DEPTH = 3

def chosen_sources(datasources: dict, props: list[dict], lookups: dict, content: dict, depth: int = 0, seen: frozenset = frozenset()) -> list[dict]:
	"""
	The data sources `content` chooses, at any depth: a `schema` property that is shown and names a source that has one of its lookup's features,
	then that source's own `schema` properties in turn (the form does the same: the fields of a choice show under it). Each source once, at most
	MAX_CHOICE_DEPTH deep. The names are flat: every level's fields live in the one `content`.
	"""
	if depth >= MAX_CHOICE_DEPTH:
		return []
	found: list[dict] = []
	hidden = hidden_names(props, content)
	for prop in props:
		if prop.get("type") != "schema" or prop.get("name") in hidden:
			continue
		chosen = content.get(prop.get("name"))
		source = datasources.get(chosen) if isinstance(chosen, str) else None
		if source is None or chosen in seen or not _offers(source, lookups.get(prop.get("lookup"))):
			continue
		found.append(source)
		sprops, slookups = instance_properties(source)
		found.extend(chosen_sources(datasources, sprops, slookups, content, depth + 1, seen | { chosen }))
	return found

def _used_by(datasources: dict, source: dict) -> list[str]:
	"""The names of the data sources that choose this one inside them (an API data source chosen where only a page source can be)."""
	sid, have = source["info"].get("id"), set(source["info"].get("features") or [])
	names = []
	for other in datasources.values():
		props, lookups = instance_properties(other)
		asks = any(p.get("type") == "schema" and have & set((lookups.get(p.get("lookup")) or {}).get("features") or []) for p in props)
		if sid in (other["info"].get("uses") or []) or asks:
			names.append(str(other["info"].get("name") or other["info"].get("id")))
	return sorted(names)

def content_with_defaults(plugins: dict, datasources: dict, plugin_name: Any, content: dict) -> dict:
	"""
	`content` with each property its plugin and chosen data sources declare (at any depth, see `chosen_sources`), and it lacks, at the descriptor's
	`default` (a copy; the stored item is not changed). This is what the form shows and saves, so an item that was never saved again (older than
	the property, or written by hand) runs as the form says it would. A property with no default (null: the user supplies it) and a hidden one
	(see `visibleIf`) stay as they are.
	"""
	plugin = plugins.get(plugin_name)
	if plugin is None or not isinstance(content, dict):
		return content
	props, lookups = instance_properties(plugin)
	def defaults_of(fields: list[dict]) -> dict:
		return { p["name"]: p["default"] for p in fields if p.get("name") and p.get("default") is not None and p["name"] not in content }
	# a choice's default can choose the next one (a Generated Image track saved before its parts had a default): applied until nothing new is chosen
	chosen: list[dict] = []
	for _ in range(MAX_CHOICE_DEPTH + 1):
		again = chosen_sources(datasources, props, lookups, { **content, **defaults_of([*props, *(p for s in chosen for p in instance_properties(s)[0])]) })
		if [s["info"].get("id") for s in again] == [s["info"].get("id") for s in chosen]:
			break
		chosen = again
	candidates = [*props, *(p for s in chosen for p in instance_properties(s)[0])]
	wanted = { p["name"]: p["default"] for p in candidates if p.get("name") and p.get("type") != "header" and p.get("default") is not None and p["name"] not in content }
	if not wanted:
		return content
	hidden = hidden_names(candidates, { **content, **wanted })
	return { **content, **{ name: copy.deepcopy(value) for name, value in wanted.items() if name not in hidden } }

def plugin_content_errors(plugins: dict, datasources: dict, plugin_name: Any, content: dict, path: list,
		settings_of: Callable[[str, str], dict|None]|None = None) -> list[dict]:
	"""
	The plugin exists and `content` follows its settings and its chosen data sources' (at any depth: a source's own choice of others, see `chosen_sources`);
	`path` is where `plugin_name` and `content` live in the item (`["task"]` for a timer task, none for a track). Paths are flat (`["content", "<field>"]`):
	every level's fields live in the one `content`. `settings_of(kind, id)` gives the stored settings of a `"plugin"` or `"datasource"`, which the
	`settings` lookups of its instance fields choose from.
	"""
	plugin = plugins.get(plugin_name)
	if plugin is None:
		return [{ "path": [*path, "plugin_name"], "message": "Unknown plugin" }]
	def resolved(kind: str, item: dict, lookups: dict) -> dict:
		if not settings_of:
			return lookups
		return resolve_settings_lookups(lookups, settings_of(kind, item["info"].get("id")),
			(lambda other: settings_of("datasource", other) if other in datasources else None) if kind == "datasource" else None)
	errors: list[dict] = []
	def check(props: list[dict], lookups: dict, depth: int, seen: frozenset) -> None:
		errors.extend(validate_properties(content, props, lookups))
		hidden = hidden_names(props, content)
		for prop in props:
			# a hidden choice is not applicable: its data source's fields are not checked either
			chosen = content.get(prop.get("name")) if prop.get("type") == "schema" and prop.get("name") not in hidden else None
			if not (isinstance(chosen, str) and chosen):
				continue
			source = datasources.get(chosen)
			if source is None or not _offers(source, lookups.get(prop.get("lookup"))):
				# only the plugin's own choice: inside a source that chooses parts, a part of the wrong kind is just not one of the choices
				users = _used_by(datasources, source) if depth == 0 and source is not None and "api" in (source["info"].get("features") or []) else []
				# an API data source is chosen inside another (an `openai-image` track from before the Generated Image): say where it went
				message = f"{source['info'].get('name')} is now chosen inside {users[0]}: choose {users[0]} and pick it there" if source is not None and users else "Not one of the allowed values"
				errors.append({ "path": [prop["name"]], "message": message })
			elif depth + 1 < MAX_CHOICE_DEPTH and chosen not in seen:
				sprops, slookups = instance_properties(source)
				check(sprops, resolved("datasource", source, slookups), depth + 1, seen | { chosen })
	props, lookups = instance_properties(plugin)
	check(props, resolved("plugin", plugin, lookups), 0, frozenset())
	return [{ "path": [*path, "content", *e["path"]], "message": e["message"] } for e in errors]
