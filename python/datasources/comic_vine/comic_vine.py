"""
Covers of a comic series from Comic Vine, one page per cover. `open_async` lists a page of the series' issues (a random one for a long series, so its
newest or oldest issues are not the only ones shown) in a random order; the Slide Show keeps the list and shows it through (`keepsList`).
`render_async` draws one cover on a blurred margin: a cover is portrait and a panel usually is not.

The key, the search and the kept answers are the Comic Vine API data source's (`comicvine`), asked with `dsec.use`.
"""
import logging
import math
import random
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from ...plugins.plugin_base import PermanentError
from ...utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, blurred_margin
from ..content_cache import download_for
from ..comicvine.comicvine import HEADERS, PAGE, ComicVineApi
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

COMICVINE_ID = "comicvine"
MAX_IMAGE_BYTES = DEFAULT_MAX_DOWNLOAD_BYTES
# a cover does not change: kept for a day (the site's headers can shorten that)
DEFAULT_CONTENT_HOURS = 24.0

logger = logging.getLogger(__name__)

def cover_title(volume: Mapping[str, Any], issue: Mapping[str, Any]) -> str:
	"""What the cover is called in the telemetry: the series, the issue's number and its date."""
	number = f" #{issue['number']}" if issue.get("number") else ""
	date = f" ({issue['date'][:4]})" if issue.get("date") else ""
	return f"{volume.get('name') or 'Comic Vine'}{number}{date}"

class ComicVineCoversAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		series = str(params.get("series") or "").strip()
		if not series:
			raise PermanentError("Enter the series to show.")
		api, api_dsec = dsec.use(COMICVINE_ID, ComicVineApi)
		volume = await api.open_async(api_dsec, { "request": "volume", "query": series })
		pages = max(1, math.ceil(int(volume["issues"]) / PAGE))
		offset = random.randrange(pages) * PAGE
		answer = await api.open_async(api_dsec, { "request": "issues", "volume": volume["id"], "offset": offset })
		if not answer["issues"] and offset > 0:
			# the series has fewer issues than it had (or the count was stale): the first page
			answer = await api.open_async(api_dsec, { "request": "issues", "volume": volume["id"], "offset": 0 })
		covers = [{ "url": issue["cover"], "title": cover_title(volume, issue) } for issue in answer["issues"]]
		if not covers:
			raise PermanentError(f"Comic Vine has no covers for “{volume['name']}”. Choose another series.")
		random.shuffle(covers)
		return covers

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, dict) or not state.get("url"):
			return None
		size = target_dimensions(dsec)
		try:
			# a cover is a picture of ours to fit, from an address Comic Vine gave: it goes through the URL guard, and is kept (a cover does not change)
			buffer = await download_for(dsec, str(state["url"]), default_hours=DEFAULT_CONTENT_HOURS, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
			image = Image.open(buffer)
			image.draft("RGB", (size[0] * 2, size[1] * 2))
			image.load()
		except UnidentifiedImageError:
			raise RuntimeError(f"'{self.name}' the cover is in a format that cannot be read.") from None
		except Exception as e:
			logger.error(f"'{self.name}' could not load the cover ({type(e).__name__}).")
			raise RuntimeError(f"'{self.name}' could not load the cover ({type(e).__name__}).") from None
		return MediaRenderResult(image=blurred_margin(image, size), title=str(state.get("title") or "Comic Vine"))
