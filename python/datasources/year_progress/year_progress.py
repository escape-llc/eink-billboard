import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from ...plugins.plugin_base import RenderSession
from ...model.theme import ThemeInputs, current_inputs
from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

def generate_image(schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, theme: ThemeInputs|None = None):
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	# the year is the one where the display is: the schedule timestamp already carries the system zone (naive means local)
	current_time = schedule_ts if schedule_ts.tzinfo is not None else schedule_ts.astimezone()
	# wall-clock arithmetic: a DST change must not make a day 23 or 25 hours long
	now = current_time.replace(tzinfo=None)

	start_of_year = datetime(now.year, 1, 1)
	start_of_next_year = datetime(now.year + 1, 1, 1)

	total_days = (start_of_next_year - start_of_year).days
	elapsed_days = (now - start_of_year).total_seconds() / (24 * 3600)
	# floor, never round: 99.6% is not "100% done" and the last day still has a day left
	year_percent = int((elapsed_days / total_days) * 100)
	days_left = (start_of_next_year.date() - now.date()).days

	template_params = {
		"year": current_time.year,
		"year_percent": year_percent,
		"days_left": days_left,
		"settings": settings
	}
	px = Path(os.path.dirname(__file__)).joinpath("render")
	rs = RenderSession(stm, str(px.resolve()), "year_progress.html", theme)
	image = rs.render(dimensions, template_params)
	return image


class YearProgressAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		return {}
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state: Any) -> MediaRenderResult | None:
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		display_cob = scm.open("display")
		_, display_config = display_cob.get()
		if display_config is None:
			raise ValueError("Display settings is None")
		# Chromium is slow and blocking: keep it off the event loop
		img = await asyncio.to_thread(generate_image, dsec.timestamp, stm, target_dimensions(dsec, display_config), params, current_inputs(scm))
		return None if img is None else MediaRenderResult(image=img, title=f"Year Progress: {dsec.timestamp.year}")
