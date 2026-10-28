import asyncio
from datetime import date, datetime, time
import logging
from typing import Any, Mapping

from ...plugins.plugin_base import RenderSession
from ...model.theme import ThemeInputs, current_inputs
from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

def day_grid(today: date) -> dict[str, int]:
	"""
	What the page's grid of days needs: one cell per day of the year in columns of a week (Monday at the top), so `lead` empty cells come before
	the 1st of January; `today` is the day of the year counted from 0 (the days before it are past).
	"""
	first = date(today.year, 1, 1)
	days = date(today.year + 1, 1, 1).toordinal() - first.toordinal()
	lead = first.weekday()
	return { "days": days, "today": today.toordinal() - first.toordinal(), "lead": lead, "weeks": -(-(lead + days) // 7) }

def generate_image(schedule_ts:datetime, stm: StaticConfigurationManager, render_dir: str, dimensions, settings, theme: ThemeInputs|None = None):
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	# the year is the one where the display is: the schedule timestamp already carries the system zone (naive means local)
	current_time = schedule_ts if schedule_ts.tzinfo is not None else schedule_ts.astimezone()
	# wall-clock arithmetic: a DST change must not make a day 23 or 25 hours long
	now = current_time.replace(tzinfo=None)

	grid = day_grid(now.date())
	# the share of the year gone by: the whole days before today and the part of today; floored, so 99.6% is not "100% done"
	part_of_today = (now - datetime.combine(now.date(), time())).total_seconds() / 86400
	year_percent = int((grid["today"] + part_of_today) * 100 / grid["days"])
	# today counts as left until it is over
	days_left = grid["days"] - grid["today"]

	template_params = {
		"year": current_time.year,
		"year_percent": year_percent,
		"days_left": days_left,
		**grid,
		"settings": settings
	}
	rs = RenderSession(stm, render_dir, "year_progress.html", theme)
	image = rs.render(dimensions, template_params)
	return image


class YearProgressAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		# one generated picture: the list is one empty item (an empty list is a source with nothing to show)
		return [{}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state: Any) -> MediaRenderResult | None:
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("year_progress")
		display_cob = scm.open("display")
		_, display_config = display_cob.get()
		if display_config is None:
			raise ValueError("Display settings is None")
		# Chromium is slow and blocking: keep it off the event loop
		img = await asyncio.to_thread(generate_image, dsec.timestamp, stm, render_dir, target_dimensions(dsec, display_config), params, current_inputs(scm))
		return None if img is None else MediaRenderResult(image=img, title=f"Year Progress: {dsec.timestamp.year}")
