import logging
import pytz
import os
from datetime import datetime, timezone
from pathlib import Path

from ...task.display import DisplayImage
from ...task.messages import BasicMessage
from ...model.schedule import PluginSchedule
from ...model.configuration_manager import StaticConfigurationManager
from ...utils.file_utils import path_to_file_url
from ..plugin_base import PluginBase, PluginExecutionContext, RenderSession

logger = logging.getLogger(__name__)
class YearProgress(PluginBase):
	def __init__(self, id, name):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def receive(self, pec: PluginExecutionContext, msg: BasicMessage):
		pass
	def reconfigure(self, pec: PluginExecutionContext, config):
		pass
	def timeslot_start(self, ctx: PluginExecutionContext):
		self.logger.info(f"'{self.name}' timeslot.start '{ctx.sb.title}'.")
		if isinstance(ctx.sb, PluginSchedule):
			dimensions = ctx.resoluion
			data = ctx.sb.content.data
			display_config = ctx.scm.load_settings("display")
			img = None
			try:
				img = self.generate_image(ctx.schedule_ts, ctx.stm, dimensions, data, display_config)
			except Exception as e:
				self.logger.error(f"Failed to draw year progress image: {str(e)}")
			if img is not None:
				self.logger.debug(f"display {ctx.schedule_ts}")
				ctx.router.send("display", DisplayImage(f"{ctx.schedule_ts} year progress", img, ctx.schedule_ts))

	def timeslot_end(self, ctx: PluginExecutionContext):
		self.logger.info(f"'{self.name}' timeslot.end '{ctx.sb.title}'.")
	def schedule(self, ctx: PluginExecutionContext):
		self.logger.info(f"'{self.name}' schedule '{ctx.sb.title}'.")

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