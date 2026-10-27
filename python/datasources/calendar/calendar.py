"""
The Calendar pages: a month grid, the next weeks and an agenda of the next days, from the device's calendar provider (`dsec.provide(CalendarApi)`,
the Calendar Sources), whose calendars and kept answers every page and overlay share; this source only draws.

A list source: `open_async` asks for the events once for the slot and returns one page per chosen view (month, weeks, agenda), and `render_async`
draws one of them. The provider's notes (a calendar that cannot be read, or has run out) are the page's footer.
"""
import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import RenderSession
from ..contracts.calendar import CalendarApi, Event, device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

VIEWS = ("month", "weeks", "agenda")
FONT_SCALES = { "x-small": 0.7, "small": 0.85, "normal": 1.0, "large": 1.2, "x-large": 1.45 }
DEFAULT_AGENDA_DAYS = 7
DEFAULT_WEEKS_AHEAD = 4
MAX_WEEKS_AHEAD = 8
@dataclass
class Slot:
	"""What one slot read: shared by its pages, so the calendars are read once however many views there are."""
	today: date
	zone: tzinfo
	events: list[Event] = field(default_factory=list)
	notes: list[str] = field(default_factory=list)
	# the pages' choices, from this data source's settings (not the task's)
	week_start: str = "monday"
	week_numbers: bool = False
	# the slot's time: an event that ended before it is drawn faded
	now: datetime|None = None

@dataclass(frozen=True)
class Page:
	view: str
	slot: Slot

def chosen_views(params: Mapping[str, Any]) -> list[str]:
	"""The views in page order (month, then agenda); none chosen reads as month."""
	views = params.get("views")
	picked = [v for v in VIEWS if isinstance(views, list) and v in views]
	return picked or ["month"]

def days_ahead(params: Mapping[str, Any]) -> int:
	"""How many days the agenda shows, today included."""
	value = params.get("agendaDays")
	return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DEFAULT_AGENDA_DAYS

def weeks_ahead(params: Mapping[str, Any]) -> int:
	"""How many weeks the weekly view shows after the current one."""
	value = params.get("weeksAhead")
	return min(value, MAX_WEEKS_AHEAD) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else DEFAULT_WEEKS_AHEAD

def week_of(day: date, week_start: str) -> date:
	"""The first day of the week `day` is in."""
	return day - timedelta(days=(day.weekday() + (1 if week_start == "sunday" else 0)) % 7)

def rolling_weeks(today: date, week_start: str, ahead: int) -> list[list[date]]:
	"""The current week and `ahead` more, whatever months they cross."""
	first = week_of(today, week_start)
	return [[first + timedelta(days=7 * w + n) for n in range(7)] for w in range(ahead + 1)]

def month_weeks(today: date, week_start: str) -> list[list[date]]:
	"""The weeks of today's month, each seven days from the first weekday (`monday` or `sunday`), with the days of the months around it."""
	first = today.replace(day=1)
	offset = (first.weekday() + (1 if week_start == "sunday" else 0)) % 7
	day = first - timedelta(days=offset)
	weeks: list[list[date]] = []
	while not weeks or day.month == today.month:
		weeks.append([day + timedelta(days=n) for n in range(7)])
		day += timedelta(days=7)
	return weeks

def query_range(today: date, views: list[str], week_start: str, agenda_days: int, zone: tzinfo, ahead: int = DEFAULT_WEEKS_AHEAD) -> tuple[datetime, datetime]:
	"""The time the chosen views show: the month grid (with its spill-over days), the weekly rows, and/or today plus the agenda's days."""
	start, end = today, today + timedelta(days=1)
	for view, weeks in (("month", lambda: month_weeks(today, week_start)), ("weeks", lambda: rolling_weeks(today, week_start, ahead))):
		if view in views:
			rows = weeks()
			start, end = min(start, rows[0][0]), max(end, rows[-1][-1] + timedelta(days=1))
	if "agenda" in views:
		end = max(end, today + timedelta(days=agenda_days))
	return datetime.combine(start, datetime.min.time(), zone), datetime.combine(end, datetime.min.time(), zone)

class CalendarPagesAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""A month grid, weeks and an agenda as a slide show: one page per chosen view, of the events the device's calendar provider answers."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def new_slot(self, dsec: DataSourceExecutionContext) -> Slot:
		"""An empty slot at the context's time, in the device zone, with the pages' choices from this data source's settings."""
		now = device_now(dsec.timestamp)
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		settings = settings or {}
		return Slot(now.date(), now.tzinfo or now.astimezone().tzinfo,  # type: ignore[arg-type]
			week_start="sunday" if settings.get("weekStart") == "sunday" else "monday", week_numbers=settings.get("weekNumbers") is True, now=now)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		views = chosen_views(params)
		slot = self.new_slot(dsec)
		start, end = query_range(slot.today, views, slot.week_start, days_ahead(params), slot.zone, weeks_ahead(params))
		provider, provider_dsec = dsec.provide(CalendarApi)
		answer = await provider.open_async(provider_dsec, { "start": start, "end": end, "calendars": params.get("calendars"), "holidaySets": params.get("holidaySets") })
		slot.events, slot.notes = list(answer.events), list(answer.notes)
		return [Page(view, slot) for view in views]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, Page):
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("calendar")
		_, display_config = scm.open("display").get()
		if display_config is None:
			raise ValueError("Display settings is None")
		_, system = scm.open("system").get()
		dimensions = target_dimensions(dsec, display_config)
		layout = Layout(dimensions, FONT_SCALES.get(str(params.get("fontSize")), 1.0) * current_inputs(scm).font_scale, (system or {}).get("timeFormat") == "12h", len(state.slot.notes))
		template_params = page_params(state, params, layout)
		return await asyncio.to_thread(generate_image, stm, render_dir, dimensions, template_params, current_inputs(scm))

# the least text a panel draws solid (plugin.css: --min-text, --min-label): the page floors its sizes with them, so the count does too
MIN_TEXT_PX = 15
MIN_LABEL_PX = 13

@dataclass(frozen=True)
class Layout:
	"""The page's size and text size, which decide how many events fit in a day of the grid and in the agenda."""
	dimensions: tuple[int, int]
	scale: float
	twelve_hour: bool
	# the footer's notes take their lines from the grid or the agenda
	notes: int = 0

	@property
	def font_px(self) -> int:
		return max(8, round(min(self.dimensions) * 0.04 * self.scale))

	@property
	def portrait(self) -> bool:
		return self.dimensions[1] > self.dimensions[0]

	def clock(self, when: datetime, short: bool = False) -> str:
		if not self.twelve_hour:
			# in a day of the grid every character counts: 9:00, not 09:00
			return f"{when.hour}:{when.minute:02d}" if short else f"{when:%H:%M}"
		hour = when.hour % 12 or 12
		minutes = "" if short and when.minute == 0 else f":{when.minute:02d}"
		suffix = ("a" if when.hour < 12 else "p") if short else (" AM" if when.hour < 12 else " PM")
		return f"{hour}{minutes}{suffix}"

	def _usable(self) -> float:
		"""The height under the heading and the weekday row (or the agenda's top margin), above the notes."""
		font = self.font_px
		footer = font * 0.3 + self.notes * max(MIN_LABEL_PX, font * 0.6) * 1.3 if self.notes else 0
		return self.dimensions[1] * 0.92 - font * 1.6 - font * 1.2 - footer

	def month_slots(self, weeks: int) -> int:
		"""Lines of events a day of the grid has room for (the CSS in calendar.html uses the same sizes)."""
		font = self.font_px
		cell = self._usable() / weeks
		# a tall page's days are narrow: an event is its title alone, on up to two lines
		line = max(MIN_TEXT_PX, font * 0.72) * 1.25 * (2 if self.portrait else 1)
		return max(0, math.floor((cell - font * 0.95 - 4) / line))

	def agenda_lines(self) -> int:
		# a line is kept for "and N more"
		return max(1, math.floor(self._usable() / (self.font_px * 1.45)) - 1)

def _item(event: Event, day: date, layout: Layout, short: bool, now: datetime|None) -> dict:
	"""How an event shows on a day: a bar for all-day and multi-day events, a dot and a time for the others."""
	spans = event.all_day or len(event.days()) > 1
	time = ""
	if not event.all_day and not (short and layout.portrait):
		if event.start.date() == day:
			time = layout.clock(event.start, short)
		elif not short:
			time = "continues"
	return { "title": event.title, "time": time, "color": event.color, "bar": spans, "holiday": event.holiday, "location": event.location, "calendar": event.calendar,
		"past": now is not None and event.end <= now }

def _when_short(day: date) -> str:
	return f"{day.day} {day:%b}"

