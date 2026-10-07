from typing import Any, Mapping
from PIL import Image
from datetime import timedelta, datetime
import logging

from httpx import HTTPError

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ...utils.image_utils import get_image_async, to_rgb
from .constants import NEWSPAPERS

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"
KNOWN_SLUGS = frozenset(x["slug"].upper() for x in NEWSPAPERS)

class NewspaperAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		newspaper_slug = params.get('slug')
		if not newspaper_slug:
			raise RuntimeError("Newspaper input not provided.")
		newspaper_slug = str(newspaper_slug).upper()
		# only a slug from our own list may reach the URL
		if newspaper_slug not in KNOWN_SLUGS:
			raise ValueError("Unknown newspaper: choose one from the list.")
		return [newspaper_slug]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._generate_image(state, target_dimensions(dsec), dsec.timestamp)
		if image is not None:
			return MediaRenderResult(image=image, title=f"Newspaper {state}")
		return None
	async def _generate_image(self, newspaper_slug:str, dimensions, timestamp:datetime) -> Image.Image | None:
		if newspaper_slug not in KNOWN_SLUGS:
			raise ValueError("Unknown newspaper.")
		# Get today's date
		today = timestamp
		# check the next day, then today, then prior day
		days = [today + timedelta(days=diff) for diff in [1,0,-1,-2]]

		image = None
		for date in days:
			image_url = FREEDOM_FORUM_URL.format(date.day, newspaper_slug)
			try:
				# decodes the image too, so a corrupt/truncated download is handled like a missing one
				image = await get_image_async(image_url)
				if image:
					self.logger.info(f"Found {newspaper_slug} front cover for {date.strftime('%Y-%m-%d')}")
					break
			except HTTPError as e:
				# status errors and timeouts/connection failures: try the previous day's cover
				self.logger.debug(f"Failed to fetch {image_url}: {type(e).__name__}")
			except Exception as e:
				self.logger.warning(f"Unusable image from {image_url}: {type(e).__name__}: {e}")
		if image is None:
			raise RuntimeError(f"{newspaper_slug}: Newspaper front cover not found.")

		return self._pad_to_ratio(image, dimensions)
	def _pad_to_ratio(self, image: Image.Image, dimensions) -> Image.Image:
		"""Pad (never crop) the cover with white so its aspect ratio equals the target's; the cover is centred."""
		img_width, img_height = image.size
		desired_width, desired_height = dimensions
		img_ratio = img_width / img_height
		desired_ratio = desired_width / desired_height

		if img_ratio < desired_ratio:
			# narrower than the target: widen the canvas
			canvas_size = (int(round(img_height * desired_ratio)), img_height)
		elif img_ratio > desired_ratio:
			# wider than the target: make the canvas taller
			canvas_size = (img_width, int(round(img_width / desired_ratio)))
		else:
			return image
		canvas = Image.new("RGB", canvas_size, (255, 255, 255))
		canvas.paste(to_rgb(image), ((canvas_size[0] - img_width) // 2, (canvas_size[1] - img_height) // 2))
		return canvas
