"""
Reading events for the Calendar data source: iCal files (a link, `webcal` read as `https`), CalDAV servers (one REPORT with a time range)
and holidays (the `holidays` package). Everything comes out as `Event`s in the device zone, recurrences expanded.

Messages raised from here are ours: they never hold an address, a secret or exception text.
"""
import base64
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

import holidays
import httpx
import icalendar
import recurring_ical_events

from ...plugins.plugin_base import PermanentError
from ...utils.url_guard import stream_checked

# a calendar file is text: a big family calendar with years of history is a few megabytes
MAX_CALENDAR_BYTES = 5 * 1024 * 1024
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "text/calendar, */*;q=0.5" }
TITLE_CHARS = 120
# a finite calendar is walked to its end to find its last day; one with more occurrences than this is read as never ending
MAX_OCCURRENCES = 20000
_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_SPACE = re.compile(r"\s+")

@dataclass(frozen=True)
class Event:
	"""One occurrence, in the device zone. `end` is exclusive; an all-day event starts and ends at midnight."""
	start: datetime
	end: datetime
	all_day: bool
	title: str
	location: str
	calendar: str
	color: str|None
	holiday: bool = False

	def days(self) -> list[date]:
		"""The days the event shows on (an event ending at midnight does not show on the day it ends)."""
		first = self.start.date()
		last = (self.end - timedelta(microseconds=1)).date() if self.end > self.start else first
		return [first + timedelta(days=n) for n in range((last - first).days + 1)]

class NotACalendar(RuntimeError):
	"""The answer is no calendar (an HTML page, a sign-in screen)."""

def safe_color(value: Any) -> str|None:
	"""A `#rgb` / `#rrggbb` color, or None: the value goes into the page's CSS, so nothing else passes."""
	return value if isinstance(value, str) and _COLOR.match(value) else None

def _text(value: Any) -> str:
	text = _SPACE.sub(" ", str(value or "")).strip()
	return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"

def web_url(url: str) -> str:
	"""`webcal://` is `https://` (that is what a calendar app does with it)."""
	return "https://" + url[len("webcal://"):] if url.lower().startswith("webcal://") else url

def auth_headers(entry: Mapping[str, Any]) -> dict[str, str]:
	"""The sign-in a calendar row asks for. A row that asks for one without its secret cannot work until the settings are fixed."""
	auth = entry.get("auth") or "none"
	name = entry.get("name")
	if auth == "basic":
		username, password = entry.get("username"), entry.get("password")
		if not username or not password:
			raise PermanentError(f"The calendar '{name}' needs a username and password.")
		return { "Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii") }
	if auth == "bearer":
		token = entry.get("token")
		if not token:
			raise PermanentError(f"The calendar '{name}' needs a token.")
		return { "Authorization": f"Bearer {token}" }
	return {}

def parse_calendar(data: bytes) -> icalendar.Calendar:
	try:
		cal = icalendar.Calendar.from_ical(data)
	except ValueError:
		raise NotACalendar("The answer is not a calendar.") from None
	if not isinstance(cal, icalendar.Calendar) or cal.name != "VCALENDAR":
		raise NotACalendar("The answer is not a calendar.")
	return cal

def _moment(value: date|datetime, zone: tzinfo) -> datetime:
	"""A start or end in the device zone: a day is its midnight there, a time without a zone (floating) is read as the device's own."""
	if not isinstance(value, datetime):
		return datetime.combine(value, time(), zone)
	return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)

def _event(component: Any, zone: tzinfo, calendar: str, color: str|None) -> Event|None:
	"""One occurrence as an Event, or None for what is not shown (not an event, cancelled, no start)."""
	if component.name != "VEVENT" or str(component.get("STATUS", "")).upper() == "CANCELLED" or component.get("DTSTART") is None:
		return None
	raw_start = component["DTSTART"].dt
	raw_end = component["DTEND"].dt if component.get("DTEND") is not None else raw_start
	all_day = not isinstance(raw_start, datetime)
	first = _moment(raw_start, zone)
	last = _moment(raw_end, zone)
	if all_day and last <= first:
		last = first + timedelta(days=1)
	return Event(first, max(first, last), all_day, _text(component.get("SUMMARY")) or "(untitled)", _text(component.get("LOCATION")), calendar, color)

def events_between(cal: icalendar.Calendar, start: datetime, end: datetime, zone: tzinfo, calendar: str, color: str|None) -> list[Event]:
	"""The occurrences that overlap [start, end), recurrences expanded and cancelled ones left out, sorted by start."""
	found = [e for e in (_event(c, zone, calendar, color) for c in recurring_ical_events.of(cal).between(start, end)) if e is not None]
	return sorted(found, key=lambda e: (e.start, not e.all_day, e.title))

