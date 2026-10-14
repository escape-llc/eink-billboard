"""
NASA's Astronomy Picture of the Day (#278): today's picture, a day the user chose, or a random day. Nothing here needs a key.

The pictures come from NASA's public WordPress API (`science.nasa.gov/wp-json/wp/v2/apod-basic`): a list of the latest days, and one day by its `yymmdd` id.
A day can be a video, which cannot be shown: for the latest picture and a random day the next one is taken, for a day the user chose it is said, in our words.
The picture (`hdurl`) is fitted to the screen with a blurred margin (`blurred_margin`).
"""
import html
import logging
from datetime import date, datetime, timedelta
from random import randint
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, blurred_margin, stream_to_buffer
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

API_URL = "https://science.nasa.gov/wp-json/wp/v2/apod-basic"
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "application/json" }
# the first Picture of the Day; some early days have none, so a random day is asked for again a few times
FIRST_DAY = date(1995, 6, 16)
RANDOM_TRIES = 6
LATEST_COUNT = 25
MAX_IMAGE_BYTES = DEFAULT_MAX_DOWNLOAD_BYTES

def day_id(day: date) -> str:
	"""A day as the API names it: yymmdd."""
	return f"{day:%y%m%d}"

def chosen_day(params: Mapping[str, Any]) -> date|None:
	"""The day the user chose, or None (today's picture). A date that is not one is a settings problem."""
	value = params.get("customDate")
	if not value:
		return None
	try:
		return datetime.strptime(str(value), "%Y-%m-%d").date()
	except ValueError:
		raise PermanentError("The custom date must be a day like 2026-10-14.") from None

def random_day(today: date) -> date:
	return FIRST_DAY + timedelta(days=randint(0, max(0, (today - FIRST_DAY).days - 1)))

def picture_of(entry: Any) -> dict[str, Any]|None:
	"""What is kept of one day, or None when it is not a picture (a video) or has no image address."""
	if not isinstance(entry, dict) or entry.get("media_type") != "image":
		return None
	url = entry.get("hdurl")
	if not isinstance(url, str) or not url.startswith("https://"):
		return None
	return { "date": str(entry.get("date") or ""), "title": html.unescape(str(entry.get("title") or "")).strip(), "url": url }

class ApodAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	async def _get(self, path: str = "", params: Mapping[str, Any]|None = None) -> Any:
		"""NASA's answer as JSON; None for a day it has no page for (404). Anything else that goes wrong is ours to word: never the address."""
		try:
			response = await client_var.get().get(f"{API_URL}{path}", params=params, headers=HEADERS, timeout=15)
			if response.status_code == 404:
				return None
			response.raise_for_status()
			return response.json()
		except Exception as e:
			self.logger.error(f"'{self.name}' NASA's API request failed ({type(e).__name__}).")
			raise RuntimeError(f"'{self.name}' could not get the picture list from NASA ({type(e).__name__}).") from None

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		day = chosen_day(params)
		if day is not None and params.get("randomizeDate") is not True:
			entry = await self._get(f"/{day_id(day)}")
			if entry is None:
				raise PermanentError(f"NASA has no Picture of the Day for {day}. Choose another date.")
			found = picture_of(entry)
			if found is None:
				raise PermanentError(f"The Picture of the Day for {day} is not a picture (a video). Choose another date.")
			return [found]
		if params.get("randomizeDate") is True:
			today = dsec.timestamp.date()
			for _ in range(RANDOM_TRIES):
				found = picture_of(await self._get(f"/{day_id(random_day(today))}"))
				if found is not None:
					return [found]
			raise RuntimeError(f"'{self.name}' found no picture for a random day after {RANDOM_TRIES} tries.")
		# the latest days, newest first: today's picture, or the last one before it when today's is a video or not published yet
		latest = await self._get(params={ "per_page": LATEST_COUNT })
		for entry in latest if isinstance(latest, list) else []:
			found = picture_of(entry)
			if found is not None:
				return [found]
		raise RuntimeError(f"'{self.name}' found no picture in NASA's latest {LATEST_COUNT} days.")

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, dict) or not state.get("url"):
			return None
		size = target_dimensions(dsec)
		try:
			buffer = await stream_to_buffer(client_var.get(), str(state["url"]), headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
			image = Image.open(buffer)
			# a JPEG is decoded at a reduced size (a power of two, still at least twice the screen's): the originals run to tens of megapixels
			image.draft("RGB", (size[0] * 2, size[1] * 2))
			# decode now: a truncated body must fail here
			image.load()
		except UnidentifiedImageError:
			raise RuntimeError(f"'{self.name}' the picture is in a format that cannot be read.") from None
		except Exception as e:
			self.logger.error(f"'{self.name}' could not load the picture ({type(e).__name__}: {e}).")
			raise RuntimeError(f"'{self.name}' could not load the picture ({type(e).__name__}).") from None
		title = state.get("title") or "Picture of the Day"
		return MediaRenderResult(image=blurred_margin(image, size), title=f"NASA Picture of the Day: {title} ({state.get('date')})")
