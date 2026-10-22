"""Lookup lists the settings forms use to populate drop-downs."""
import zoneinfo
from datetime import date, datetime
from functools import lru_cache
from typing import Annotated, cast

from fastapi import APIRouter, Depends

from ...datasources.contracts import CONTRACTS
from ...model.configuration_manager import ConfigurationManager
from ..deps import get_cm
from ..errors import ApiError

router = APIRouter(prefix="/lookups")

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

@router.get('/timezone')
def list_timezones():
	return _timezone_options(date.today())

@router.get('/locale')
def list_locales():
	return LOCALES

@router.get('/providers/{capability}')
def list_providers(capability: str, cm: Annotated[ConfigurationManager, Depends(get_cm)]):
	"""The providers of a capability (#513) that are enabled, for the device's choice of one (`weatherProvider`): a capability of our own list, else a 404."""
	known = next((c for c in CONTRACTS if c == capability), None)
	if known is None:
		raise ApiError(404, "No such capability.", "lookups")
	items = [cast(dict, x["info"]) for x in cm.enum_datasources()]
	return [{ "name": str(i.get("name") or i.get("id")), "value": str(i.get("id")) } for i in items
		if known in (i.get("features") or []) and "api" in (i.get("features") or []) and not i.get("disabled")]
