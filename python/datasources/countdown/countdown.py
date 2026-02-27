from concurrent.futures import Future
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any
from PIL import Image
import zoneinfo

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...plugins.plugin_base import RenderSession
from ...utils.file_utils import path_to_file_url
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItem, MediaRender, MediaRenderResult

class Countdown(DataSource, MediaItem, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, Any]) -> Future[Any]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def open_countdown():
			return {}
			pass
		future = self._es.submit(open_countdown)
		return future
	def render(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> Future[MediaRenderResult | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		def render_countdown():
			display_cob = scm.open("display")
			_, display_config = display_cob.get()
			return self.generate_image(dsec.timestamp, stm, dsec.dimensions, params, display_config)
		future = self._es.submit(render_countdown)
		return future
	def generate_image(self, schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, display_config) -> MediaRenderResult | None:
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