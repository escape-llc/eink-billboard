import asyncio
import logging
from datetime import date, datetime
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ...plugins.plugin_base import PermanentError
from ..overlay_text import outline_factor, overlay_margin, render_overlay_text, zone_valign
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult

FORMATS = ("long", "full", "short", "numeric", "custom")

def date_parts(day: date|datetime, fmt: str, custom: str|None = None) -> tuple[str, str]:
	"""
	The date as (highlight, rest): the presets highlight the weekday. Built here rather than with strftime's `%-d`, which only some platforms have.
	`custom` is a strftime pattern, all of it plain text. A pattern that is missing or that strftime refuses is a PermanentError (fix the settings).
	"""
	if fmt == "long":
		return (day.strftime("%A"), f", {day.strftime('%B')} {day.day}")
	if fmt == "full":
		return (day.strftime("%A"), f", {day.strftime('%B')} {day.day}, {day.year}")
	if fmt == "short":
		return (day.strftime("%a"), f", {day.strftime('%b')} {day.day}")
	if fmt == "numeric":
		return ("", day.strftime("%Y-%m-%d"))
	if fmt == "custom":
		if not isinstance(custom, str) or not custom.strip():
			raise PermanentError("The custom format is empty")
		try:
			text = day.strftime(custom)
		except ValueError:
			raise PermanentError("The custom format is not a valid strftime pattern") from None
		if not text.strip():
			raise PermanentError("The custom format gives no text")
		return ("", text)
	raise PermanentError(f"Unknown format '{fmt}' (one of {', '.join(FORMATS)})")

class TodayAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""Today's date as outlined text for an overlay zone (python/datasources/overlay_text.py): the theme's overlay font and colors, the weekday highlighted, on a transparent page."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		return {}
	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		# the timestamp is already in the device's zone (ConfiguredTimeOfDay)
		highlight, rest = date_parts(dsec.timestamp, str(params.get("format") or "long"), params.get("customFormat"))
		theme = current_inputs(dsec.provider.required(SettingsConfigurationManager))
		stm = dsec.provider.required(StaticConfigurationManager)
		runs = [run for run in ((highlight, "text-secondary-1"), (rest, "text-primary")) if run[0]]
		# the line sits near the screen's edge, `offset` pixels from it; an overlay renders at the zone's size as given (never through target_dimensions); Chromium is blocking: keep it off the event loop
		image = await asyncio.to_thread(render_overlay_text, stm, theme, dsec.dimensions, runs, outline_factor(params), str(params.get("weight") or "bold"), zone_valign(params), overlay_margin(params))
		return MediaRenderResult(image=image, title=highlight + rest)
