import asyncio
import io
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body
from ...web.openapi import test_route
from PIL import Image

from ...task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context
from ...utils.upload_image import open_picture
from ...utils.url_guard import UrlRefused, fetch_checked
from .image_url import HEADERS, MAX_IMAGE_BYTES

logger = logging.getLogger(__name__)

# mounted under /api by the web application
image_url_router = APIRouter(prefix="/datasource/image-url")

TIMEOUT = httpx.Timeout(10.0)

async def _test(value: Any) -> dict:
	"""
	Fetch the address as the data source would and say what came of it: `{ ok, message }`. Always an answer, never an error status: the button is a question, and "no" is an answer.
	The message is ours; it never holds the address or exception text.
	"""
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an address first." }
	# a client of its own: the web app has no pool of its own, and a test is rare. The tests' transport is installed the same way as the pool's.
	async with httpx.AsyncClient(timeout=TIMEOUT, transport=AsyncHttpWorkerPool.default_transport, verify=tls_context()) as client:
		try:
			body = await fetch_checked(client, value.strip(), HEADERS, MAX_IMAGE_BYTES)
		except UrlRefused as refused:
			return { "ok": False, "message": str(refused) }
		except httpx.HTTPStatusError as bad:
			return { "ok": False, "message": f"The server answered {bad.response.status_code}." }
		except httpx.TimeoutException:
			return { "ok": False, "message": "The server did not answer in time." }
		except httpx.ConnectError:
			return { "ok": False, "message": "Could not connect to the server." }
		except httpx.HTTPError as failed:
			return { "ok": False, "message": f"The request failed ({type(failed).__name__})." }
		except RuntimeError as problem:
			# the size cap words its own message
			return { "ok": False, "message": str(problem) }
	try:
		picture = open_picture(body)
		kind = Image.open(io.BytesIO(body)).format
	except ValueError as problem:
		return { "ok": False, "message": str(problem) }
	return { "ok": True, "message": f"A {picture.width} x {picture.height} {kind} picture." }

@image_url_router.post('/test', **test_route())
def test_picture(body: dict[str, Any] = Body(...)):
	# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
	return asyncio.run(_test(body.get("value")))
