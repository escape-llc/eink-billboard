"""
The Comic Vine data source's routes (mounted under /api): the Test button of a task's series, which says what the search matches with the **saved** key
(read here on the server; the browser never sees it). Always 200 `{ ok, message }` in our words, never the address, the key or the site's text.
"""
import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Body

from ...model.configuration_manager import DatasourceConfigurationManager
from ...model.service_container import ServiceContainer
from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.openapi import test_route
from ..data_source import DataSourceExecutionContext
from .comicvine_api import ComicVineApi, comicvine_client, fetch

logger = logging.getLogger(__name__)

DATASOURCE_ID = "comicvine-api"

# mounted under /api by the web application
comicvine_router = APIRouter(prefix=f"/datasource/{DATASOURCE_ID}")

async def _test(cm, value: Any) -> dict:
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter a series to search for." }
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager(DATASOURCE_ID))
	dsec = DataSourceExecutionContext(root, (0, 0), datetime.now(timezone.utc))
	try:
		volume = await ComicVineApi(DATASOURCE_ID, "Comic Vine").open_async(dsec, { "request": "volume", "query": value })
	except (PermanentError, RuntimeError) as problem:
		# the source's failures are in our words already
		return { "ok": False, "message": str(problem) }
	except Exception as problem:
		logger.warning(f"The Comic Vine test failed ({type(problem).__name__}).")
		return { "ok": False, "message": "The search could not be made." }
	count = volume["issues"]
	detail = ", ".join(part for part in (volume["publisher"], volume["year"]) if part)
	return { "ok": True, "message": f"{volume['name']}" + (f" ({detail})" if detail else "") + f", {count} issue{'' if count == 1 else 's'}" }

@comicvine_router.post('/test', **test_route())
def test_series(cm: CM, body: dict[str, Any] = Body(...)):
	# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
	return asyncio.run(_test(cm, body.get("value")))

@comicvine_router.post('/test-key', **test_route())
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask Comic Vine with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`, always 200, in our words. Never kept. (`/test` is the series' Test.)"""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		_, settings = cm.datasource_manager(DATASOURCE_ID).open().get()
		value = (settings or {}).get("apiKey")
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an API key first." }
	async def ask() -> dict:
		async with comicvine_client() as client:
			await fetch(client, "search", value.strip(), { "query": "a", "resources": "volume", "limit": 1 })
		return { "ok": True, "message": "Comic Vine accepts this key." }
	try:
		return asyncio.run(ask())
	except (PermanentError, RuntimeError) as problem:
		# the source's failures are in our words already (a refused key, the limit, no answer)
		return { "ok": False, "message": str(problem) }
	except Exception as problem:
		logger.warning(f"Testing a Comic Vine key failed ({type(problem).__name__}).")
		return { "ok": False, "message": "The key could not be tested." }