def weeks_params(slot: Slot, params: Mapping[str, Any], layout: Layout) -> dict:
	"""
	The weekly view: the current week and the ones after it as continuous rows. Months are told apart by alternating a light tint
	(the month of today is plain, the next tinted, and so on) and by the month's name on its first day (and on the first day shown).
	"""
	weeks = rolling_weeks(slot.today, slot.week_start, weeks_ahead(params))
	grid = grid_params(slot, weeks, layout)
	first, last = weeks[0][0], weeks[-1][-1]
	for row in grid["weeks"]:
		for cell in row["days"]:
			day: date = cell["date"]
			cell["in_month"] = True
			cell["alt"] = ((day.year - slot.today.year) * 12 + day.month - slot.today.month) % 2 == 1
			cell["label"] = f"{day:%b}" if day.day == 1 or day == first else ""
	span = f"{_when_short(first)} – {_when_short(last)} {last.year}" if first.year == last.year else f"{_when_short(first)} {first.year} – {_when_short(last)} {last.year}"
	return { **grid, "heading": params.get("title") or span }

def month_params(slot: Slot, params: Mapping[str, Any], layout: Layout) -> dict:
	weeks = month_weeks(slot.today, slot.week_start)
	return { **grid_params(slot, weeks, layout), "heading": params.get("title") or f"{slot.today:%B} {slot.today.year}" }

def grid_params(slot: Slot, weeks: list[list[date]], layout: Layout) -> dict:
	"""Rows of seven days with the events that fit in each (the month and the weekly views)."""
	slots = layout.month_slots(len(weeks))
	by_day: dict[date, list[Event]] = {}
	for event in slot.events:
		for day in event.days():
			by_day.setdefault(day, []).append(event)
	rows = []
	for week in weeks:
		cells = []
		for day in week:
			# holidays first, then all-day and multi-day, then by time
			events = sorted(by_day.get(day, []), key=lambda e: (not e.holiday, not (e.all_day or len(e.days()) > 1), e.start, e.title))
			shown = events if len(events) <= slots else events[:max(0, slots - 1)]
			cells.append({
				"date": day,
				"day": day.day,
				"alt": False,
				"label": "",
				"in_month": day.month == slot.today.month,
				"today": day == slot.today,
				"weekend": day.weekday() >= 5,
				"entries": [_item(e, day, layout, True, slot.now) for e in shown],
				"more": len(events) - len(shown),
			})
		# ISO 8601 week numbers (weeks start on Monday): a Sunday-first row is numbered by its Monday
		rows.append({ "number": week[0 if slot.week_start == "monday" else 1].isocalendar().week, "days": cells })
	names = [(weeks[0][n]).strftime("%a") for n in range(7)]
	return {
		"weekdays": [n[0] for n in names] if layout.portrait else names,
		"weeks": rows,
		"week_numbers": slot.week_numbers,
	}

def agenda_params(slot: Slot, params: Mapping[str, Any], layout: Layout) -> dict:
	agenda_days = days_ahead(params)
	budget = layout.agenda_lines()
	days: list[dict] = []
	left = 0
	for n in range(agenda_days):
		day = slot.today + timedelta(days=n)
		events = [e for e in slot.events if day in e.days()]
		if not events:
			continue
		events.sort(key=lambda e: (not e.holiday, not e.all_day, e.start if e.start.date() == day else datetime.combine(day, datetime.min.time(), slot.zone), e.title))
		if budget < 2:
			left += len(events)
			continue
		label = "Today" if n == 0 else "Tomorrow" if n == 1 else f"{day:%A}, {day.day} {day:%B}"
		budget -= 1
		fits = events[:budget]
		budget -= len(fits)
		left += len(events) - len(fits)
		days.append({ "label": label, "today": n == 0, "entries": [{ **_item(e, day, layout, False, slot.now), "range": _range(e, day, layout) } for e in fits] })
	return {
		"heading": params.get("title") or "Agenda",
		"days": days,
		"more": left,
	}

def _range(event: Event, day: date, layout: Layout) -> str:
	if event.all_day:
		return "All day"
	start = layout.clock(event.start) if event.start.date() == day else "…"
	end = layout.clock(event.end) if event.end.date() == day or (event.end.date() == day + timedelta(days=1) and event.end.time() == datetime.min.time()) else "…"
	return start if event.end == event.start else f"{start} – {end}"

def page_params(page: Page, params: Mapping[str, Any], layout: Layout) -> dict:
	views = { "month": month_params, "weeks": weeks_params, "agenda": agenda_params }
	body = views.get(page.view, month_params)(page.slot, params, layout)
	return { "view": page.view, "font_px": layout.font_px, "portrait": layout.portrait, "notes": page.slot.notes, "settings": params, **body }

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	rs = RenderSession(stm, render_dir, "calendar.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=template_params["heading"])
