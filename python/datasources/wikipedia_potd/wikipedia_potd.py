"""
Wikipedia's Picture of the Day: today's, a chosen day's or a random day's, credited to its author under its licence.

The day's picture is named by the page `Template:POTD/<date>`; its file's `imageinfo` gives a rendition sized for the panel and the file's
description (`extmetadata`), whose `Artist` and `LicenseShortName` are the credit. This is the method of Wikimedia's own tutorial:
https://www.mediawiki.org/wiki/API:Picture_of_the_day_viewer. Many pictures are CC BY-SA, which asks for the author to be named, so the
page's title carries the credit. Wikimedia asks every client to name itself (`HEADERS`):
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
"""
import logging
import random
from datetime import date, datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

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
# the first day a random day may be
FIRST_RANDOM_DAY = date(2015, 1, 1)

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = { 'User-Agent': 'eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)' }

def day_of(settings: Mapping[str, Any], now: datetime) -> date:
	"""The day whose picture is shown: a random one since FIRST_RANDOM_DAY, the task's own (`YYYY-MM-DD`), or today where the display is."""
	today = now.date()
	if settings.get("randomizeDate"):
		return date.fromordinal(random.randint(FIRST_RANDOM_DAY.toordinal(), max(FIRST_RANDOM_DAY, today).toordinal()))
	chosen = settings.get("customDate")
	return date.fromisoformat(str(chosen)) if chosen else today

def first_page(answer: Any) -> Mapping[str, Any] | None:
	"""The one page a query for one title answers with, in either of the API's formats (a list of pages, or pages by id); None when there is none."""
	pages = answer.get("query", {}).get("pages") if isinstance(answer, Mapping) else None
	if isinstance(pages, Mapping):
		pages = list(pages.values())
	return pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], Mapping) else None

def is_svg(url: str) -> bool:
	"""An SVG file, by the address's path (its query, Wikimedia's `?utm_source=...`, is not part of the name). Wikimedia's rendition of one is a PNG."""
	return urlsplit(url).path.lower().endswith(".svg")

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
		day = day_of(params, dsec.timestamp)
		self.logger.info(f"'{self.name}' picture of {day}")
		file = await self._file_of_day(day)
		url, credit = await self._rendition(file, max(target_dimensions(dsec)) * THUMBNAIL_FACTOR)
		return [{"url": url, "date": day, "credit": credit}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		original = await self._download_image(dsec, state.get("url"))
		image = original
		if params.get("shrinkToFit"):
			image = self._shrink_to_fit(original, *target_dimensions(dsec))
		title = f"Wikipedia Picture of the Day: {state.get('date', 'Unknown Date')}"
		credit = state.get("credit")
		return MediaRenderResult(image=enhanced(dsec, image), title=f"{title} ({credit})" if credit else title, original=original)
	def _shrink_to_fit(self, image: Image.Image, max_width: int, max_height: int) -> Image.Image:
		"""The whole picture inside the page, centred on a blurred copy of itself; one that already fits is not enlarged."""
		return blurred_margin(image, (max_width, max_height), enlarge=False)
	async def _download_image(self, dsec: DataSourceExecutionContext, url: str) -> Image.Image:
		if is_svg(url):
			# only when Wikimedia gave no rendition: PIL cannot read an SVG
			self.logger.warning(f"'{self.name}' The picture is an SVG with no rendition; it cannot be shown.")
			raise RuntimeError(f"'{self.name}' Unsupported image format: SVG.")
		try:
			buffer = await download_for(dsec, url, default_hours=DEFAULT_CONTENT_HOURS, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
			picture = Image.open(buffer)
			# Image.open reads only the header: a corrupt body fails here, not later
			picture.load()
			return picture
		except UnidentifiedImageError as e:
			self.logger.error(f"'{self.name}' Not a picture at {url}: {e}")
			raise RuntimeError(f"'{self.name}' Unsupported image format.") from e
		except Exception as e:
			self.logger.error(f"'{self.name}' The picture at {url} could not be loaded: {e}")
			raise RuntimeError(f"'{self.name}' Failed to load the picture of the day.") from e
	async def _file_of_day(self, day: date) -> str:
		"""The file the day's template page shows (`File:...`)."""
		page = first_page(await self._ask({ "prop": "images", "titles": f"Template:POTD/{day.isoformat()}" }))
		images = page.get("images") if page is not None else None
		if not isinstance(images, list) or not images or not isinstance(images[0], Mapping) or "title" not in images[0]:
			self.logger.error(f"'{self.name}' No picture named for {day}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve POTD filename.")
		return str(images[0]["title"])
	async def _rendition(self, file: str, width: int) -> tuple[str, str]:
		"""The address of the file at `width` (Wikimedia gives the original's when it is smaller), and its credit."""
		# the file's description (`extmetadata`) is its author and licence
		page = first_page(await self._ask({ "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": width, "titles": file }))
		infos = page.get("imageinfo") if page is not None else None
		info = infos[0] if isinstance(infos, list) and infos and isinstance(infos[0], Mapping) else None
		url = (info.get("thumburl") or info.get("url")) if info is not None else None
		if not url:
			self.logger.error(f"'{self.name}' No address for {file}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve image URL.")
		return str(url), credit_of(info.get("extmetadata") if info is not None else None)
	async def _ask(self, query: Mapping[str, Any]) -> Any:
		"""One question to the Action API (a `query`, as JSON); a failure is a RuntimeError in our words."""
		try:
			answer = await client_var.get().get(API_URL, params={ "action": "query", "format": "json", **query }, headers=HEADERS, timeout=10)
			answer.raise_for_status()
			return answer.json()
		except Exception as e:
			self.logger.error(f"'{self.name}' Wikipedia did not answer {dict(query)}: {e}")
			raise RuntimeError(f"'{self.name}' Wikipedia API request failed.") from e
