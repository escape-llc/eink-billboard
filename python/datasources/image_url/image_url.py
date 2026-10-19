"""
One picture from a web address: a camera's snapshot, a chart or dashboard image, a weather map. The address is fetched again each time the picture is shown, so an address that always gives the
latest picture always shows the latest. It is a picture of one (`media-image`), a background page like the other pictures (a photograph overlays may be drawn on).

The address is typed in a settings page, so it goes through the URL guard like every download of an address that is not our own constant (`stream_to_buffer`: not this device, not link-local, every
redirect checked), and what comes back is treated as untrusted: a size cap, only PNG, JPEG, GIF and WEBP (by content, never by what the server calls it), a pixel cap, and the first frame of an
animation (`open_picture`). A picture whose shape is not the panel's gets a blurred margin, not white bars.
"""
import logging
from typing import Any, Mapping
from urllib.parse import urlsplit

from PIL import Image

from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import blurred_margin, stream_to_buffer
from ...utils.upload_image import MAX_UPLOAD_BYTES, open_picture
from ...utils.url_guard import UrlRefused

logger = logging.getLogger(__name__)

HEADERS = { "User-Agent": "eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)", "Accept": "image/*" }
MAX_IMAGE_BYTES = MAX_UPLOAD_BYTES

def picture_content_type(content_type: str) -> bool:
	"""A picture, or a server that does not say what it is (a camera often sends `application/octet-stream` or nothing): the content decides, not this."""
	kind = content_type.split(";")[0].strip().lower()
	return kind == "" or kind.startswith("image/") or kind == "application/octet-stream"

def address_of(params: Mapping[str, Any]) -> str:
	"""The task's address, or a `PermanentError` that says what to do (no use trying again)."""
	url = params.get("url")
	if not isinstance(url, str) or not url.strip():
		raise PermanentError("Enter the picture's web address in the task's settings.")
	url = url.strip()
	if urlsplit(url).scheme.lower() not in ("http", "https"):
		raise PermanentError("The picture's address must start with http:// or https://.")
	return url

class ImageUrlAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		# one picture; the address is the whole of the list, fetched when it is shown
		return [{ "url": address_of(params) }]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if state is None:
			return None
		url = address_of({ "url": state.get("url") if isinstance(state, Mapping) else None })
		image = await self._download(url)
		if params.get("shrinkToFit", True) is not False:
			image = blurred_margin(image, target_dimensions(dsec), enlarge=False)
		# the host only: the rest of the address can hold a secret
		return MediaRenderResult(image=image, title=f"Picture from {urlsplit(url).hostname or 'a web address'}")

	async def _download(self, url: str) -> Image.Image:
		"""The picture at `url`. Failures are in our words and never hold the address (it can carry a key); the log has the detail."""
		try:
			client = client_var.get()
			buffer = await stream_to_buffer(client, url, headers=HEADERS, ctok=picture_content_type, max_bytes=MAX_IMAGE_BYTES)
		except UrlRefused as refused:
			# the address is the user's to fix: our own words, and no use trying again
			raise PermanentError(str(refused)) from None
		except RuntimeError as e:
			# our own text from the downloader: the content type, a size over the cap
			self.logger.error(f"'{self.name}' the download failed: {e}")
			raise RuntimeError("The address did not give a picture the device can use (it is too large, or not a picture).") from None
		try:
			return open_picture(buffer.getvalue())
		except ValueError as e:
			self.logger.error(f"'{self.name}' the picture could not be used: {e}")
			raise RuntimeError(str(e)) from None
