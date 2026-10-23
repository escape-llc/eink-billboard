"""
Calendar Sources: a calendar provider (`CalendarApi`, `data-calendar`): the events of the iCal links, CalDAV servers, connected accounts and holiday sets
kept in its settings, and nothing drawn. The Calendar pages and the Reminder Overlay ask for a calendar provider with `dsec.provide(CalendarApi)`; what each
calendar answered is kept for the settings' `cacheHours`, so a page and an overlay of the same days make one read.

A calendar that cannot be read is a note in the answer (our words, never its address); the answer fails only when every chosen calendar does. A calendar
that has run out (nothing repeats, and its last event is past or near) says so in a note too.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool
from ..contracts.calendar import CalendarAnswer, CalendarApi, Event, device_now
from ..data_source import DataSourceExecutionContext
from ..metering import metered_client
from ..response_cache import cached
from .accounts import PROVIDERS, TokenStore, read_account_calendar
from .sources import NotACalendar, event_from_json, event_to_json, events_between, holiday_events, last_day, read_caldav, read_ical, safe_color

# what a calendar answered is kept this long (the data source's `cacheHours` setting says otherwise), shared by its pages and by the overlays that ask it for events
DEFAULT_CACHE_HOURS = 0.25
MIN_READ_DAYS = 8

@dataclass
class _Read:
	"""One read of the calendars: the day and zone it is for, and the notes it makes."""
	today: date
	zone: tzinfo
	now: datetime
	notes: list[str] = field(default_factory=list)

def _enabled(rows: Any) -> bool:
	return any(isinstance(r, dict) and r.get("enabled") is not False for r in (rows if isinstance(rows, list) else []))

def _chosen(rows: Any, names: Any, what: str) -> list[dict]:
	"""The enabled rows a task chose by name (none chosen: all of them). A name that is not in the settings cannot work until the task is fixed."""
	listed = [r for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict) and isinstance(r.get("name"), str)]
	if not names:
		return [r for r in listed if r.get("enabled") is not False]
	by_name = { r["name"]: r for r in listed }
	missing = [n for n in names if n not in by_name]
	if missing:
		raise PermanentError(f"The {what} '{missing[0]}' is not in the Calendar Sources settings.")
	return [by_name[n] for n in names if by_name[n].get("enabled") is not False]

def failure_reason(ex: BaseException) -> str:
	"""Why a calendar could not be read, in our words (an exception's text can hold the address, and a private address is a secret)."""
	if isinstance(ex, httpx.HTTPStatusError):
		code = ex.response.status_code
		return f"the server answered {code}" + (" (it needs a sign-in)" if code in (401, 403) else "")
	if isinstance(ex, httpx.TimeoutException):
		return "the server did not answer in time"
	if isinstance(ex, httpx.ConnectError):
		return "could not connect to the server"
	if isinstance(ex, NotACalendar):
		return "the answer is not a calendar"
	return type(ex).__name__

def _when(day: date) -> str:
	return f"{day.day} {day:%b} {day.year}"

def ran_out_note(name: str, last: date|None, today: date, shown_until: date) -> str|None:
	"""A footer note when a calendar has nothing after a day the page shows (or before it): its address may need changing for a new file."""
	if last is None or last >= shown_until:
		return None
	return f"{name} ended on {_when(last)}" if last < today else f"{name} has no events after {_when(last)}"

class CalendarSources(CalendarApi):
	"""The calendars and holiday sets of its settings, as a calendar provider: see `CalendarApi` for what it is asked and answers."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def configured(self, dsec: DataSourceExecutionContext) -> bool:
		"""Set up when it has a calendar or a holiday set that is enabled."""
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		return _enabled((settings or {}).get("calendars")) or _enabled((settings or {}).get("holidays"))

	async def _read_one(self, client: httpx.AsyncClient, entry: dict, start: datetime, end: datetime, read: _Read, settings: Mapping[str, Any], store: TokenStore,
			dscm: DatasourceConfigurationManager) -> list[Event]:
		"""The events of one calendar between two days: kept for `cacheHours` (the answer is the same for every page and task), with the notes it made."""
		async def fetch() -> Mapping[str, Any]:
			notes: list[str] = []
			found = await self._fetch_one(client, entry, start, end, read, settings, store, notes)
			return { "events": [event_to_json(e) for e in found], "notes": notes }
		# the key is only hashed into a file name (cache_file_name): the entry's secrets are not kept; an edited entry or another range is another answer
		key = f"events|{json.dumps(entry, sort_keys=True, default=str)}|{start.date()}|{end.date()}"
		answer = await cached(dscm, settings, key, read.now, fetch, DEFAULT_CACHE_HOURS)
		read.notes.extend(str(n) for n in answer.get("notes") or [])
		return [event_from_json(d, read.zone) for d in answer.get("events") or []]

	async def _fetch_one(self, client: httpx.AsyncClient, entry: dict, start: datetime, end: datetime, read: _Read, settings: Mapping[str, Any], store: TokenStore, notes: list[str]) -> list[Event]:
		name = entry["name"]
		color = safe_color(entry.get("color"))
		if entry.get("source") in PROVIDERS:
			return await read_account_calendar(client, entry, settings, store, start, end, read.zone)
		if entry.get("source") == "caldav":
			cals = await read_caldav(client, entry, start, end)
			return [e for cal in cals for e in events_between(cal, start, end, read.zone, name, color)]
		cal = await read_ical(client, entry)
		note = ran_out_note(name, last_day(cal, read.zone), read.today, (end - timedelta(microseconds=1)).date())
		if note:
			notes.append(note)
		return events_between(cal, start, end, read.zone, name, color)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> CalendarAnswer:
		"""
		The events between `start` and `end` (see `CalendarApi`), sorted, with the notes about calendars that could not be read or have run out. Each calendar's
		answer is kept for the settings' `cacheHours`. The days are read whole (from the midnight before `start` to the midnight after `end`, and at least
		`MIN_READ_DAYS` days), so one answer serves every range inside them; the caller picks the moments it wants.
		"""
		now = device_now(dsec.timestamp)
		zone = now.tzinfo or now.astimezone().tzinfo
		assert zone is not None
		start, end = params.get("start"), params.get("end")
		if not isinstance(start, datetime) or not isinstance(end, datetime):
			raise ValueError("A calendar is asked for the events between two moments (start, end).")
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		_, stored = dscm.open().get()
		settings: Mapping[str, Any] = stored or {}
		read = _Read(now.date(), zone, now)
		answer = CalendarAnswer()
		first = datetime.combine(start.astimezone(zone).date(), time(), zone)
		last_moment = end.astimezone(zone)
		last = datetime.combine(last_moment.date() + timedelta(days=0 if last_moment.time() == time() else 1), time(), zone)
		# a short range is read as the same number of days as the agenda's, so what a page and an overlay ask for the same days is one answer
		last = max(last, first + timedelta(days=MIN_READ_DAYS))
		# the connected accounts' tokens are kept by the same manager, beside the settings
		store = TokenStore(dscm)
		calendars = _chosen(settings.get("calendars"), params.get("calendars"), "calendar")
		holiday_sets = _chosen(settings.get("holidays"), params.get("holidaySets"), "holiday set")
		for entry in holiday_sets:
			answer.events.extend(holiday_events(entry, range(first.year, last.year + 1), zone))
		# a metered client of its own (#440): every calendar that is not kept is a call counted against this provider
		async with metered_client(self.id, timeout=AsyncHttpWorkerPool.REQUEST_TIMEOUT) as client:
			results = await asyncio.gather(*(self._read_one(client, entry, first, last, read, settings, store, dscm) for entry in calendars), return_exceptions=True)
		failed: list[BaseException] = []
		for entry, result in zip(calendars, results, strict=True):
			if isinstance(result, BaseException):
				failed.append(result)
				# the type only: the text of an HTTP error holds the address
				self.logger.warning(f"'{self.name}' the calendar '{entry['name']}' could not be read ({type(result).__name__}).")
				read.notes.append(str(result) if isinstance(result, PermanentError) else f"{entry['name']} could not be loaded: {failure_reason(result)}")
			else:
				answer.events.extend(result)
		if calendars and len(failed) == len(calendars):
			if all(isinstance(f, PermanentError) for f in failed):
				raise PermanentError("; ".join(read.notes))
			raise RuntimeError("No calendar could be loaded: " + "; ".join(read.notes))
		answer.events.sort(key=lambda e: (e.start, not e.all_day, e.title))
		answer.notes = read.notes
		return answer

