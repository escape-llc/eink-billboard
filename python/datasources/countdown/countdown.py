import asyncio
from datetime import date, datetime
import logging
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...plugins.plugin_base import RenderSession
from ...model.theme import ThemeInputs, current_inputs
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

# how the count is said, by its sign: the page's label and the word after the number
WORDING = { 1: ("Days Left", "left"), 0: ("Today", "today"), -1: ("Days Passed", "passed") }

def days_between(today: date, target: date) -> int:
	"""Whole days from `today` to `target`: positive before it, 0 on the day, negative after."""
	return target.toordinal() - today.toordinal()

def generate_image(schedule_ts:datetime, stm: StaticConfigurationManager, render_dir: str, dimensions, settings, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	target_text = settings.get('targetDate')
	if not target_text:
		raise RuntimeError("Date is required.")
	target = date.fromisoformat(str(target_text))
	# "today" is the date where the display is: the schedule timestamp already carries the system zone (naive means local)
	today = (schedule_ts if schedule_ts.tzinfo is not None else schedule_ts.astimezone()).date()
	days = days_between(today, target)
	label, word = WORDING[(days > 0) - (days < 0)]
	template_params = {
		"date": target.strftime("%B %d, %Y"),
		"day_count": abs(days),
		"left_or_passed": word,
		"label": label,
		"settings": settings
	}
	rs = RenderSession(stm, render_dir, "countdown.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title="Countdown")

class CountdownAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		# one generated picture: the list is one empty item (an empty list is a source with nothing to show)
		return [{}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("countdown")
		display_cob = scm.open("display")
		_, display_config = display_cob.get()
		if display_config is None:
			raise ValueError("Display settings is None")
		# Chromium is slow and blocking: keep it off the event loop
		return await asyncio.to_thread(generate_image, dsec.timestamp, stm, render_dir, target_dimensions(dsec, display_config), params, current_inputs(scm))
