"""Lookup lists the settings forms use to populate drop-downs."""
import zoneinfo
from datetime import date, datetime
from functools import lru_cache
import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from ...datasources.contracts import CONTRACTS
from ...datasources.contracts.provider import ProviderContract
from ...datasources.data_source import DataSourceExecutionContext
from ...model.configuration_manager import CollectInfoDict, ConfigurationManager
from ...model.service_container import ServiceContainer
from ..deps import get_cm
from ..errors import ApiError
from ..openapi import Choice, answers

router = APIRouter(prefix="/lookups")
logger = logging.getLogger(__name__)

class ProviderChoice(Choice):
	"""A provider of a capability: `ready` when its own settings are complete (its name says so too)."""
	ready: bool

MAJOR_REGIONS = {
	"Africa", "America", "Antarctica", "Asia", "Atlantic",
	"Australia", "Europe", "Indian", "Pacific"
}

@lru_cache(maxsize=2)
def _timezone_options(day: date) -> list[dict]:
	"""Keyed by day so the displayed UTC offsets follow daylight saving changes."""
	options = []
	now = datetime.now()
	for tz_name in sorted(zoneinfo.available_timezones()):
		# Region/City, e.g. "America/New_York"
		parts = tz_name.split('/')
		if len(parts) >= 2 and parts[0] in MAJOR_REGIONS:
			offset = now.astimezone(zoneinfo.ZoneInfo(tz_name)).strftime('%z')
			display_offset = f"UTC{offset[:3]}:{offset[3:]}"
			# "America/Argentina/Buenos_Aires" -> "Argentina / Buenos Aires"
			city_name = " / ".join(parts[1:]).replace('_', ' ')
			options.append({ "name": f"{parts[0]}: {city_name} ({display_offset})", "value": tz_name })
	return options

LOCALES = [
	{"value": "en-US", "name": "English"},
	{"value": "es-ES", "name": "Español"},
	{"value": "fr-FR", "name": "Français"},
	{"value": "de-DE", "name": "Deutsch"}
]

@router.get('/timezone', **answers(list[Choice]))
def list_timezones():
	return _timezone_options(date.today())

@router.get('/locale', **answers(list[Choice]))
def list_locales():
	return LOCALES

def _set_up(cm: ConfigurationManager, item: CollectInfoDict) -> bool:
	"""Whether a provider says it is set up (`configured`, its own settings complete). One that cannot be made or asked is not."""
	try:
		source = cm.create_datasource(item)
		if not isinstance(source, ProviderContract):
			return False
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		dsec = DataSourceExecutionContext(root, (1, 1), datetime.now().astimezone())
		return source.configured(dsec.context_for(source))
	except Exception as e:
		logger.warning(f"Could not ask '{item['info'].get('id')}' whether it is set up ({type(e).__name__}).")
		return False

@router.get('/providers/{capability}', **answers(list[ProviderChoice]))
def list_providers(capability: str, cm: Annotated[ConfigurationManager, Depends(get_cm)]):
	"""
	The providers of a capability (#513) that are enabled, for the device's choice of one (`weatherProvider`): a capability of our own list, else a 404.
	One that is not set up says so in its name (choosing it is harmless: the device then takes one that is), and `ready` says it for a script.
	"""
	known = next((c for c in CONTRACTS if c == capability), None)
	if known is None:
		raise ApiError(404, "No such capability.", "lookups")
	providers = [x for x in cm.enum_datasources() if known in (x["info"].get("features") or []) and "api" in (x["info"].get("features") or []) and not x["info"].get("disabled")]
	answer = []
	for item in providers:
		name, ready = str(item["info"].get("name") or item["info"].get("id")), _set_up(cm, item)
		answer.append({ "name": name if ready else f"{name} (not set up)", "value": str(item["info"].get("id")), "ready": ready })
	return answer
