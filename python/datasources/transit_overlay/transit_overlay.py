"""
Next Departure (#429 PR 4): the next departures from one of your stops for an overlay zone, as outlined text (python/datasources/overlay_text.py). A line per
route and destination: "23 Downtown 12:07 · 12:20", the next two of each, so a refresh just after one leaves still shows one.

The data comes from the device's transit provider (`dsec.provide(TransitApi)`), the same kept answer a Departure Board of the stop reads. **The times are what
can still be caught when it is drawn**, counting the walk to the stop, and they are always clock times: the departure's, or when to leave (the walk taken off).
**Never a countdown**: this is not a real-time display, and "in 4 min" is wrong a minute after the refresh, while 12:41 stays right. A timetable time is marked `~`
and a late live one `+3`, so the difference is not a colour only. Nothing to catch, or a clock that is not set, takes the overlay off.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...model.clock_sync import ClockSync
from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ..contracts.transit import Departure, TransitApi, TransitReport, device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult
from ..overlay_text import Run, lines_that_fit, outline_factor, overlay_margin, render_overlay, zone_valign

# clock times only: the departure's, or when to leave for it (never a countdown: #429)
TIME_STYLES = ("clock", "leave-by")
DEFAULT_PER_LINE = 2
HEADSIGN_CHARS = 22
# a live departure less than this late reads as on time
ON_TIME_SECONDS = 60

@dataclass(frozen=True)
class Line:
	"""A route and where it goes, and its next departures that can still be caught, soonest first."""
	route: str
	headsign: str
	departures: tuple[Departure, ...]

def lines_of(report: TransitReport, now: datetime, per_line: int) -> list[Line]:
	"""The catchable departures that run, grouped by route and destination, in the order of each group's first one; `per_line` of each."""
	groups: dict[tuple[str, str], list[Departure]] = {}
	for d in report.catchable(now):
		if d.running:
			groups.setdefault((d.route.label, d.headsign), []).append(d)
	return [Line(route, headsign, tuple(found[:per_line])) for (route, headsign), found in groups.items()]

def clock(when: datetime, twelve_hour: bool) -> str:
	return f"{when.hour % 12 or 12}:{when.minute:02d}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"

def mark(d: Departure, text: str) -> str:
	"""A time as it is drawn: `~` before a timetable time, `+3` after a live one that is late."""
	if not d.live:
		return f"~{text}"
	if d.delay is not None and d.delay >= ON_TIME_SECONDS:
		return f"{text}+{round(d.delay / 60)}"
	return text

def times_text(line: Line, now: datetime, style: str, walk: int, twelve_hour: bool) -> str:
	"""A line's times in the task's style, clock times both: "12:07 · 12:20", or "leave 12:02 · 12:15"."""
	if style == "leave-by":
		return "leave " + " · ".join(mark(d, clock(d.when - timedelta(minutes=walk), twelve_hour)) for d in line.departures)
	return " · ".join(mark(d, clock(d.when, twelve_hour)) for d in line.departures)

def _short(text: str, chars: int = HEADSIGN_CHARS) -> str:
	return text if len(text) <= chars else text[:chars - 1].rstrip() + "…"

def overlay_lines(report: TransitReport, now: datetime, params: Mapping[str, Any], twelve_hour: bool) -> list[list[Run]]:
	"""
	One line per route and destination: the route in the accent, where it goes, then its times. The first carries the provider's name: its terms ask for the credit
	next to the data, and an overlay has room for a word.
	"""
	per_line = params.get("perLine")
	per_line = per_line if isinstance(per_line, int) and not isinstance(per_line, bool) and per_line > 0 else DEFAULT_PER_LINE
	style = params.get("timeStyle") if params.get("timeStyle") in TIME_STYLES else "clock"
	runs: list[list[Run]] = [[(f"{line.route} ", "text-secondary-1"), (f"{_short(line.headsign)}  ", "text-primary"),
		(times_text(line, now, str(style), report.walk_minutes, twelve_hour), "text-primary")] for line in lines_of(report, now, per_line)]
	if runs and report.credit:
		runs[0].append((f" · {report.credit.rsplit(':', 1)[-1].strip()}", "text-secondary-2"))
	return runs

class TransitOverlayAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The next departures from a stop as an overlay: it asks the device's transit provider, whose kept answers a Departure Board of the stop shares."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		api, api_dsec = dsec.provide(TransitApi)
		return [await api.open_async(api_dsec, { "stop": params.get("stop") })]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		if not isinstance(state, TransitReport) or ClockSync().state() == "unsynced":
			# a clock that may be any date makes "what can be caught" mean nothing: the overlay comes off
			return None
		now = device_now(dsec.timestamp)
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		_, system = scm.open("system").get()
		lines = overlay_lines(state, now, params, (system or {}).get("timeFormat") == "12h")
		if not lines:
			# nothing left to catch: the overlay is taken off, so a departure that has gone is never left up
			return None
		theme = current_inputs(scm)
		texts = ["".join(text for text, _ in runs) for runs in lines]
		outline, weight, valign, margin = outline_factor(params), str(params.get("weight") or "bold"), zone_valign(params), overlay_margin(params)
		shown = await asyncio.to_thread(lines_that_fit, stm, theme, dsec.dimensions, texts, outline, weight, valign, margin)
		image = await asyncio.to_thread(render_overlay, stm, theme, dsec.dimensions, lines[:shown], outline, weight, valign, margin)
		return MediaRenderResult(image=image, title=" · ".join(texts[:shown]))
