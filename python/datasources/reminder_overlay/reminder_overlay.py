"""
The next events of the calendars for an overlay zone (#158): what is coming up, as outlined text (python/datasources/overlay_text.py).

It has no calendar list, no settings and no cache of its own: it asks the Calendar data source for its events (`events_async`, through `dsec.context_for(calendar)`),
so the calendars, the accounts and the kept answers are the Calendar's, and a Calendar page and this overlay of the same days make one read. Each run asks nobody
else and starts nothing: the overlay task's own trigger decides when it runs, and the events in the window are picked from what is kept. Nothing in the window is
nothing to show: the overlay is taken off, so an old reminder is never left up.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ...plugins.plugin_base import PermanentError
from ..calendar.calendar import CalendarAsync, device_now
from ..calendar.sources import Event
from ..data_source import DataSource, DataSourceExecutionContext, DataSourceManager, MediaItemAsync, MediaRenderAsync, MediaRenderResult
from ..overlay_text import Run, lines_that_fit, outline_factor, overlay_margin, render_overlay, zone_valign

# the data source it asks: the Calendar's id (its descriptor's), never a value from a request
CALENDAR_ID = "calendar"
DEFAULT_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 7 * 24 * 60
TITLE_CHARS = 30

def window_minutes(params: Mapping[str, Any]) -> int:
	value = params.get("windowMinutes")
	if value is None:
		return DEFAULT_WINDOW_MINUTES
	if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 1:
		raise PermanentError("The window must be at least one minute.")
	return int(min(value, MAX_WINDOW_MINUTES))

def upcoming(events: list[Event], now: datetime, minutes: int, all_day: bool) -> list[Event]:
	"""The events that are on now or start within the window, the nearest first; an all-day event only when asked for."""
	until = now + timedelta(minutes=minutes)
	chosen = [e for e in events if e.end > now and e.start < until and (all_day or not e.all_day)]
	return sorted(chosen, key=lambda e: (e.start, e.title))

def clock(when: datetime, twelve_hour: bool) -> str:
	if not twelve_hour:
		return f"{when:%H:%M}"
	return f"{when.hour % 12 or 12}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"

def when_text(event: Event, now: datetime, twelve_hour: bool) -> str:
	"""When it is: `Now` while it is on, the time of day when it is today, the weekday and the time on a later day (all-day: Today or the weekday)."""
	today = now.date()
	if event.all_day:
		return "Today" if event.start.date() <= today else f"{event.start:%a}"
	if event.start <= now:
		return "Now"
	return clock(event.start, twelve_hour) if event.start.date() == today else f"{event.start:%a} {clock(event.start, twelve_hour)}"

def title_text(event: Event) -> str:
	title = event.title
	return title if len(title) <= TITLE_CHARS else title[:TITLE_CHARS - 1].rstrip() + "…"

def event_lines(events: list[Event], now: datetime, twelve_hour: bool) -> list[list[Run]]:
	return [[(when_text(e, now, twelve_hour), "text-secondary-1"), (f"  {title_text(e)}", "text-primary")] for e in events]

class ReminderOverlayAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The next events as an overlay: it asks the Calendar data source, whose calendars and kept answers it shares."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def _calendar(self, dsec: DataSourceExecutionContext) -> CalendarAsync:
		calendar = dsec.provider.required(DataSourceManager).get_source(CALENDAR_ID)
		if not isinstance(calendar, CalendarAsync):
			raise PermanentError("The Calendar data source is not available. The reminders use its calendars.")
		return calendar

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		minutes = window_minutes(params)
		calendar = self._calendar(dsec)
		now = device_now(dsec.timestamp)
		# the Calendar reads whole days (kept for its `cacheHours`); the window is picked from them
		slot = await calendar.events_async(dsec.context_for(calendar), now, now + timedelta(minutes=minutes), params)
		return [e for e in upcoming(slot.events, now, minutes, params.get("allDay") is True)]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, list):
			return None
		if not state:
			# nothing in the window: the overlay comes off (the Overlay plugin revokes it)
			return None
		now = device_now(dsec.timestamp)
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		_, system = scm.open("system").get()
		twelve_hour = (system or {}).get("timeFormat") == "12h"
		theme = current_inputs(scm)
		lines = event_lines(state, now, twelve_hour)
		texts = ["".join(text for text, _ in runs) for runs in lines]
		outline, weight, valign, margin = outline_factor(params), str(params.get("weight") or "bold"), zone_valign(params), overlay_margin(params)
		# as many events as the zone shows at a size that can be read
		shown = await asyncio.to_thread(lines_that_fit, stm, theme, dsec.dimensions, texts, outline, weight, valign, margin)
		image = await asyncio.to_thread(render_overlay, stm, theme, dsec.dimensions, lines[:shown], outline, weight, valign, margin)
		return MediaRenderResult(image=image, title=" · ".join(texts[:shown]))
