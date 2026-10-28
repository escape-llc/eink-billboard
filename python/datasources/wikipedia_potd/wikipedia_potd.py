"""
Wikipedia's Picture of the Day: today's, a chosen day's or a random day's, credited to its author under its licence.

The day's picture is named by the page `Template:POTD/<date>`; its file's `imageinfo` gives a rendition sized for the panel and the file's
description (`extmetadata`), whose `Artist` and `LicenseShortName` are the credit. This is the method of Wikimedia's own tutorial:
https://www.mediawiki.org/wiki/API:Picture_of_the_day_viewer. Many pictures are CC BY-SA, which asks for the author to be named, so the
page's title carries the credit. Wikimedia asks every client to name itself (`HEADERS`):
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
"""
from typing import Any, Mapping
from PIL import Image, UnidentifiedImageError
from datetime import date, timedelta
from datetime import datetime
import logging
from random import randint

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions, enhanced
from ...task.async_http_worker_pool import client_var
from ..content_cache import download_for
from ...utils.html_text import html_text
from ...utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, blurred_margin

# a POTD original can be tens of megabytes: ask Wikipedia for a thumbnail this many times the display's long side, and refuse bigger downloads
THUMBNAIL_FACTOR = 2
MAX_IMAGE_BYTES = DEFAULT_MAX_DOWNLOAD_BYTES
# the picture of a day does not change: what Wikimedia says (`Cache-Control`) decides, never longer than this
DEFAULT_CONTENT_HOURS = 24.0

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = { 'User-Agent': 'eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)' }

def _determine_date(settings: Mapping[str, Any], schedule_ts) -> date:
	if settings.get("randomizeDate"):
		start = datetime(2015, 1, 1).astimezone(schedule_ts.tzinfo)
		delta_days = (schedule_ts - start).days
		return (start + timedelta(days=randint(0, delta_days))).date()
	elif settings.get("customDate"):
		return datetime.strptime(settings["customDate"], "%Y-%m-%d").date()
	else:
		return schedule_ts.date()

def credit_of(metadata: Any) -> str:
	"""
	"<author>, <licence>" from a file's `extmetadata`, either part left out when it is not there. The author is HTML (a link to their page, often), read
	as text with a parser; an empty credit is "".
	"""
	if not isinstance(metadata, Mapping):
		return ""
	def field(name: str) -> str:
		entry = metadata.get(name)
		value = entry.get("value") if isinstance(entry, Mapping) else None
		return html_text(value) if isinstance(value, str) else ""
	return ", ".join(part for part in (field("Artist"), field("LicenseShortName")) if part)

class WpotdAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		datetofetch = _determine_date(params, dsec.timestamp)
		self.logger.info(f"'{self.name}' datetofetch: {datetofetch}")
		data = await self._fetch_potd(datetofetch, max(target_dimensions(dsec)) * THUMBNAIL_FACTOR)
		return [{"url": data["image_src"], "date": datetofetch, "credit": data["credit"]}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._download_image(dsec, state.get("url"))
		if image is None:
			self.logger.error(f"'{self.name}' Failed to download image.")
			raise RuntimeError(f"'{self.name}' Failed to download image.")
		original = image
		if params.get("shrinkToFit"):
			max_width, max_height = target_dimensions(dsec)
			image = self._shrink_to_fit(image, max_width, max_height)
			self.logger.info(f"'{self.name}' Image resized: {max_width},{max_height}")
		title = f"Wikipedia Picture of the Day: {state.get('date', 'Unknown Date')}"
		credit = state.get("credit")
		return MediaRenderResult(image=enhanced(dsec, image), title=f"{title} ({credit})" if credit else title, original=original)
	def _shrink_to_fit(self, image: Image.Image, max_width: int, max_height: int) -> Image.Image:
		"""
		Fit the image inside max_width x max_height (both sides), keeping the aspect ratio, and centre it on a blurred copy of itself of that size.
		Images that already fit are not enlarged. Uses high-quality resampling.
		"""
		return blurred_margin(image, (max_width, max_height), enlarge=False)
	async def _download_image(self, dsec: DataSourceExecutionContext, url: str) -> Image.Image:
		if url.lower().endswith(".svg"):
			self.logger.warning(f"'{self.name}' SVG format is not supported by Pillow. Skipping image download.")
			raise RuntimeError(f"'{self.name}' Unsupported image format: SVG.")
		try:
			buffer = await download_for(dsec, url, default_hours=DEFAULT_CONTENT_HOURS, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
			img = Image.open(buffer)
			# Image.open is lazy: a corrupt body must fail here
			img.load()
			return img
		except UnidentifiedImageError as e:
			self.logger.error(f"'{self.name}' Unsupported image format at {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Unsupported image format.") from e
		except Exception as e:
			self.logger.error(f"'{self.name}' Failed to load WPOTD image from {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Failed to load WPOTD image.") from e
	async def _fetch_potd(self, cur_date: date, thumb_width: int) -> Mapping[str, Any]:
		title = f"Template:POTD/{cur_date.isoformat()}"
		params = {
			"action": "query",
			"format": "json",
			"formatversion": "2",
			"prop": "images",
			"titles": title
		}
		data = await self._make_request(params)
		try:
			filename = data["query"]["pages"][0]["images"][0]["title"]
		except (KeyError, IndexError) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve POTD filename for {cur_date}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve POTD filename.") from e
		image_src, credit = await self._fetch_image_src(filename, thumb_width)
		return {
			"filename": filename,
			"image_src": image_src,
			"credit": credit,
			"image_page_url": f"https://en.wikipedia.org/wiki/{title}",
			"date": cur_date
		}
	async def _make_request(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
		try:
			client = client_var.get()
			response = await client.get(API_URL, params=params, headers=HEADERS, timeout=10)
			response.raise_for_status()
			return response.json()
		except Exception as e:
			self.logger.error(f"'{self.name}' Wikipedia API request failed: {params}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Wikipedia API request failed.") from e
	async def _fetch_image_src(self, filename: str, thumb_width: int) -> tuple[str, str]:
		"""The address of the file's rendition, and its credit."""
		params = {
			"action": "query",
			"format": "json",
			"prop": "imageinfo",
			# the address, and the file's description: its author and licence
			"iiprop": "url|extmetadata",
			# a bounded rendition instead of the (possibly huge) original; Wikipedia returns the original's URL as thumburl when it is smaller
			"iiurlwidth": thumb_width,
			"titles": filename
		}
		data = await self._make_request(params)
		try:
			page = next(iter(data["query"]["pages"].values()))
			info = page["imageinfo"][0]
			return info.get("thumburl") or info["url"], credit_of(info.get("extmetadata"))
		except (KeyError, IndexError, StopIteration) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve image URL for {filename}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve image URL.") from e
