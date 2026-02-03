from concurrent.futures import Future
from datetime import datetime
import logging
import os
from pathlib import Path
from PIL import Image
import pytz

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...plugins.plugin_base import RenderSession
from ...utils.file_utils import path_to_file_url
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItem, MediaRender

class Countdown(DataSource, MediaItem, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, any]) -> Future[any]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def open_countdown():
			return {}
			pass
		future = self._es.submit(open_countdown)
		return future
	def render(self, context: DataSourceExecutionContext, params:dict[str,any], state:any) -> Future[Image.Image | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		scm = context.provider.required(SettingsConfigurationManager)
		stm = context.provider.required(StaticConfigurationManager)
		def render_countdown():
			display_cob = scm.load_settings("display")
			(_, display_config) = display_cob.get()
			return self.generate_image(context.schedule_ts, stm, context.dimensions, params, display_config)
		future = self._es.submit(render_countdown)
		return future
	def generate_image(self, schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, display_config):
		#title = settings.get('title')
		countdown_date_str = settings.get('targetDate')

		if not countdown_date_str:
			raise RuntimeError("Date is required.")

		if display_config.get("orientation") == "portrait":
			dimensions = dimensions[::-1]
		
		timezone = "US/Eastern" #display_config.get_config("timezone", default="America/New_York")
		tz = pytz.timezone(timezone)
#		current_time = datetime.now(tz)
		current_time = schedule_ts.astimezone(tz)

		countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
		countdown_date = tz.localize(countdown_date)

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
		return image