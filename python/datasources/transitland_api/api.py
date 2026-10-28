"""
The Transitland provider's routes (mounted under /api, #429): the Test of the API key, the Test of a stop's key (My Stops), and the stop lookup (the stops near the
device). Each reads the **saved** key on the server when it needs one (the browser never sees it), and answers in our words: never the key, an address or
Transitland's text. The Tests always answer 200 `{ ok, message }`; the lookup is a list of choices, or an error the form shows under the field.
"""
import asyncio
from datetime import datetime
import logging
from typing import Any

from fastapi import APIRouter, Body

from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.errors import ApiError
from ...web.openapi import Choice, answers, test_route
from ..metering import QuotaUsedUp
from .transitland_api import DATASOURCE_ID, check_key, check_stop, has_key, nearby

logger = logging.getLogger(__name__)

# mounted under /api by the web application
transitland_router = APIRouter(prefix=f"/datasource/{DATASOURCE_ID}")

def _settings(cm: CM) -> tuple[Any, dict]:
	dscm = cm.datasource_manager(DATASOURCE_ID)
	_, settings = dscm.open().get()
	return dscm, settings or {}

@transitland_router.post('/test', **test_route())
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask Transitland with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`. Never kept."""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		value = _settings(cm)[1].get("apiKey")
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an API key first." }
	try:
		# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
		return asyncio.run(check_key(value.strip()))
	except Exception as e:
		logger.warning(f"Testing a Transitland key failed ({type(e).__name__}).")
		return { "ok": False, "message": "The key could not be tested." }

@transitland_router.post('/test-stop', **test_route())
def test_stop(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask Transitland, with the saved key, whether it knows a stop's key: `{ ok, message }` with the stop's name."""
	value = body.get("value")
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter or choose a stop first." }
	_, settings = _settings(cm)
	if not has_key(settings):
		return { "ok": False, "message": "Save the Transitland API key first." }
	try:
		return asyncio.run(check_stop(str(settings["apiKey"]).strip(), value.strip()))
	except Exception as e:
		logger.warning(f"Testing a Transitland stop failed ({type(e).__name__}).")
		return { "ok": False, "message": "The stop could not be tested." }

def _location(cm: CM) -> tuple[float, float]:
	_, system = cm.settings_manager().open("system").get()
	where = (system or {}).get("location")
	if not isinstance(where, dict) or not all(isinstance(where.get(k), (int, float)) and not isinstance(where.get(k), bool) for k in ("latitude", "longitude")):
		raise ApiError(409, "Set the device's location first (System settings): the stops listed are the ones near it.", "transitland-stops")
	return float(where["latitude"]), float(where["longitude"])

@transitland_router.get('/lookups/stops', **answers(list[Choice]))
def stop_choices(cm: CM):
	"""The stops near the device's location, within the radius of the settings, nearest first: kept a day, so opening the form spends no quota."""
	latitude, longitude = _location(cm)
	dscm, settings = _settings(cm)
	if not has_key(settings):
		raise ApiError(409, "Enter the Transitland API key and save the settings first.", "transitland-stops")
	try:
		return asyncio.run(nearby(dscm, settings, latitude, longitude, datetime.now().astimezone()))
	except (PermanentError, QuotaUsedUp, RuntimeError) as problem:
		# the provider's failures are in our words already (`refusal`, the budget guard)
		raise ApiError(502, str(problem), "transitland-stops") from None
	except Exception as e:
		logger.warning(f"Listing the stops near the device failed ({type(e).__name__}).")
		raise ApiError(502, "The stops near the device could not be listed.", "transitland-stops") from None
