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
from typing import Any, Iterable

from ..model.configuration_manager import ConfigurationObject, HASH_KEY, ID_KEY
from .errors import ApiError
from .visibility import hidden_names, null_hidden

logger = logging.getLogger(__name__)

NOT_FINITE = "Must be a finite number"
ENTER_THE_KEY = "Enter the key"

# What clients see instead of a stored secret. Sending it back unchanged means "keep the stored value".
SECRET_MASK = "********"

def secret_fields(properties: Iterable[dict]|None) -> set[str]:
	"""Names of the properties flagged `"secret": true` in a schema descriptor."""
	if not properties:
		return set()
	return { p["name"] for p in properties if isinstance(p, dict) and p.get("secret") is True and "name" in p }

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
		allowed = prop.get("enum")
		if not allowed:
			lookup = lookups.get(prop.get("lookup")) if prop.get("lookup") else None
			items = lookup.get("items") if isinstance(lookup, dict) else None
			allowed = [i.get("value") for i in items if isinstance(i, dict)] if isinstance(items, list) else None
		if allowed and value != "" and value not in allowed:
			return "Not one of the allowed values"
	elif ptype == "boolean":
		if not isinstance(value, bool):
			return "Expected boolean"
	elif ptype in ("number", "int"):
		if not _is_number(value):
			return f"Expected {ptype}"
		if isinstance(value, float) and not math.isfinite(value):
			return NOT_FINITE
		if ptype == "int" and isinstance(value, float) and not value.is_integer():
			return "Whole numbers only"
		if prop.get("min") is not None and value < prop["min"]:
			return f"Minimum {prop['min']:g}"
		if prop.get("max") is not None and value > prop["max"]:
			return f"Maximum {prop['max']:g}"
	elif ptype == "date":
		if value != "" and not _is_iso_date(value):
			return "Expected a date (YYYY-MM-DD)"
	elif ptype == "location":
		return _is_location(value)
	elif ptype == "schema":
		if not isinstance(value, str):
			return "Expected string"
	return None

def validate_properties(document: dict, properties: Iterable[dict]|None, lookups: dict|None = None) -> list[dict]:
	"""
	Check the values the schema declares against the same rules the form applies: type, `required`, `enum` / `items` lookup membership,
	`min` / `max`, `int`, `date` and `location`. Properties hidden by `visibleIf` are skipped. Unknown properties are kept untouched.
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
