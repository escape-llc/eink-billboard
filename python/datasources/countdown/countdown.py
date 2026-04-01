from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any, Mapping
import zoneinfo

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...plugins.plugin_base import RenderSession
from ...utils.file_utils import path_to_file_url
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult

def generate_image(schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, display_config) -> MediaRenderResult | None:
	#title = settings.get('title')
	countdown_date_str = settings.get('targetDate')

	if not countdown_date_str:
		raise RuntimeError("Date is required.")

	if display_config.get("orientation") == "portrait":
		dimensions = dimensions[::-1]
	
	timezone = "US/Eastern" #display_config.get_config("timezone", default="America/New_York")
	tz = zoneinfo.ZoneInfo(timezone)
	current_time = schedule_ts.astimezone(tz)

	countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
	countdown_date = countdown_date.replace(tzinfo=tz)

	day_count = (countdown_date.date() - current_time.date()).days
	label = "Days Left" if day_count > 0 else "Days Passed"

	template_params = {
		#"title": title,
		"date": countdown_date.strftime("%B %d, %Y"),
		"day_count": abs(day_count),
		"left_or_passed": "left" if day_count > 0 else "passed",
		"label": label,
		"theme_name": "triadic",
		"settings": settings
	}

	px = Path(os.path.dirname(__file__)).joinpath("render")
	css = path_to_file_url(os.path.join(px.resolve(), "countdown.css"))
	rs = RenderSession(stm, px.resolve(), "countdown.html", css)
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
		return generate_image(dsec.timestamp, stm, dsec.dimensions, params, display_config)
	pass
