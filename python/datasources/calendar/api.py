import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Body

from ...task.async_http_worker_pool import AsyncHttpWorkerPool
from ...utils.url_guard import UrlRefused, fetch_checked
from ...web.deps import TOD
from .calendar import device_now
from .sources import HEADERS, MAX_CALENDAR_BYTES, NotACalendar, country_names, events_between, last_day, parse_calendar, web_url

logger = logging.getLogger(__name__)

# mounted under /api by the web application
calendar_router = APIRouter(prefix="/datasource/calendar")

TIMEOUT = httpx.Timeout(15.0)
SOON_DAYS = 30

def _when(day) -> str:
	return f"{day.day} {day:%b} {day.year}"

async def _test(value: Any, now: datetime) -> dict:
	"""
	Open the address as the data source would and say what came of it: `{ ok, message }`. Always an answer, never an error status.
	Besides how many events are coming, it says when a calendar runs out: nothing repeats (or every repeat ends), so past its last day
	it is empty, as a season's fixture list is. The message is ours (or the calendar's own name); it never holds the address or exception text.
	"""
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an address first." }
	async with httpx.AsyncClient(timeout=TIMEOUT, transport=AsyncHttpWorkerPool.default_transport) as client:
		try:
			body = await fetch_checked(client, web_url(value.strip()), HEADERS, MAX_CALENDAR_BYTES)
			cal = parse_calendar(body)
		except UrlRefused as refused:
			return { "ok": False, "message": str(refused) }
		except httpx.HTTPStatusError as bad:
			code = bad.response.status_code
			hint = " (this calendar needs a sign-in, which Test does not send)" if code in (401, 403) else ""
			return { "ok": False, "message": f"The server answered {code}{hint}." }
		except httpx.TimeoutException:
			return { "ok": False, "message": "The server did not answer in time." }
		except httpx.ConnectError:
			return { "ok": False, "message": "Could not connect to the server." }
		except httpx.HTTPError as failed:
			return { "ok": False, "message": f"The request failed ({type(failed).__name__})." }
		except NotACalendar:
			return { "ok": False, "message": "That is not a calendar file (a CalDAV address cannot be tested here)." }
		except RuntimeError as problem:
			# the size cap words its own message
			return { "ok": False, "message": str(problem) }
	zone = now.tzinfo
	assert zone is not None
	coming = events_between(cal, now, now + timedelta(days=SOON_DAYS), zone, "", None)
	name = str(cal.get("X-WR-CALNAME") or "").strip()[:60]
	message = f"{len(coming)} {'event' if len(coming) == 1 else 'events'} in the next {SOON_DAYS} days" + (f", from “{name}”" if name else "")
	last = last_day(cal, zone)
	if last is not None and last < now.date():
		return { "ok": False, "message": f"{message}. It ended on {_when(last)}: nothing repeats, so it shows nothing now. A new season or year may have a new address." }
	if last is not None:
		message += f". Nothing repeats: it has no events after {_when(last)}, and then needs a new address."
	return { "ok": True, "message": message }

@calendar_router.post('/test')
def test_calendar(tod: TOD, body: dict[str, Any] = Body(...)):
	# a plain `def`: it runs in the thread pool, where there is no event loop to be in the way of asyncio.run
	return asyncio.run(_test(body.get("value"), device_now(tod.current_time())))

@calendar_router.get('/lookups/countries')
def countries():
	return country_names()
