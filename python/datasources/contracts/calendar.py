"""
The calendar contract (`data-calendar`): the events a calendar provider answers, which the Calendar pages and the Reminder Overlay show.
A provider implements `CalendarApi`; a consumer asks `dsec.provide(CalendarApi)` and imports nothing else of the provider's.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from ..data_source import DataSourceExecutionContext
from .provider import ProviderContract, device_now  # noqa: F401 (a consumer's time: one definition)

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

@dataclass
class CalendarAnswer:
	"""The events between two moments, sorted (by start, all-day first, by title), and the notes about calendars that could not be read or have run out (our words)."""
	events: list[Event] = field(default_factory=list)
	notes: list[str] = field(default_factory=list)

class CalendarApi(ProviderContract):
	"""
	`open_async(dsec, { "start": datetime, "end": datetime, "calendars": [names], "holidaySets": [names] })` answers a `CalendarAnswer`: the events of the
	provider's calendars and holiday sets between `start` and `end` (moments; `calendars` and `holidaySets` choose entries by name, none chosen: all that are
	enabled). A provider reads whole days, so a page and an overlay of the same days share what it keeps. A name that is not one of its entries is a
	PermanentError; so is every chosen calendar failing for a setting.
	"""
	capability = "data-calendar"
	noun = "calendar"
	setting = "calendarProvider"

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> CalendarAnswer:
		raise NotImplementedError
