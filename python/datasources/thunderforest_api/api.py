"""
The Thunderforest data source's routes (mounted under /api): the Test button of the API key. It asks Thunderforest for the smallest map with the key typed, or the **saved** one
when the field shows the mask (read here on the server; the browser never sees it). Always 200 `{ ok, message }` in our words: never the key, the address or the service's text.
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body

from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.openapi import test_route
from .thunderforest_api import check_key

logger = logging.getLogger(__name__)

DATASOURCE_ID = "thunderforest-api"

# mounted under /api by the web application
thunderforest_router = APIRouter(prefix=f"/datasource/{DATASOURCE_ID}")

@thunderforest_router.post('/test', **test_route())
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask Thunderforest with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`. Never kept."""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		_, settings = cm.datasource_manager(DATASOURCE_ID).open().get()
		value = (settings or {}).get("apiKey")
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an API key first." }
	try:
		# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
		return asyncio.run(check_key(value.strip()))
	except Exception as e:
		logger.warning(f"Testing a Thunderforest key failed ({type(e).__name__}).")
		return { "ok": False, "message": "The key could not be tested." }
