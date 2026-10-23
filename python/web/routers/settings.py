"""Settings documents and their schemas: device-wide (system/display/theme), per plugin and per datasource."""
import logging
from typing import Any, Callable, cast

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from ...model.configuration_manager import CollectInfoDict
from ..deps import CM
from ..documents import from_source, get_document, instance_properties, load_schema_lookups, load_schema_properties, put_document, secret_fields, settings_choices, settings_lookup_items
from ..errors import ApiError
from ..openapi import Choice, Descriptor, Document, Saved, answers, described

logger = logging.getLogger(__name__)
router = APIRouter()

# the device-wide settings; anything else is a 404, never a path into the file system
DEVICE_SETTINGS = ("system", "display", "theme", "master-prompts", "devices")

def _device_name(name: str) -> str:
	"""
	The device-wide settings the URL names. What is returned is the constant from our own list, never the URL's string,
	so nothing that builds a file path is made from request data.
	"""
	for known in DEVICE_SETTINGS:
		if known == name:
			return known
	raise ApiError(404, "Unknown settings.", "settings")

def _find_item(items: list[CollectInfoDict], item_id: str, kind: str) -> tuple[str, CollectInfoDict]:
	"""
	Only IDs that the plugin/datasource folders actually declare are accepted.
	Returns the declared ID (from the descriptor, not the URL's string) with the item: that is what may build a file path.
	"""
	for item in items:
		declared = item["info"].get("id")
		if isinstance(declared, str) and declared == item_id:
			return declared, item
	raise ApiError(404, f"Unknown {kind}.", None)

def _settings_properties(item: CollectInfoDict) -> list[dict]:
	# a descriptor may hold `"settings": null` (or no schema): that is a plugin without settings, not an error
	settings = item["info"].get("settings") or {}
	return (settings.get("schema") or {}).get("properties") or []

def _settings_schema_id(item: CollectInfoDict) -> str|None:
	"""The `_schema` of the settings a descriptor declares (their source: the stored document carries it)."""
	urn = (item["info"].get("settings") or {}).get("_schema")
	return urn if isinstance(urn, str) else None

def _names(properties: list[dict]) -> list[str]:
	"""The keys the settings schema declares: any other stored value is masked when served (see `get_document`)."""
	return [p["name"] for p in properties if isinstance(p, dict) and isinstance(p.get("name"), str)]

def _settings_lookups(item: CollectInfoDict) -> dict:
	settings = item["info"].get("settings") or {}
	return (settings.get("schema") or {}).get("lookups") or {}

def _settings_lookup_choices(item: CollectInfoDict, lookup_name: str, stored: dict|None, stored_of: Callable[[str], dict|None]|None = None) -> list[dict]:
	"""
	The choices of one of the item's `settings` lookups (of its instance settings or its settings), from the settings it keeps. Only a lookup the descriptor declares (with a `settings` list) is served;
	what is read is our own declared name, never the URL's string.
	"""
	# a task's fields choose from the lists, and so may a field of the settings themselves (a row naming an entry of another list)
	_, lookups = instance_properties(cast(dict, item))
	for declared, definition in [*lookups.items(), *_settings_lookups(item).items()]:
		if declared == lookup_name and isinstance(definition, dict) and "settings" in definition:
			# `from` names another data source whose list this one chooses from, or a capability whose provider's (`from_source`: an id of ours, or none)
			other = definition.get("from")
			return settings_lookup_items(definition, stored if other is None else (stored_of(str(other)) if stored_of else None))
	raise ApiError(404, "Unknown lookup.", None)

@router.get('/settings/{name}', **described(Document))
def get_device_settings(name: str, cm: CM):
	name = _device_name(name)
	cob = cm.settings_manager().open(name)
	return get_document(f"{name}-settings", cob)

@router.put('/settings/{name}', **answers(Saved))
def put_device_settings(name: str, cm: CM, body: dict[str, Any] = Body(...)):
	name = _device_name(name)
	cob = cm.settings_manager().open(name)
	schema = cm.read_schema(name)
	properties, lookups = load_schema_properties(schema), load_schema_lookups(schema)
	if any(p.get("type") == "schema" for p in properties):
		# what the document chooses (the display's device) brings its own fields, checked with the rest
		properties, lookups = settings_choices({ str(d["info"].get("id")): d for d in cm.enum_displays() }, properties, lookups, body)
	return put_document(f"{name}-settings", body, cob, properties, lookups=lookups, schema_id=(schema or {}).get("_schema"))

