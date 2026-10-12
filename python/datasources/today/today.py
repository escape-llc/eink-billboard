import logging
from datetime import date, datetime
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_palette
from ...plugins.plugin_base import PermanentError
from ...utils.image_compositor import TextRun, text_overlay
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
	"""Today's date as text for an overlay zone, drawn with PIL in the theme's colors (the weekday highlighted), on a transparent box."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		return {}
	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		# the timestamp is already in the device's zone (ConfiguredTimeOfDay)
		highlight, rest = date_parts(dsec.timestamp, str(params.get("format") or "long"), params.get("customFormat"))
		palette = current_palette(dsec.provider.required(SettingsConfigurationManager))
		stm = dsec.provider.required(StaticConfigurationManager)
		# an overlay renders at the zone's size as given (never through target_dimensions)
		width, height = dsec.dimensions
		font_name = str(params.get("font") or "Jost")
		weight = str(params.get("weight") or "bold")
		try:
			# bold is the font's own bold face where it has one; heavy strokes the letters on top of that
			font = stm.get_font(font_name, max(8, int(height * 0.6)), "normal" if weight == "normal" else "bold")
		except ValueError:
			raise PermanentError(f"Font '{font_name}' is not available") from None
		runs: list[TextRun] = [run for run in ((highlight, palette.text_secondary_1.rgb), (rest, palette.text_primary.rgb)) if run[0]]
		# the zones are bands along the top and the bottom of the screen: the line sits near the screen's edge, `offset` pixels from it, not in the middle of the band
		zone = str(params.get("zone") or "")
		valign = "top" if zone.startswith("top") else "bottom" if zone.startswith("bottom") else "center"
		offset = params.get("offset")
		margin = int(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool) and offset >= 0 else 6
		overlay = text_overlay(runs, (width, height), (0, 0), font=font, embolden=0.022 if weight == "heavy" else 0.0, valign=valign, margin=margin)
		return MediaRenderResult(image=overlay.image, title=highlight + rest)
