from concurrent.futures import Future
from datetime import datetime
import logging
import os
from pathlib import Path
from PIL import Image
import pytz

from python.plugins.plugin_base import RenderSession
from python.utils.file_utils import path_to_file_url
from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...datasources.data_source import DataSource, DataSourceExecutionContext, MediaItem, MediaRender

class YearProgress(DataSource, MediaItem, MediaRender):
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
			_, display_config = display_cob.get()
			return self.generate_image(context.schedule_ts, stm, context.dimensions, params, display_config)
		future = self._es.submit(render_countdown)
		return future
	def generate_image(self, schedule_ts:datetime, stm: StaticConfigurationManager, dimensions, settings, display_config):
		if display_config.get("orientation") == "portrait":
			dimensions = dimensions[::-1]

		timezone = "US/Eastern" #device_config.get("timezone", default="America/New_York")
		tz = pytz.timezone(timezone)
#		current_time = datetime.now(tz)
		current_time = schedule_ts.astimezone(tz)

		start_of_year = datetime(current_time.year, 1, 1, tzinfo=tz)
		start_of_next_year = datetime(current_time.year + 1, 1, 1, tzinfo=tz)

		total_days = (start_of_next_year - start_of_year).days
		days_left = (start_of_next_year - current_time).total_seconds() / (24 * 3600)
		elapsed_days = (current_time - start_of_year).total_seconds() / (24 * 3600)

		template_params = {
			"year": current_time.year,
			"year_percent": round((elapsed_days / total_days) * 100),
			"days_left": round(days_left),
			"theme_name": "split-complementary",
			"settings": settings
		}
		px = Path(os.path.dirname(__file__)).joinpath("render")
		css = path_to_file_url(os.path.join(px.resolve(), "year_progress.css"))
		rs = RenderSession(stm, px.resolve(), "year_progress.html", css)
		image = rs.render(dimensions, template_params)
		return image
	pass