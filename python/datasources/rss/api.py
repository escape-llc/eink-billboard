import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body

from ...task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context
from ...utils.url_guard import UrlRefused, fetch_checked
from .rss import HEADERS, MAX_FEED_BYTES, parse_stories, plain_text

logger = logging.getLogger(__name__)

# mounted under /api by the web application
rss_router = APIRouter(prefix="/datasource/rss")

TIMEOUT = httpx.Timeout(10.0)

async def _test(value: Any) -> dict:
	"""
	Open the address as the data source would and say what came of it: `{ ok, message }`. Always an answer, never an error status: the
	button is a question, and "no" is an answer. The message is ours (or the feed's own title); it never holds the address or exception text.
	"""
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an address first." }
	# a client of its own: the web app has no pool of its own, and a test is rare. The tests' transport is installed the same way as the pool's.
	async with httpx.AsyncClient(timeout=TIMEOUT, transport=AsyncHttpWorkerPool.default_transport, verify=tls_context()) as client:
		try:
			body = await fetch_checked(client, value.strip(), HEADERS, MAX_FEED_BYTES)
			stories = parse_stories(body, "test")
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
			# parse_stories and the size cap word their own messages
			return { "ok": False, "message": str(problem) }
	title = plain_text(stories[0].get("feed_title"), 60)
	count = len(stories)
	return { "ok": True, "message": f"{count} {'story' if count == 1 else 'stories'}" + (f", from “{title}”" if title else "") }

@rss_router.post('/test')
def test_feed(body: dict[str, Any] = Body(...)):
	# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
	return asyncio.run(_test(body.get("value")))