def last_day(cal: icalendar.Calendar, zone: tzinfo) -> date|None:
	"""
	The last day a calendar has anything on, or None when something repeats with no end (or there is nothing at all).
	A calendar whose events are all one-off (a season's fixtures) or whose repeats end (`UNTIL`, `COUNT`) runs out: past that day it is empty,
	which usually means its address must be changed for a new file (next season's, next year's).
	"""
	events = list(cal.walk("VEVENT"))
	if not events:
		return None
	for event in events:
		rule = event.get("RRULE")
		rules = rule if isinstance(rule, list) else [rule] if rule is not None else []
		if any(not r.get("UNTIL") and not r.get("COUNT") for r in rules):
			return None
	latest: date|None = None
	for count, occurrence in enumerate(recurring_ical_events.of(cal).all()):
		if count >= MAX_OCCURRENCES:
			return None
		shown = _event(occurrence, zone, "", None)
		if shown is not None:
			day = shown.days()[-1]
			latest = day if latest is None or day > latest else latest
	return latest

def caldav_query(start: datetime, end: datetime) -> bytes:
	"""The REPORT body of RFC 4791: the events that overlap the range, with their iCalendar data."""
	fmt = "%Y%m%dT%H%M%SZ"
	return (
		'<?xml version="1.0" encoding="utf-8"?>'
		'<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
		'<D:prop><C:calendar-data/></D:prop>'
		'<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">'
		f'<C:time-range start="{start.astimezone(timezone.utc).strftime(fmt)}" end="{end.astimezone(timezone.utc).strftime(fmt)}"/>'
		'</C:comp-filter></C:comp-filter></C:filter>'
		'</C:calendar-query>'
	).encode("utf-8")

def caldav_calendars(body: bytes) -> list[icalendar.Calendar]:
	"""The calendars in a CalDAV multistatus answer (one per event resource)."""
	try:
		root = ElementTree.fromstring(body)
	except ElementTree.ParseError:
		raise NotACalendar("The answer is not a CalDAV answer.") from None
	if root.tag != "{DAV:}multistatus":
		raise NotACalendar("The answer is not a CalDAV answer.")
	return [parse_calendar(node.text.encode("utf-8")) for node in root.iter("{urn:ietf:params:xml:ns:caldav}calendar-data") if node.text and node.text.strip()]

async def download(client: httpx.AsyncClient, method: str, url: str, headers: Mapping[str, str], content: bytes|None = None, max_bytes: int = MAX_CALENDAR_BYTES) -> bytes:
	"""The body of a GET or REPORT, refused (RuntimeError) past `max_bytes`; an error status raises httpx.HTTPStatusError."""
	async with stream_checked(client, method, url, headers, content) as resp:
		resp.raise_for_status()
		body = bytearray()
		async for chunk in resp.aiter_bytes():
			body.extend(chunk)
			if len(body) > max_bytes:
				raise RuntimeError(f"The calendar is too large (more than {max_bytes // (1024 * 1024)} MB).")
		return bytes(body)

async def read_ical(client: httpx.AsyncClient, entry: Mapping[str, Any]) -> icalendar.Calendar:
	headers = { **HEADERS, **auth_headers(entry) }
	return parse_calendar(await download(client, "GET", web_url(str(entry.get("url"))), headers))

async def read_caldav(client: httpx.AsyncClient, entry: Mapping[str, Any], start: datetime, end: datetime) -> list[icalendar.Calendar]:
	headers = { **HEADERS, **auth_headers(entry), "Depth": "1", "Content-Type": "application/xml; charset=utf-8" }
	return caldav_calendars(await download(client, "REPORT", web_url(str(entry.get("url"))), headers, caldav_query(start, end)))

def country_names() -> list[dict]:
	"""The countries the `holidays` package knows, as lookup choices (`{ name, value }`, the value the two-letter code), by name."""
	from holidays.registry import COUNTRIES
	supported = holidays.list_supported_countries()
	names = { entry[1]: key.replace("_", " ").title() for key, entry in COUNTRIES.items() }
	return sorted(({ "name": names.get(code, code), "value": code } for code in supported if len(code) == 2), key=lambda c: c["name"])

def holiday_events(entry: Mapping[str, Any], years: Iterable[int], zone: tzinfo) -> list[Event]:
	"""The holidays of a holiday row, as all-day events. An unknown country or subdivision cannot work until the settings are fixed."""
	name = str(entry.get("name"))
	country = entry.get("country")
	subdivision = entry.get("subdivision") or None
	try:
		days = holidays.country_holidays(str(country), subdiv=subdivision, years=sorted(set(years)))
	except NotImplementedError:
		what = f"subdivision '{subdivision}' of " if subdivision else ""
		raise PermanentError(f"The holidays '{name}': the {what}country '{country}' is not known.") from None
	color = safe_color(entry.get("color"))
	found = []
	for day, title in sorted(days.items()):
		first = datetime.combine(day, time(), zone)
		found.append(Event(first, first + timedelta(days=1), True, _text(title), "", name, color, holiday=True))
	return found
