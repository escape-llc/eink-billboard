from typing import Any, Mapping
from PIL import Image
from datetime import date, datetime, timedelta
import logging

from httpx import HTTPError

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions, enhanced
from ...utils.image_utils import blurred_margin
from ..content_cache import download_for
from .constants import NEWSPAPERS

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"
# the cover of a day is not changed later; the address names only the day of the month, so it is not kept for long (the site's headers can shorten it)
DEFAULT_CONTENT_HOURS = 12.0
KNOWN_SLUGS = frozenset(x["slug"].upper() for x in NEWSPAPERS)
# the site's day can be ahead of ours (a paper in an earlier time zone) or late: tomorrow's cover first, then today's, then up to two days back
COVER_DAY_OFFSETS = (1, 0, -1, -2)

def cover_days(today: date) -> list[date]:
	"""The days whose cover is looked for, in order."""
	return [today + timedelta(days=offset) for offset in COVER_DAY_OFFSETS]

class NewspaperAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		newspaper_slug = params.get('slug')
		if not newspaper_slug:
			raise RuntimeError("Choose a newspaper first.")
		newspaper_slug = str(newspaper_slug).upper()
		# only a slug from our own list may reach the URL
		if newspaper_slug not in KNOWN_SLUGS:
			raise ValueError("Unknown newspaper: choose one from the list.")
		return [newspaper_slug]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._generate_image(dsec, state, target_dimensions(dsec), dsec.timestamp)
		if image is not None:
			return MediaRenderResult(image=enhanced(dsec, image), title=f"Newspaper {state}")
		return None
	async def _generate_image(self, dsec: DataSourceExecutionContext, newspaper_slug:str, dimensions, timestamp:datetime) -> Image.Image | None:
		if newspaper_slug not in KNOWN_SLUGS:
			raise ValueError("Unknown newspaper.")
		for day in cover_days(timestamp.date()):
			cover = await self._cover(dsec, newspaper_slug, day)
			if cover is not None:
				self.logger.info(f"Found {newspaper_slug} front cover for {day.isoformat()}")
				return self._pad_to_ratio(cover, dimensions)
		raise RuntimeError(f"{newspaper_slug}: Newspaper front cover not found.")
	async def _cover(self, dsec: DataSourceExecutionContext, newspaper_slug: str, day: date) -> Image.Image | None:
		"""The cover the site has for `day`, or None when it has none or what it sent is not a picture."""
		url = FREEDOM_FORUM_URL.format(day.day, newspaper_slug)
		try:
			# kept (the cover of a day does not change; a day with no cover is an error and is not kept); decoded here, so a corrupt download is no cover
			buffer = await download_for(dsec, url, default_hours=DEFAULT_CONTENT_HOURS, ctok=lambda ct: ct.startswith("image/"))
			cover = Image.open(buffer)
			cover.load()
			return cover
		except HTTPError as e:
			# a status error, a timeout or a failed connection: the day before may have one
			self.logger.debug(f"Failed to fetch {url}: {type(e).__name__}")
		except Exception as e:
			self.logger.warning(f"Unusable image from {url}: {type(e).__name__}: {e}")
		return None
	def _pad_to_ratio(self, image: Image.Image, dimensions) -> Image.Image:
		"""Pad (never crop) the cover with a blurred copy of itself so its aspect ratio equals the target's; the cover is centred."""
		width, height = image.size
		target_width, target_height = dimensions
		# compared as whole numbers (cross-multiplied), so a cover already the page's shape is returned as it is
		if width * target_height == height * target_width:
			return image
		if width * target_height < height * target_width:
			canvas = (round(height * target_width / target_height), height)
		else:
			canvas = (width, round(width * target_height / target_width))
		return blurred_margin(image, canvas, enlarge=False)
