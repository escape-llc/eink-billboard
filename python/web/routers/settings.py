"""Settings documents and their schemas: device-wide (system/display/theme), per plugin and per datasource."""
import logging
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse

from ...model.configuration_manager import CollectInfoDict, ConfigurationManager
from ..deps import CM
from ..documents import get_document, load_schema_lookups, load_schema_properties, put_document, secret_fields
from ..errors import ApiError

logger = logging.getLogger(__name__)
router = APIRouter()

# the device-wide settings; anything else is a 404, never a path into the file system
DEVICE_SETTINGS = ("system", "display", "theme")

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
	return item["info"].get("settings", {}).get("schema", {}).get("properties", [])

@router.get('/settings/{name}')
def get_device_settings(name: str, cm: CM):
	name = _device_name(name)
	cob = cm.settings_manager().open(name)
	return get_document(f"{name}-settings", cob)

@router.put('/settings/{name}')
def put_device_settings(name: str, cm: CM, body: dict[str, Any] = Body(...)):
	name = _device_name(name)
	cob = cm.settings_manager().open(name)
	properties = load_schema_properties(cm.schema_path(name))
	return put_document(f"{name}-settings", body, cob, properties, lookups=load_schema_lookups(cm.schema_path(name)))

@router.get('/schemas/{name}')
def get_device_schema(name: str, cm: CM):
	name = _device_name(name)
	path = cm.schema_path(name)
	try:
		return FileResponse(path, media_type="application/json")
	except FileNotFoundError:
		raise ApiError(404, "File not found.", f"{name}-schema")

@router.get('/plugins/list')
def plugins_list(cm: CM):
	return [x.get("info") for x in cm.enum_plugins()]

@router.get('/datasources/list')
def datasources_list(cm: CM):
	return [x.get("info") for x in cm.enum_datasources()]

@router.get('/plugins/{plugin_id}/settings')
def get_plugin_settings(plugin_id: str, cm: CM):
	declared, item = _find_item(cm.enum_plugins(), plugin_id, "plugin")
	cob = cm.plugin_manager(declared).open()
	return get_document(f"plugin-{declared}-settings", cob, secret_fields(_settings_properties(item)))

@router.put('/plugins/{plugin_id}/settings')
def put_plugin_settings(plugin_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	declared, item = _find_item(cm.enum_plugins(), plugin_id, "plugin")
	cob = cm.plugin_manager(declared).open()
	properties = _settings_properties(item)
	return put_document(f"plugin-{declared}-settings", body, cob, properties, secret_fields(properties))

@router.get('/datasources/{datasource_id}/settings')
def get_datasource_settings(datasource_id: str, cm: CM):
	declared, item = _find_item(cm.enum_datasources(), datasource_id, "datasource")
	cob = cm.datasource_manager(declared).open()
	return get_document(f"datasource-{declared}-settings", cob, secret_fields(_settings_properties(item)))

@router.put('/datasources/{datasource_id}/settings')
def put_datasource_settings(datasource_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	declared, item = _find_item(cm.enum_datasources(), datasource_id, "datasource")
	cob = cm.datasource_manager(declared).open()
	properties = _settings_properties(item)
	return put_document(f"datasource-{declared}-settings", body, cob, properties, secret_fields(properties))
