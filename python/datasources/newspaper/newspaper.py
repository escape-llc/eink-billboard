from typing import Any
from PIL import Image
from datetime import timedelta, datetime
import logging

from httpx import HTTPStatusError

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult
from ...utils.image_utils import get_image, get_image_async

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"
class NewspaperAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: dict[str, Any]) -> list:
		newspaper_slug = params.get('slug')
		if not newspaper_slug:
			raise RuntimeError("Newspaper input not provided.")
		newspaper_slug = newspaper_slug.upper()
		return [newspaper_slug]
	async def render_async(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._generate_image(state, dsec.dimensions, dsec.timestamp)
		if image is not None:
			return MediaRenderResult(image=image, title=f"Newspaper {state}")
		return None
	async def _generate_image(self, newspaper_slug:str, dimensions, timestamp:datetime) -> Image.Image | None:
		# Get today's date
		today = timestamp
		# check the next day, then today, then prior day
		days = [today + timedelta(days=diff) for diff in [1,0,-1,-2]]

		image = None
		for date in days:
			image_url = FREEDOM_FORUM_URL.format(date.day, newspaper_slug)
			try:
				image = await get_image_async(image_url)
				if image:
					self.logger.info(f"Found {newspaper_slug} front cover for {date.strftime('%Y-%m-%d')}")
					break
			except HTTPStatusError as e:
				self.logger.debug(f"Failed to fetch {image_url}: {e.response.status_code}")
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
			raise RuntimeError(f"{newspaper_slug}: Newspaper front cover not found.")

		return image