@router.get('/settings/{name}/defaults')
def get_device_defaults(name: str, cm: CM):
	"""
	The factory values of a device-wide document, from the copy shipped in the NVE (not the stored schema's, and not the stored document): what a "restore the
	default" button puts back in the form (the user saves it, or not). Only values, never the stored document's `_id` or `_rev`.
	"""
	return cm.shipped_settings(_device_name(name))

@router.get('/schemas/{name}')
def get_device_schema(name: str, cm: CM):
	name = _device_name(name)
	schema = cm.read_schema(name)
	if schema is None:
		raise ApiError(404, "File not found.", f"{name}-schema")
	# no lifetime, so a browser would keep an old copy for days (a schema that gained settings showed none): no-cache is "ask each time"
	return JSONResponse(schema, headers={ "Cache-Control": "no-cache" })

@router.get('/plugins/list', **described(list[Descriptor]))
def plugins_list(cm: CM):
	return [x.get("info") for x in cm.enum_plugins()]

@router.get('/displays/list', **described(list[Descriptor]))
def displays_list(cm: CM):
	"""The display devices that are installed (`python/displays`): what the display type's `schema` field chooses among, each with the settings of its own."""
	return [x.get("info") for x in cm.enum_displays()]

@router.get('/datasources/list', **described(list[Descriptor]))
def datasources_list(cm: CM):
	return [x.get("info") for x in cm.enum_datasources()]

@router.get('/plugins/{plugin_id}/settings', **described(Document))
def get_plugin_settings(plugin_id: str, cm: CM):
	declared, item = _find_item(cm.enum_plugins(), plugin_id, "plugin")
	cob = cm.plugin_manager(declared).open()
	properties = _settings_properties(item)
	return get_document(f"plugin-{declared}-settings", cob, secret_fields(properties), _names(properties))

@router.put('/plugins/{plugin_id}/settings', **answers(Saved))
def put_plugin_settings(plugin_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	declared, item = _find_item(cm.enum_plugins(), plugin_id, "plugin")
	cob = cm.plugin_manager(declared).open()
	properties = _settings_properties(item)
	return put_document(f"plugin-{declared}-settings", body, cob, properties, secret_fields(properties), _settings_lookups(item), schema_id=_settings_schema_id(item))

@router.get('/datasources/{datasource_id}/settings', **described(Document))
def get_datasource_settings(datasource_id: str, cm: CM):
	declared, item = _find_item(cm.enum_datasources(), datasource_id, "datasource")
	cob = cm.datasource_manager(declared).open()
	properties = _settings_properties(item)
	return get_document(f"datasource-{declared}-settings", cob, secret_fields(properties), _names(properties))

@router.put('/datasources/{datasource_id}/settings', **answers(Saved))
def put_datasource_settings(datasource_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	declared, item = _find_item(cm.enum_datasources(), datasource_id, "datasource")
	cob = cm.datasource_manager(declared).open()
	properties = _settings_properties(item)
	return put_document(f"datasource-{declared}-settings", body, cob, properties, secret_fields(properties), _settings_lookups(item), schema_id=_settings_schema_id(item))

@router.get('/plugins/{plugin_id}/lookups/{lookup}', **answers(list[Choice]))
def get_plugin_lookup(plugin_id: str, lookup: str, cm: CM):
	declared, item = _find_item(cm.enum_plugins(), plugin_id, "plugin")
	_, stored = cm.plugin_manager(declared).open().get()
	return _settings_lookup_choices(item, lookup, stored)

@router.get('/datasources/{datasource_id}/lookups/{lookup}', **answers(list[Choice]))
def get_datasource_lookup(datasource_id: str, lookup: str, cm: CM):
	sources = cm.enum_datasources()
	declared, item = _find_item(sources, datasource_id, "datasource")
	_, stored = cm.datasource_manager(declared).open().get()
	by_id = { str(d["info"].get("id")): d for d in sources }
	_, system = cm.settings_manager().open("system").get()
	def stored_of(other: str) -> dict|None:
		source = from_source(other, by_id, system)
		return cm.datasource_manager(source).open().get()[1] if source is not None else None
	return _settings_lookup_choices(item, lookup, stored, stored_of)
