"""
Helpers for the settings documents served by the API: secret handling, validation, optimistic concurrency.

A document is a dict stored as JSON. The API adds `_id` and `_rev` (a hash of the stored content) on the way out,
and requires the same `_rev` on the way back in; a stale `_rev` is a 409 conflict.
"""
import json
import logging
from typing import Any, Iterable

from ..model.configuration_manager import ConfigurationObject, HASH_KEY, ID_KEY
from .errors import ApiError

logger = logging.getLogger(__name__)

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
	"""A copy of the incoming document where masked or omitted secrets are replaced by the stored values."""
	out = dict(document)
	for name in secrets:
		if out.get(name, SECRET_MASK) == SECRET_MASK and stored is not None and name in stored:
			out[name] = stored[name]
	return out

_TYPE_CHECKS = {
	"string": lambda v: isinstance(v, str),
	"boolean": lambda v: isinstance(v, bool),
	"number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
	"int": lambda v: isinstance(v, int) and not isinstance(v, bool),
}

def validate_properties(document: dict, properties: Iterable[dict]|None) -> list[dict]:
	"""
	Check the value types of the properties the schema declares. Unknown properties are kept untouched.
	`null` is always accepted: unset values are stored that way.
	Returns a list of `{ "path": [name], "message": str }`; empty when valid.
	"""
	errors: list[dict] = []
	for prop in properties or []:
		name = prop.get("name") if isinstance(prop, dict) else None
		check = _TYPE_CHECKS.get(prop.get("type")) if name else None
		if check is None or name not in document or document[name] is None:
			continue
		if not check(document[name]):
			errors.append({ "path": [name], "message": f"Expected {prop.get('type')}" })
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

def put_document(id: str, body: dict[str, Any], cob: ConfigurationObject, properties: Iterable[dict]|None = None, secrets: set[str]|None = None) -> dict:
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
	errors = validate_properties(document, properties)
	if errors:
		raise ApiError(422, "Settings validation failed", id, errors=errors)
	committed, new_rev = cob.save(rev, document)
	if not committed:
		current_rev, _ = cob.get()
		raise ApiError(409, "Revision mismatch: the settings changed since they were loaded.", id, rev=current_rev)
	return { "id": id, "success": True, "message": "Success", "rev": new_rev }
