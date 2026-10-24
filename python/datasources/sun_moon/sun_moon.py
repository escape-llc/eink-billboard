"""
The sun and the moon where the device is (#619): one page per chosen view, today's times and the moon (`today`), or the sky's arc (`arc`, the paths of the
sun and the moon across the sky and where each is now). Calculated on the device (python/datasources/sky): no network, no key, no cache.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import PermanentError, RenderSession
from ..contracts.provider import device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ..sky.draw import arc_svg, moon_svg
from ..sky.sky import Sky, depression_of, device_place, sky_of

VIEWS = ("today", "arc")

@dataclass(frozen=True)
class Page:
	view: str
	sky: Sky
	twelve_hour: bool
	# a portrait page: the arc is drawn taller
	tall: bool = False

def chosen_views(params: Mapping[str, Any]) -> list[str]:
	"""The views in page order; none chosen reads as today. An unknown one is a PermanentError (fix the settings)."""
	views = params.get("views")
	if views is None or views == []:
		return ["today"]
	if not isinstance(views, list) or any(v not in VIEWS for v in views):
		raise PermanentError(f"Unknown view (one of {', '.join(VIEWS)})")
	return [v for v in VIEWS if v in views]

def clock(when: datetime|None, twelve_hour: bool, base: datetime|None = None) -> str:
	"""A time of day in the device's clock; a time on another date than `base` says so with a mark (the sunset after midnight)."""
	if when is None:
		return ""
	text = f"{when.hour % 12 or 12}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"
	if base is not None and when.date() != base.date():
		text += " (+1)" if when.date() > base.date() else " (-1)"
	return text

def duration(length: timedelta|None) -> str:
	if length is None:
		return ""
	minutes = round(length.total_seconds() / 60)
	return f"{minutes // 60}h {minutes % 60:02d}m"

def change(today: timedelta|None, yesterday: timedelta|None, short: bool = False) -> str:
	"""How much longer or shorter than yesterday, to the minute ("+2m on yesterday", "same as yesterday"; short: "+2m", "+0m")."""
	if today is None or yesterday is None:
		return ""
	minutes = round((today - yesterday).total_seconds() / 60)
	sign = "+" if minutes >= 0 else "-"
	if short:
		return f"{sign}{abs(minutes)}m"
	if minutes == 0:
		return "same as yesterday"
	return f"{sign}{abs(minutes)}m on yesterday"

def page_params(page: Page, params: Mapping[str, Any]) -> dict:
	"""What the template draws: text and drawings ready to place (the template decides nothing about clocks or the sky)."""
	sky, h12 = page.sky, page.twelve_hour
	sun, moon = sky.sun, sky.moon
	base = sun.noon
	if sun.polar == "day":
		note = "The sun does not set today"
	elif sun.polar == "night":
		note = "The sun does not rise today"
	else:
		note = ""
	body: dict[str, Any] = {
		"sunrise": clock(sun.sunrise, h12, base), "sunset": clock(sun.sunset, h12, base), "noon": clock(sun.noon, h12),
		"dawn": clock(sun.dawn, h12, base), "dusk": clock(sun.dusk, h12, base),
		"length": duration(sun.length), "change": change(sun.length, sky.yesterday), "polar": note,
		"moon_name": moon.name, "moon_lit": f"{round(moon.lit * 100)}% lit",
		"moonrise": clock(moon.moonrise, h12), "moonset": clock(moon.moonset, h12),
		"next_full": "Today" if sky.next_full == sky.now.date() else sky.next_full.strftime("%a %b ") + str(sky.next_full.day),
		"next_new": "Today" if sky.next_new == sky.now.date() else sky.next_new.strftime("%a %b ") + str(sky.next_new.day),
		"moon_svg": moon_svg(moon.phase, sky.place.southern),
	}
	if page.view == "arc":
		body["arc_svg"] = arc_svg(sky, body["sunrise"], body["sunset"], tall=page.tall)
		# the line under the arc: a polar day in a few words, and when a moon that is down rises
		body["polar_short"] = { "day": "Sun up all day", "night": "Sun down all day" }.get(sun.polar or "", "")
		rises = moon.moonrise if moon.moonrise is not None and moon.moonrise > sky.now else None
		up = sky.moon_now.elevation >= 0 or rises is None
		body["moon_line"] = f"{moon.name}, {round(moon.lit * 100)}% lit" if up else f"{moon.name}, rises {clock(rises, h12)}"
	heading = params.get("title") or "Sun and Moon"
	return { "view": page.view, "heading": heading, "date": sky.now.strftime("%A, %B ") + str(sky.now.day), "settings": params, **body }

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	rs = RenderSession(stm, render_dir, "sun_moon.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=f"{template_params['heading']}: {template_params['view']}")

class SunMoonAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""The sun and the moon as a slide show: one page per chosen view, calculated for the device's location in its zone."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		views = chosen_views(params)
		_, system = dsec.provider.required(SettingsConfigurationManager).open("system").get()
		place = device_place(system)
		depression = depression_of(params.get("twilight"))
		now = device_now(dsec.timestamp)
		# a few hundred positions for the arc: a moment's work, but not on the event loop
		sky = await asyncio.to_thread(sky_of, place, now, depression)
		twelve = (system or {}).get("timeFormat") == "12h"
		_, display = dsec.provider.required(SettingsConfigurationManager).open("display").get()
		tall = (display or {}).get("orientation") == "portrait"
		return [Page(view, sky, twelve, tall) for view in views]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, Page):
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("sun_moon")
		_, display_config = scm.open("display").get()
		if display_config is None:
			raise ValueError("Display settings is None")
		return await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), page_params(state, params), current_inputs(scm))
