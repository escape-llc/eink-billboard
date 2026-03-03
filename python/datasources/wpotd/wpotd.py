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
6. Optionally resize the image to fit the device dimensions. (_shrink_to_fit))
"""
from concurrent.futures import Future
from typing import Any
from PIL import Image, UnidentifiedImageError
from datetime import date, timedelta
from datetime import datetime
import logging
from random import randint
import requests
from io import BytesIO

from ..data_source import DataSource, DataSourceExecutionContext, MediaList, MediaListAsync, MediaRender, MediaRenderAsync, MediaRenderResult
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import stream_to_buffer

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = { 'User-Agent': 'eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)' }

def _determine_date(settings: dict[str, Any], schedule_ts) -> date:
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
	async def open_async(self, dsec: DataSourceExecutionContext, params: dict[str, Any]) -> list:
		datetofetch = _determine_date(params, dsec.timestamp)
		self.logger.info(f"'{self.name}' datetofetch: {datetofetch}")
		data = await self._fetch_potd(datetofetch)
		picurl = data["image_src"]
		return [{"url": picurl, "date": datetofetch}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._download_image(state.get("url"))
		if image is None:
			self.logger.error(f"'{self.name}' Failed to download image.")
			raise RuntimeError(f"'{self.name}' Failed to download image.")
		if params.get("shrinkToFit") == True:
			max_width, max_height = dsec.dimensions
			image = self._shrink_to_fit(image, max_width, max_height)
			self.logger.info(f"'{self.name}' Image resized: {max_width},{max_height}")
		return MediaRenderResult(image=image, title=f"Wikipedia Picture of the Day: {state.get('date', 'Unknown Date')}")
		pass
	def _shrink_to_fit(self, image: Image.Image, max_width: int, max_height: int) -> Image.Image:
		"""
		Resize the image to fit within max_width and max_height while maintaining aspect ratio.
		Uses high-quality resampling.
		"""
		orig_width, orig_height = image.size

		if orig_width > max_width or orig_height > max_height:
			# Determine whether to constrain by width or height
			if orig_width >= orig_height:
				# Landscape or square -> constrain by max_width
				if orig_width > max_width:
					new_width = max_width
					new_height = int(orig_height * max_width / orig_width)
				else:
					new_width, new_height = orig_width, orig_height
			else:
				# Portrait -> constrain by max_height
				if orig_height > max_height:
					new_height = max_height
					new_width = int(orig_width * max_height / orig_height)
				else:
					new_width, new_height = orig_width, orig_height
			# Resize using high-quality resampling
			image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
			# Create a new image with white background and paste the resized image in the center
			new_image = Image.new("RGB", (max_width, max_height), (255, 255, 255))
			new_image.paste(image, ((max_width - new_width) // 2, (max_height - new_height) // 2))
			return new_image
		else:
			# If the image is already within bounds, return it as is
			return image
	async def _download_image(self, url: str) -> Image.Image:
		try:
			if url.lower().endswith(".svg"):
				self.logger.warning("'{self.name}' SVG format is not supported by Pillow. Skipping image download.")
				raise RuntimeError("'{self.name}' Unsupported image format: SVG.")

			client = client_var.get()
#			response = await client.get(url, headers=HEADERS, timeout=10)
#			response.raise_for_status()
			buffer = await stream_to_buffer(client, url, headers=HEADERS)
			return Image.open(buffer)
		except UnidentifiedImageError as e:
			self.logger.error(f"'{self.name}' Unsupported image format at {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Unsupported image format.")
		except Exception as e:
			self.logger.error(f"'{self.name}' Failed to load WPOTD image from {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Failed to load WPOTD image.")
	async def _fetch_potd(self, cur_date: date) -> dict[str, Any]:
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
		image_src = await self._fetch_image_src(filename)
		return {
			"filename": filename,
			"image_src": image_src,
			"image_page_url": f"https://en.wikipedia.org/wiki/{title}",
			"date": cur_date
		}
	async def _make_request(self, params: dict[str, Any]) -> dict[str, Any]:
		try:
			client = client_var.get()
			response = await client.get(API_URL, params=params, headers=HEADERS, timeout=10)
			response.raise_for_status()
			return response.json()
		except Exception as e:
			self.logger.error(f"'{self.name}' Wikipedia API request failed with params {params}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Wikipedia API request failed.")
	async def _fetch_image_src(self, filename: str) -> str:
		params = {
			"action": "query",
			"format": "json",
			"prop": "imageinfo",
			"iiprop": "url",
			"titles": filename
		}
		data = await self._make_request(params)
		try:
			page = next(iter(data["query"]["pages"].values()))
			return page["imageinfo"][0]["url"]
		except (KeyError, IndexError, StopIteration) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve image URL for {filename}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve image URL.")
	pass

class Wpotd(DataSource, MediaList, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, Any]) -> Future[list]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def locate_image_url():
			datetofetch = _determine_date(params, dsec.timestamp)
			self.logger.info(f"'{self.name}' datetofetch: {datetofetch}")
			data = self._fetch_potd(datetofetch)
			picurl = data["image_src"]
			return [{"url": picurl, "date": datetofetch}]
		future = self._es.submit(locate_image_url)
		return future
	def render(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> Future[MediaRenderResult | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def load_next():
			if state is None:
				return None
			image = self._download_image(state.get("url"))
			if image is None:
				self.logger.error(f"'{self.name}' Failed to download image.")
				raise RuntimeError(f"'{self.name}' Failed to download image.")
			if params.get("shrinkToFit") == True:
				max_width, max_height = dsec.dimensions
				image = self._shrink_to_fit(image, max_width, max_height)
				self.logger.info(f"'{self.name}' Image resized: {max_width},{max_height}")
			return MediaRenderResult(image=image, title=f"Wikipedia Picture of the Day: {state.get('date', 'Unknown Date')}")
		future = self._es.submit(load_next)
		return future
	def _fetch_potd(self, cur_date: date) -> dict[str, Any]:
		title = f"Template:POTD/{cur_date.isoformat()}"
		params = {
			"action": "query",
			"format": "json",
			"formatversion": "2",
			"prop": "images",
			"titles": title
		}
		data = self._make_request(params)
		try:
			filename = data["query"]["pages"][0]["images"][0]["title"]
		except (KeyError, IndexError) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve POTD filename for {cur_date}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve POTD filename.")
		image_src = self._fetch_image_src(filename)
		return {
			"filename": filename,
			"image_src": image_src,
			"image_page_url": f"https://en.wikipedia.org/wiki/{title}",
			"date": cur_date
		}
	def _fetch_image_src(self, filename: str) -> str:
		params = {
			"action": "query",
			"format": "json",
			"prop": "imageinfo",
			"iiprop": "url",
			"titles": filename
		}
		data = self._make_request(params)
		try:
			page = next(iter(data["query"]["pages"].values()))
			return page["imageinfo"][0]["url"]
		except (KeyError, IndexError, StopIteration) as e:
			self.logger.error(f"'{self.name}' Failed to retrieve image URL for {filename}: {e}")
			raise RuntimeError(f"'{self.name}' Failed to retrieve image URL.")
	def _make_request(self, params: dict[str, Any]) -> dict[str, Any]:
		try:
			response = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
			response.raise_for_status()
			return response.json()
		except Exception as e:
			self.logger.error(f"'{self.name}' Wikipedia API request failed with params {params}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Wikipedia API request failed.")
	def _shrink_to_fit(self, image: Image.Image, max_width: int, max_height: int) -> Image.Image:
		"""
		Resize the image to fit within max_width and max_height while maintaining aspect ratio.
		Uses high-quality resampling.
		"""
		orig_width, orig_height = image.size

		if orig_width > max_width or orig_height > max_height:
			# Determine whether to constrain by width or height
			if orig_width >= orig_height:
				# Landscape or square -> constrain by max_width
				if orig_width > max_width:
					new_width = max_width
					new_height = int(orig_height * max_width / orig_width)
				else:
					new_width, new_height = orig_width, orig_height
			else:
				# Portrait -> constrain by max_height
				if orig_height > max_height:
					new_height = max_height
					new_width = int(orig_width * max_height / orig_height)
				else:
					new_width, new_height = orig_width, orig_height
			# Resize using high-quality resampling
			image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
			# Create a new image with white background and paste the resized image in the center
			new_image = Image.new("RGB", (max_width, max_height), (255, 255, 255))
			new_image.paste(image, ((max_width - new_width) // 2, (max_height - new_height) // 2))
			return new_image
		else:
			# If the image is already within bounds, return it as is
			return image
	def _download_image(self, url: str) -> Image.Image:
		try:
			if url.lower().endswith(".svg"):
				self.logger.warning("'{self.name}' SVG format is not supported by Pillow. Skipping image download.")
				raise RuntimeError("'{self.name}' Unsupported image format: SVG.")

			response = requests.get(url, headers=self.HEADERS, timeout=10)
			response.raise_for_status()
			return Image.open(BytesIO(response.content))
		except UnidentifiedImageError as e:
			self.logger.error(f"'{self.name}' Unsupported image format at {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Unsupported image format.")
		except Exception as e:
			self.logger.error(f"'{self.name}' Failed to load WPOTD image from {url}: {str(e)}")
			raise RuntimeError(f"'{self.name}' Failed to load WPOTD image.")
