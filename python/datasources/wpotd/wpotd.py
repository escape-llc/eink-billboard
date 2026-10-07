"""
It supports optional manual date selection or random dates and can resize the image to fit the device's dimensions.

Wikipedia API Documentation: https://www.mediawiki.org/wiki/API:Main_page
Picture of the Day example: https://www.mediawiki.org/wiki/API:Picture_of_the_day_viewer
Github Repository: https://github.com/wikimedia/mediawiki-api-demos/tree/master/apps/picture-of-the-day-viewer
Wikimedia requires a User Agent header for API requests, which is set in the request headers:
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy

Flow:
1. Fetch the date to use for the Picture of the Day (POTD) based on settings. (_determine_date)
2. Make an API request to fetch the POTD data for that date. (_fetch_potd)
3. Extract the image filename from the response. (_fetch_potd)
4. Make another API request to get the image URL. (_fetch_image_src)
5. Download the image from the URL. (_download_image)
5a. NOTE: sometimes the "image" is actually a video: raise error
6. Optionally resize the image to fit the device dimensions. (_shrink_to_fit))
"""
from typing import Any, Mapping
from PIL import Image, UnidentifiedImageError
from datetime import date, timedelta
from datetime import datetime
import logging
from random import randint

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, stream_to_buffer, to_rgb

# a POTD original can be tens of megabytes: ask Wikipedia for a thumbnail this many times the display's long side, and refuse bigger downloads
THUMBNAIL_FACTOR = 2
MAX_IMAGE_BYTES = DEFAULT_MAX_DOWNLOAD_BYTES

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = { 'User-Agent': 'eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)' }

def _determine_date(settings: Mapping[str, Any], schedule_ts) -> date:
	if settings.get("randomizeDate") == True:
		start = datetime(2015, 1, 1).astimezone(schedule_ts.tzinfo)
		delta_days = (schedule_ts - start).days
		return (start + timedelta(days=randint(0, delta_days))).date()
	elif settings.get("customDate"):
		return datetime.strptime(settings["customDate"], "%Y-%m-%d").date()
	else:
		return schedule_ts.date()

class WpotdAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		datetofetch = _determine_date(params, dsec.timestamp)
		self.logger.info(f"'{self.name}' datetofetch: {datetofetch}")
		data = await self._fetch_potd(datetofetch, max(target_dimensions(dsec)) * THUMBNAIL_FACTOR)
		picurl = data["image_src"]
		return [{"url": picurl, "date": datetofetch}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._download_image(state.get("url"))
		if image is None:
			self.logger.error(f"'{self.name}' Failed to download image.")
			raise RuntimeError(f"'{self.name}' Failed to download image.")
		if params.get("shrinkToFit") == True:
			max_width, max_height = target_dimensions(dsec)
			image = self._shrink_to_fit(image, max_width, max_height)
			self.logger.info(f"'{self.name}' Image resized: {max_width},{max_height}")
		return MediaRenderResult(image=image, title=f"Wikipedia Picture of the Day: {state.get('date', 'Unknown Date')}")
		pass
	def _shrink_to_fit(self, image: Image.Image, max_width: int, max_height: int) -> Image.Image:
		"""
		Fit the image inside max_width x max_height (both sides), keeping the aspect ratio, and centre it on a white canvas of that size.
		Images that already fit are not enlarged. Uses high-quality resampling.
		"""
		orig_width, orig_height = image.size
		scale = min(1.0, max_width / orig_width, max_height / orig_height)
		new_width = max(1, int(orig_width * scale))
		new_height = max(1, int(orig_height * scale))
		if (new_width, new_height) != (orig_width, orig_height):
			image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
		# alpha/palette images are pasted onto white paper
		image = to_rgb(image)
		new_image = Image.new("RGB", (max_width, max_height), (255, 255, 255))
		new_image.paste(image, ((max_width - new_width) // 2, (max_height - new_height) // 2))
		return new_image
	async def _download_image(self, url: str) -> Image.Image:
		if url.lower().endswith(".svg"):
			self.logger.warning(f"'{self.name}' SVG format is not supported by Pillow. Skipping image download.")
			raise RuntimeError(f"'{self.name}' Unsupported image format: SVG.")
		try:
			client = client_var.get()
			buffer = await stream_to_buffer(client, url, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
			img = Image.open(buffer)
			# Image.open is lazy: a corrupt body must fail here
			img.load()
			return img
		except UnidentifiedImageError as e:
			self.logger.error(f"'{self.name}' Unsupported image format at {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Unsupported image format.")
		except Exception as e:
			self.logger.error(f"'{self.name}' Failed to load WPOTD image from {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Failed to load WPOTD image.")
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
			raise RuntimeError(f"'{self.name}' Failed to retrieve POTD filename.")
		image_src = await self._fetch_image_src(filename, thumb_width)
		return {
			"filename": filename,
			"image_src": image_src,
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
			raise RuntimeError(f"'{self.name}' Wikipedia API request failed.")
	async def _fetch_image_src(self, filename: str, thumb_width: int) -> str:
		params = {
			"action": "query",
			"format": "json",
			"prop": "imageinfo",
			"iiprop": "url",
			# a bounded rendition instead of the (possibly huge) original; Wikipedia returns the original's URL as thumburl when it is smaller
			"iiurlwidth": thumb_width,
			"titles": filename
		}
		data = await self._make_request(params)
		try:
			page = next(iter(data["query"]["pages"].values()))
			info = page["imageinfo"][0]
			return info.get("thumburl") or info["url"]
		except (KeyError, IndexError, StopIteration) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve image URL for {filename}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve image URL.")
