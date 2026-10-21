"""
The weather as a slide show: one page per chosen view (now, the next hours, the next days). The data comes from the OpenWeatherMap API data
source (`dsec.use`), whose key, units and kept answers every page and overlay share; this source only draws.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import RenderSession
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ..openweathermap.openweathermap import OpenWeatherMapApi, Report, Units
from .icons import icon_svg, stat_svg

# the API data source it asks: its descriptor's id, never a value from a request
OPENWEATHERMAP_ID = "openweathermap"
VIEWS = ("current", "hours", "days")
FONT_SCALES = { "x-small": 0.7, "small": 0.85, "normal": 1.0, "large": 1.2, "x-large": 1.45 }

@dataclass(frozen=True)
class Page:
	view: str
	report: Report

def chosen_views(params: Mapping[str, Any]) -> list[str]:
	"""The views in page order (now, hours, days); none chosen reads as the weather now."""
	views = params.get("views")
	picked = [v for v in VIEWS if isinstance(views, list) and v in views]
	return picked or ["current"]

def _clock(when: datetime, twelve_hour: bool) -> str:
	return f"{when.hour % 12 or 12} {'AM' if when.hour < 12 else 'PM'}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"

def _time_of_day(when: datetime|None, twelve_hour: bool) -> str:
	if when is None:
		return ""
	return f"{when.hour % 12 or 12}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"

def _degrees(value: float|None) -> str:
	return "" if value is None else f"{round(value)}°"

def _percent(chance: float|None) -> str:
	"""The chance of rain as OpenWeatherMap gives it (0 to 1). 0% is said too: a dry hour is information, and a blank reads as missing."""
	return "" if chance is None else f"{round(max(0.0, min(chance, 1.0)) * 100)}%"

# the table of the hours and of the days: a row for each figure (the page draws one column per hour or day, a row per item in a tall page)
# (the steps' own high and low are within a degree or two of their temperature: they only repeat it, so the hours have no rows for them)
HOUR_ROWS = (("temp", "Temp", "Temp"), ("rain", "Rain", "Rain"), ("humidity", "Humidity", "Hum"), ("wind", "Wind", "Wind"))
DAY_ROWS = (("high", "High", "High"), ("low", "Low", "Low"), ("rain", "Rain", "Rain"), ("humidity", "Humidity", "Hum"), ("wind", "Wind", "Wind"))

def _rows(spec: tuple[tuple[str, str, str], ...], items: list[dict]) -> list[dict]:
	"""The rows that have something to say: one nothing in the forecast filled in is left out. `short` is the title in a tall page, where the columns are narrow."""
	return [{ "key": key, "title": title, "short": short, "glyph": stat_svg(key) } for key, title, short in spec if any(item.get(key) for item in items)]

def _humidity(value: int|None) -> str:
	return "" if value is None else f"{value}%"

def _wind(value: float|None, units: Units) -> str:
	"""The speed alone: the unit is the device's setting, and on every cell it only clutters the table."""
	return "" if value is None else str(units.wind(value))

def page_params(page: Page, params: Mapping[str, Any]) -> dict:
	"""What the template draws for a page: text and drawings ready to place (the template decides nothing about units or clocks)."""
	r, units = page.report, page.report.units
	body: dict[str, Any] = {}
	if page.view == "current" and r.current is not None:
		c = r.current
		body = { "temp": _degrees(c.temp), "feels": _degrees(c.feels), "text": c.text, "icon": icon_svg(c.icon),
			"humidity": "" if c.humidity is None else f"{c.humidity}%", "wind": "" if c.wind is None else f"{units.wind(c.wind)} {units.speed}",
			"sunrise": _time_of_day(r.sunrise, r.twelve_hour), "sunset": _time_of_day(r.sunset, r.twelve_hour) }
	elif page.view == "hours":
		items = [{ "label": _clock(p.when, r.twelve_hour), "icon": icon_svg(p.icon), "temp": _degrees(p.temp),
			"rain": _percent(p.rain), "humidity": _humidity(p.humidity), "wind": _wind(p.wind, units), "text": p.text,
			# the weekday is said above the time of the first column of each day; every other day wears the colors the other way round (`alt`), so a change of day shows
			"new_day": n > 0 and p.when.date() != r.hours[n - 1].when.date(), "day": p.when.strftime("%a") if n == 0 or p.when.date() != r.hours[n - 1].when.date() else "",
			"alt": (p.when.date() - r.hours[0].when.date()).days % 2 == 1 } for n, p in enumerate(r.hours)]
		body = { "hours": items, "items": items, "rows": _rows(HOUR_ROWS, items) }
	elif page.view == "days":
		items = [{ "label": "Today" if d.day == r.now.date() else d.day.strftime("%a"), "icon": icon_svg(d.icon), "temp": "", "high": _degrees(d.high), "low": _degrees(d.low),
			"rain": _percent(d.rain), "humidity": _humidity(d.humidity), "wind": _wind(d.wind, units), "text": d.text } for d in r.days]
		body = { "days": items, "items": items, "rows": _rows(DAY_ROWS, items) }
	heading = params.get("title") or r.place or "Weather"
	return { "view": page.view, "heading": heading, "unit": units.temp, "font_scale": FONT_SCALES.get(str(params.get("fontSize")), 1.0), "settings": params, **body }

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	rs = RenderSession(stm, render_dir, "weather.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=template_params["heading"])

class WeatherAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""The weather as a slide show: one page per chosen view (now, the next hours, the next days)."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		views = chosen_views(params)
		# only what the chosen pages need: the free plan counts calls
		needs = (["current"] if "current" in views else []) + (["forecast"] if "hours" in views or "days" in views else [])
		api, api_dsec = dsec.use(OPENWEATHERMAP_ID, OpenWeatherMapApi)
		report = await api.open_async(api_dsec, { "needs": needs })
		return [Page(view, report) for view in views]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, Page):
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("weather")
		_, display_config = scm.open("display").get()
		if display_config is None:
			raise ValueError("Display settings is None")
		template_params = page_params(state, params)
		return await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), template_params, current_inputs(scm))
