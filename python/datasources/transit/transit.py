"""
The Departure Board (#429): one stop's next departures as a page. The data comes from the device's transit provider (`dsec.provide(TransitApi)`), whose settings and
kept answers every page and overlay of the stop share; this source only draws.

**It is not a real-time display**, so it draws by e-ink's rules: clock times, never "in 4 min" (wrong a minute after the refresh); "as of" the moment the answer was
asked, rounded down to 5 minutes, so a board whose answer has not changed draws the same picture and the panel is not refreshed for it; what the reader can no
longer catch, counting the walk to the stop, is left out when it is drawn. Live, late and cancelled are marked with a symbol or a word as well as a colour (a colour
dithers, and some readers do not see it), and a route's colour is drawn in the nearest ink the panel has.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...model.clock_sync import ClockSync
from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.inks import DRIVE, nearest_ink
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import RenderSession
from ..contracts.transit import CANCELLED, Departure, TransitApi, TransitReport, device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

FONT_SCALES = { "x-small": 0.7, "small": 0.85, "normal": 1.0, "large": 1.2, "x-large": 1.45 }
DEFAULT_ROWS = 6
# the "as of" moment is rounded down to this: an answer that has not changed draws the same page (#429 B9)
AS_OF_STEP = timedelta(minutes=5)
# a pinch of the delay is noise: a departure under a minute late or early reads as on time
ON_TIME_SECONDS = 60
WAITING_FOR_CLOCK = "Waiting for the clock to be set."

def clock(when: datetime, twelve_hour: bool) -> str:
	return f"{when.hour % 12 or 12}:{when.minute:02d}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"

def as_of(moment: datetime) -> datetime:
	"""The moment rounded down to AS_OF_STEP (in its own zone)."""
	minutes = moment.hour * 60 + moment.minute
	return moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minutes - minutes % int(AS_OF_STEP.total_seconds() // 60))

def delay_text(d: Departure) -> str:
	"""A live departure's delay in whole minutes: "+3" late, "-2" early, "" on time or not known."""
	if not d.live or d.delay is None or abs(d.delay) < ON_TIME_SECONDS:
		return ""
	minutes = round(d.delay / 60)
	return f"+{minutes}" if minutes > 0 else f"−{-minutes}"

def chip(color: str|None, ink_set: str, page_ink: str) -> dict[str, str]|None:
	"""
	A route's colour as a chip on the panel's inks: its nearest ink, and the ink of its text, black or white, whichever reads on it. None (the page draws its strong
	chip) when there is no colour, or when its nearest ink is the page's own: another ink would be another colour, not the route's.
	"""
	if not color or len(color) != 7:
		return None
	rgb = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
	ink = nearest_ink(rgb, ink_set)
	if ink == page_ink:
		return None
	r, g, b = DRIVE[ink]
	text = "black" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "white"
	return { "background": "#%02x%02x%02x" % DRIVE[ink], "color": "#%02x%02x%02x" % DRIVE[text] }

def page_params(report: TransitReport, now: datetime, params: Mapping[str, Any], twelve_hour: bool, theme: ThemeInputs|None, clock_state: str = "unknown") -> dict[str, Any]:
	"""What the template draws: the rows ready to place (the template decides nothing about clocks, inks or what is gone)."""
	heading = params.get("title") or report.stop.name or "Departures"
	common = { "heading": heading, "credit": report.credit, "font_scale": FONT_SCALES.get(str(params.get("fontSize")), 1.0) }
	if clock_state == "unsynced":
		# the device's clock may be any date at boot (#785): a board drawn from it is nonsense
		return { **common, "rows": [], "alerts": [], "message": WAITING_FOR_CLOCK, "as_of": "" }
	local_now = now.astimezone(report.departures[0].when.tzinfo) if report.departures else now
	count = params.get("rows")
	count = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else DEFAULT_ROWS
	ink_set = theme.ink_set if theme is not None else "spectra6"
	page_ink = theme.palette.bg_page if theme is not None else "white"
	shown = report.catchable(local_now)[:count]
	rows = [{ "time": clock(d.when, twelve_hour), "live": d.live, "delay": delay_text(d), "route": d.route.label, "chip": chip(d.route.color, ink_set, page_ink),
		"headsign": d.headsign, "platform": d.platform or "", "cancelled": d.status == CANCELLED or not d.running } for d in shown]
	active = sorted(report.active_alerts(local_now), key=lambda a: ({ "severe": 0, "warning": 1 }.get(a.severity, 2), a.header))
	if rows:
		message = ""
	elif report.notes:
		message = report.notes[0]
	else:
		message = "No more departures you can still catch soon." if report.departures else "No departures from this stop soon."
	return { **common, "rows": rows, "platforms": any(r["platform"] for r in rows), "alerts": [a.header for a in active[:1]], "more_alerts": max(0, len(active) - 1),
		"message": message, "note": report.notes[0] if rows and report.notes else "", "as_of": clock(as_of(report.fetched_at), twelve_hour), "any_live": any(r["live"] for r in rows),
		"any_timetable": any(not r["live"] for r in rows) }

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult|None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	image = RenderSession(stm, render_dir, "transit.html", theme).render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=template_params["heading"])

class TransitAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""A stop's next departures as one page."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		api, api_dsec = dsec.provide(TransitApi)
		return [await api.open_async(api_dsec, { "stop": params.get("stop") })]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		if not isinstance(state, TransitReport):
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("transit")
		_, display_config = scm.open("display").get()
		_, system = scm.open("system").get()
		theme = current_inputs(scm)
		template_params = page_params(state, device_now(dsec.timestamp), params, (system or {}).get("timeFormat") == "12h", theme, ClockSync().state())
		return await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), template_params, theme)
