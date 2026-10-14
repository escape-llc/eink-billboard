"""
The weather for an overlay zone (#157): the weather now, today's range, or the next days, as outlined text (python/datasources/overlay_text.py).

It has no settings and no cache of its own: it asks the Weather data source for its report (`report_async`, through `dsec.context_for(weather)`), so the
API key, the units and the kept answers are the Weather's, and a Weather page and this overlay of the same hours make one call.
"""
import asyncio
import logging
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ...plugins.plugin_base import PermanentError
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult
from ..overlay_text import OverlayIcon, Run, outline_factor, overlay_margin, render_overlay, zone_valign
from ..weather.icons import ICON_WEIGHT, icon_body
from ..weather.weather import Report, WeatherAsync

# the data source it asks: the Weather's id (its descriptor's), never a value from a request
WEATHER_ID = "weather"
VIEWS = ("now", "today", "outlook")
OUTLOOK_DAYS = 3

def _degrees(value: float|None) -> str:
	return "" if value is None else f"{round(value)}°"

def _percent(chance: float|None) -> str:
	return "" if chance is None else f"{round(max(0.0, min(chance, 1.0)) * 100)}%"

def chosen_view(params: Mapping[str, Any]) -> str:
	view = params.get("view")
	if view is None:
		return "now"
	if view not in VIEWS:
		raise PermanentError(f"Unknown view '{view}' (one of {', '.join(VIEWS)})")
	return str(view)

def needs_of(view: str) -> set[str]:
	"""Only the answer the view shows: the free plan counts calls (the Weather keeps each answer for its own time)."""
	return { "current" } if view == "now" else { "forecast" }

def view_lines(view: str, report: Report) -> tuple[list[list[Run]], str|None, str]:
	"""The lines of a view (runs of text and role), the icon code before them (or None), and the title for the telemetry. A report without what the view needs is an error."""
	if view == "now":
		now = report.current
		if now is None:
			raise RuntimeError("The weather now is not in the report")
		text = now.text[:1].upper() + now.text[1:]
		return [[(_degrees(now.temp), "text-secondary-1"), (f" {text}", "text-primary")]], now.icon, f"{_degrees(now.temp)} {text}"
	if not report.days:
		raise RuntimeError("The forecast has no days")
	if view == "today":
		day = report.days[0]
		runs: list[Run] = [(_degrees(day.high), "text-secondary-1"), (f" / {_degrees(day.low)}", "text-primary")]
		if day.rain is not None:
			runs.append((f"  {_percent(day.rain)}", "text-secondary-2"))
		return [runs], day.icon, "".join(text for text, _ in runs)
	lines: list[list[Run]] = []
	for day in report.days[:OUTLOOK_DAYS]:
		label = "Today" if day.day == report.now.date() else day.day.strftime("%a")
		lines.append([(label, "text-secondary-1"), (f" {_degrees(day.high)} / {_degrees(day.low)}", "text-primary")])
	return lines, None, " · ".join("".join(text for text, _ in line) for line in lines)

class WeatherOverlayAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The weather as an overlay: it asks the Weather data source, whose settings and kept answers it shares."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		view = chosen_view(params)
		weather, weather_dsec = dsec.use(WEATHER_ID, WeatherAsync)
		return (view, await weather.report_async(weather_dsec, needs_of(view)))

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not (isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], Report)):
			return None
		view, report = state
		lines, code, title = view_lines(view, report)
		icon = OverlayIcon(icon_body(code), ICON_WEIGHT) if code is not None and params.get("showIcon", True) is not False else None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		# an overlay renders at the zone's size as given (never through target_dimensions); Chromium is blocking: keep it off the event loop
		image = await asyncio.to_thread(render_overlay, stm, current_inputs(scm), dsec.dimensions, lines, outline_factor(params), str(params.get("weight") or "bold"),
			zone_valign(params), overlay_margin(params), icon)
		return MediaRenderResult(image=image, title=title)
