"""
The sun or the moon for an overlay zone (#619): today's sunrise and sunset, the day's length, or the moon's phase, as outlined text
(python/datasources/overlay_text.py) with a drawing before it. Calculated on the device (python/datasources/sky): no network, no key, no cache.
"""
import asyncio
import logging
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ...plugins.plugin_base import PermanentError
from ..contracts.provider import device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult
from ..overlay_text import OverlayIcon, Run, outline_factor, overlay_margin, render_overlay, zone_valign
from ..sky.draw import moon_strokes
from ..sky.sky import Sky, device_place, sky_of
from ..sun_moon.sun_moon import change, clock, duration
from ..weather.icons import ICON_WEIGHT, icon_body

VIEWS = ("sun", "daylight", "moon")

def chosen_view(params: Mapping[str, Any]) -> str:
	view = params.get("view")
	if view is None:
		return "sun"
	if view not in VIEWS:
		raise PermanentError(f"Unknown view '{view}' (one of {', '.join(VIEWS)})")
	return str(view)

def view_lines(view: str, sky: Sky, twelve_hour: bool) -> tuple[list[list[Run]], str|None, str]:
	"""The lines of a view (runs of text and role), the drawing before them (strokes in the 64 grid, or None), and the title for the telemetry."""
	sun, moon = sky.sun, sky.moon
	if view == "moon":
		runs: list[Run] = [(moon.name, "text-secondary-1"), (f" {round(moon.lit * 100)}%", "text-primary")]
		return [runs], moon_strokes(moon.phase, sky.place.southern), f"{moon.name} {round(moon.lit * 100)}%"
	if view == "daylight":
		length = "24h 00m" if sun.polar == "day" else duration(sun.length) or "–"
		runs = [(length, "text-secondary-1")]
		more = change(sun.length, sky.yesterday, short=True)
		if more:
			runs.append((f" {more}", "text-primary"))
		return [runs], icon_body("01d"), "".join(text for text, _ in runs)
	if sun.polar == "day":
		runs = [("Sun up all day", "text-secondary-1")]
	elif sun.polar == "night":
		runs = [("Sun down all day", "text-secondary-1")]
	else:
		base = sun.noon
		runs = [(clock(sun.sunrise, twelve_hour, base) or "–", "text-secondary-1"), (" – ", "text-primary"), (clock(sun.sunset, twelve_hour, base) or "–", "text-secondary-1")]
	return [runs], icon_body("01d"), "".join(text for text, _ in runs)

class SunMoonOverlayAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The sun or the moon as an overlay, calculated for the device's location in its zone."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		view = chosen_view(params)
		_, system = dsec.provider.required(SettingsConfigurationManager).open("system").get()
		place = device_place(system)
		sky = await asyncio.to_thread(sky_of, place, device_now(dsec.timestamp))
		return (view, sky, (system or {}).get("timeFormat") == "12h")

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not (isinstance(state, tuple) and len(state) == 3 and isinstance(state[1], Sky)):
			return None
		view, sky, twelve_hour = state
		lines, body, title = view_lines(view, sky, bool(twelve_hour))
		icon = OverlayIcon(body, ICON_WEIGHT) if body is not None and params.get("showIcon", True) is not False else None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		# an overlay renders at the zone's size as given (never through target_dimensions); Chromium is blocking: keep it off the event loop
		image = await asyncio.to_thread(render_overlay, stm, current_inputs(scm), dsec.dimensions, lines, outline_factor(params), str(params.get("weight") or "bold"),
			zone_valign(params), overlay_margin(params), icon)
		return MediaRenderResult(image=image, title=title)
