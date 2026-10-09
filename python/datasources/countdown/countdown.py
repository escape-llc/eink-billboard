import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...plugins.plugin_base import RenderSession
from ...model.theme import ThemeInputs, current_inputs
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

def generate_image(schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	#title = settings.get('title')
	countdown_date_str = settings.get('targetDate')

	if not countdown_date_str:
		raise RuntimeError("Date is required.")

	# "today" is the date where the display is: the schedule timestamp already carries the system zone (naive means local)
	current_time = schedule_ts if schedule_ts.tzinfo is not None else schedule_ts.astimezone()

	countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")

	day_count = (countdown_date.date() - current_time.date()).days
	if day_count > 0:
		label, left_or_passed = "Days Left", "left"
	elif day_count == 0:
		label, left_or_passed = "Today", "today"
	else:
		label, left_or_passed = "Days Passed", "passed"

	template_params = {
		#"title": title,
		"date": countdown_date.strftime("%B %d, %Y"),
		"day_count": abs(day_count),
		"left_or_passed": left_or_passed,
		"label": label,
		"settings": settings
	}

	px = Path(os.path.dirname(__file__)).joinpath("render")
	rs = RenderSession(stm, str(px.resolve()), "countdown.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title="Countdown")

class CountdownAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		return {}
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		display_cob = scm.open("display")
		_, display_config = display_cob.get()
		if display_config is None:
			raise ValueError("Display settings is None")
		# Chromium is slow and blocking: keep it off the event loop
		return await asyncio.to_thread(generate_image, dsec.timestamp, stm, target_dimensions(dsec, display_config), params, current_inputs(scm))
	pass
