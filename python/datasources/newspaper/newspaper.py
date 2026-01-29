from concurrent.futures import Future
from PIL import Image
from datetime import timedelta
import datetime
import logging

from ..data_source import DataSource, DataSourceExecutionContext, MediaList, MediaRender
from ...utils.image_utils import get_image

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"
class Newspaper(DataSource, MediaList, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, any]) -> Future[list]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def locate_image_url():
			newspaper_slug = params.get('slug')
			if not newspaper_slug:
				raise RuntimeError("Newspaper input not provided.")
			newspaper_slug = newspaper_slug.upper()
			return [newspaper_slug]
		future = self._es.submit(locate_image_url)
		return future
	def render(self, context: DataSourceExecutionContext, params:dict[str,any], state:any) -> Future[Image.Image | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def load_next():
			if state is None:
				return None
			image = self._generate_image(state, context.dimensions, context.schedule_ts)
			return image
		future = self._es.submit(load_next)
		return future
	def _generate_image(self, newspaper_slug, dimensions, schedule_ts:datetime):
		# Get today's date
		today = schedule_ts
		# check the next day, then today, then prior day
		days = [today + timedelta(days=diff) for diff in [1,0,-1,-2]]

		image = None
		for date in days:
			image_url = FREEDOM_FORUM_URL.format(date.day, newspaper_slug)
			image = get_image(image_url)
			if image:
				logging.info(f"Found {newspaper_slug} front cover for {date.strftime('%Y-%m-%d')}")
				break

		if image:
			# expand height if newspaper is wider than resolution
			img_width, img_height = image.size
			desired_width, desired_height = dimensions

			img_ratio = img_width / img_height
			desired_ratio = desired_width / desired_height

			if img_ratio < desired_ratio:
				new_height =  int((img_width*desired_width) / desired_height)
				new_image = Image.new("RGB", (img_width, new_height), (255, 255, 255))
				new_image.paste(image, (0, 0))
				image = new_image
		else:
			raise RuntimeError("Newspaper front cover not found.")

		return image
	pass