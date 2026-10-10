"""
Helpers for the settings documents served by the API: secret handling, validation, optimistic concurrency.

A document is a dict stored as JSON. The API adds `_id` and `_rev` (a hash of the stored content) on the way out,
and requires the same `_rev` on the way back in; a stale `_rev` is a 409 conflict.
"""
import json
import logging
import math
import re
from datetime import date
from typing import Any, Callable, Iterable

from ..model.configuration_manager import ConfigurationObject, HASH_KEY, ID_KEY
from .errors import ApiError
from .visibility import hidden_names, null_hidden

logger = logging.getLogger(__name__)

NOT_FINITE = "Must be a finite number"
ENTER_THE_KEY = "Enter the key"

NOT_A_LIST = "Expected a list"
NOT_UNIQUE = "Must be unique"

# What clients see instead of a stored secret. Sending it back unchanged means "keep the stored value".
SECRET_MASK = "********"

def secret_fields(properties: Iterable[dict]|None) -> set[str]:
	"""Names of the properties flagged `"writeOnly": true` in a schema descriptor."""
	if not properties:
		return set()
	return { p["name"] for p in properties if isinstance(p, dict) and p.get("writeOnly") is True and "name" in p }

def redact(document: dict, secrets: set[str]) -> dict:
	"""A copy of the document where non-empty secret values are replaced with the mask."""
	out = dict(document)
	for name in secrets:
		if out.get(name):
			out[name] = SECRET_MASK
	return out

def restore_secrets(document: dict, stored: dict|None, secrets: set[str]) -> dict:
	"""
	A copy of the incoming document where masked or omitted secrets are replaced by the stored values.
	A mask with no stored value to restore is left as it is: `unrestored_masks` reports it, so the literal mask is never stored as a secret.
	"""
	out = dict(document)
	for name in secrets:
		if out.get(name, SECRET_MASK) == SECRET_MASK and stored is not None and name in stored:
			out[name] = stored[name]
	return out

def unrestored_masks(document: dict, secrets: set[str]) -> list[dict]:
	"""Errors for secrets that still hold the literal mask after `restore_secrets` (nothing stored to keep): the user must type the value."""
	return [{ "path": [name], "message": ENTER_THE_KEY } for name in sorted(secrets) if document.get(name) == SECRET_MASK]

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
		if value != "":
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

def _array_errors(prop: dict, value: Any, lookups: dict) -> list[dict]:
	"""
	Errors for the value of an `array` property, with paths relative to the property: `[]` for the list as a whole,
	`[index, name]` for a field of one item. The items' fields follow the same rules as any other property.
	`items.key` names the field whose value identifies an item: it must be unique (the later item is the one reported).
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
	item_props = items.get("properties") or []
	key = items.get("key")
	seen: set = set()
	for index, item in enumerate(value):
		if not isinstance(item, dict):
			errors.append({ "path": [str(index)], "message": "Expected an object" })
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

def load_schema_properties(schema_path: str) -> list[dict]:
	"""The `schema.properties` list of a schema file, or empty when it is missing or unreadable."""
	try:
		with open(schema_path, 'r', encoding='utf-8') as f:
			return json.load(f).get("schema", {}).get("properties", [])
	except (OSError, ValueError):
		return []

def get_document(id: str, cob: ConfigurationObject, secrets: set[str]|None = None) -> dict:
	"""The stored document (secrets masked) with `_id` and `_rev` added; 404 when nothing is stored."""
	rev, document = cob.get()
	if document is None:
		raise ApiError(404, f"{id}: not found", id, rev=None)
	document = redact(document, secrets or set())
	document[HASH_KEY] = rev
	document[ID_KEY] = id
	return document

def put_document(id: str, body: dict[str, Any], cob: ConfigurationObject, properties: Iterable[dict]|None = None, secrets: set[str]|None = None, lookups: dict|None = None) -> dict:
	"""
	Validate and store the incoming document.
	`_id` is optional, but when present it must match. `_rev` must match the stored revision (absent when nothing is stored yet).
	"""
	secrets = secrets or set()
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
	errors += [e for e in validate_properties(document, properties, lookups) if tuple(e["path"]) not in reported]
	if errors:
		raise ApiError(422, "Settings validation failed", id, errors=errors)
	committed, new_rev = cob.save(rev, document)
	if not committed:
		current_rev, _ = cob.get()
		raise ApiError(409, "Revision mismatch: the settings changed since they were loaded.", id, rev=current_rev)
	return { "id": id, "success": True, "message": "Success", "rev": new_rev }

def load_schema_lookups(schema_path: str) -> dict:
	"""The `schema.lookups` map of a schema file, or empty when it is missing or unreadable."""
	try:
		with open(schema_path, 'r', encoding='utf-8') as f:
			return json.load(f).get("schema", {}).get("lookups", {}) or {}
	except (OSError, ValueError):
		return {}

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

def resolve_settings_lookups(lookups: dict, settings: dict|None) -> dict:
	"""The lookups with every `settings` lookup turned into a closed `items` lookup of the stored choices (validation then checks membership)."""
	return {
		name: ({ "items": settings_lookup_items(lk, settings), "closed": True } if isinstance(lk, dict) and "settings" in lk else lk)
		for name, lk in (lookups or {}).items()
	}

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

def plugin_content_errors(plugins: dict, datasources: dict, plugin_name: Any, content: dict, path: list,
		settings_of: Callable[[str, str], dict|None]|None = None) -> list[dict]:
	"""
	The plugin exists and `content` follows its settings (and its data source's); `path` is where `plugin_name` and `content` live in the item (`["task"]` for a timer task, none for a track).
	`settings_of(kind, id)` gives the stored settings of a `"plugin"` or `"datasource"`, which the `settings` lookups of its instance fields choose from.
	"""
	plugin = plugins.get(plugin_name)
	if plugin is None:
		return [{ "path": [*path, "plugin_name"], "message": "Unknown plugin" }]
	props, lookups = instance_properties(plugin)
	if settings_of:
		lookups = resolve_settings_lookups(lookups, settings_of("plugin", plugin["info"].get("id")))
	errors = validate_properties(content, props, lookups)
	hidden = hidden_names(props, content)
	for prop in props:
		# a hidden choice is not applicable: its data source's fields are not checked either
		chosen = content.get(prop.get("name")) if prop.get("type") == "schema" and prop.get("name") not in hidden else None
		if isinstance(chosen, str) and chosen:
			source = datasources.get(chosen)
			if source is None or not _offers(source, lookups.get(prop.get("lookup"))):
				errors.append({ "path": [prop["name"]], "message": "Not one of the allowed values" })
			else:
				sprops, slookups = instance_properties(source)
				if settings_of:
					slookups = resolve_settings_lookups(slookups, settings_of("datasource", source["info"].get("id")))
				errors.extend(validate_properties(content, sprops, slookups))
	return [{ "path": [*path, "content", *e["path"]], "message": e["message"] } for e in errors]
