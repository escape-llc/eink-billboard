"""
Museum Art (#618): public-domain works from a museum's open collection, one picture per page on a blurred margin, with its title, artist, date and museum.

`open_async` asks the task's museum (python/datasources/museum_art/museums.py) for a random page of the works that match the task's search, public domain
and with a picture, and answers them shuffled; the Slide Show keeps the list and shows it through before asking again (`keepsList`), so nothing repeats
until the list is used up. The museums' answers are kept (`cached`: `searchCacheHours`, and `recordCacheHours` for The Met's works) and the pictures
too (`download_for`), so a slow pass stays well inside the Art Institute's 60 requests a minute.
"""
import asyncio
import base64
import io
import logging
import random
from typing import Any, Awaitable, Callable, Mapping

import httpx
from PIL import Image, UnidentifiedImageError

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import PermanentError, RenderSession
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, blurred_margin
from ..content_cache import download_for, retain
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions, enhanced
from ..metering import metered_as
from ..response_cache import cached
from .museums import MUSEUMS, PICTURE_HEADERS, Answer, Refused, museum_of

MAX_IMAGE_BYTES = DEFAULT_MAX_DOWNLOAD_BYTES
# a work does not change: kept a week by default (the museum's headers can shorten that)
DEFAULT_CONTENT_HOURS = 168.0
DEFAULT_SEARCH_HOURS = 24.0
DEFAULT_RECORD_HOURS = 168.0

logger = logging.getLogger(__name__)

def chosen(params: Mapping[str, Any]) -> tuple[str, str, str|None]:
	"""The task's museum, its search (trimmed; empty is any work) and The Met's department (none for another museum)."""
	museum = museum_of(params)
	query = " ".join(str(params.get("search") or "").split())[:100]
	department = params.get("department")
	department = str(department) if museum.key == "met" and isinstance(department, (str, int)) and str(department).isdigit() else None
	return museum.key, query, department

def scope_of(museum: str, query: str, department: str|None) -> str:
	"""The list the pictures belong to (`retain`): another search's pictures stay."""
	return f"works:{museum}|{query}|{department or ''}"

def caption_of(work: Mapping[str, Any]) -> dict[str, str]:
	museum = MUSEUMS.get(str(work.get("museum")))
	return { "title": str(work.get("title") or "Untitled"), "artist": str(work.get("artist") or ""), "date": str(work.get("date") or ""),
		"museum": museum.name if museum is not None else "" }

def picture_data_uri(image: Image.Image) -> str:
	"""The page's picture, embedded (the page fetches nothing): a JPEG, since it is a painting and a PNG of it would be large."""
	out = io.BytesIO()
	image.convert("RGB").save(out, "JPEG", quality=92)
	return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")

def render_page(stm: StaticConfigurationManager, render_dir: str, size: tuple[int, int], params: dict, theme: ThemeInputs|None = None) -> Image.Image|None:
	"""Blocking: Chromium draws the page."""
	return RenderSession(stm, render_dir, "museum_art.html", theme).render(size, params)

class MuseumArtAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""Public-domain works of a museum as a slide show: a random page of a search, shuffled; one work per page."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)

	def _ask(self, dsec: DataSourceExecutionContext) -> Callable[[str, Callable[[], Awaitable[Answer]]], Awaitable[Answer]]:
		"""How a museum's answer is asked for: kept in the data source's folder for its setting's time (a context without the folder asks every time)."""
		dscm = dsec.provider.get_service(DatasourceConfigurationManager)
		if not isinstance(dscm, DatasourceConfigurationManager):
			return lambda key, fetch: fetch()
		_, settings = dscm.open().get()
		async def ask(key: str, fetch: Callable[[], Awaitable[Answer]]) -> Answer:
			record = key.startswith("met-object|")
			return await cached(dscm, settings or {}, key, dsec.timestamp, fetch,
				DEFAULT_RECORD_HOURS if record else DEFAULT_SEARCH_HOURS, "recordCacheHours" if record else "searchCacheHours")
		return ask

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		key, query, department = chosen(params)
		museum = MUSEUMS[key]
		try:
			# the pool's client, counted under this data source on the System page's API usage
			with metered_as(self.id):
				works = await museum.search(client_var.get(), self._ask(dsec), query, department)
		except Refused as e:
			raise RuntimeError(f"'{self.name}' could not search {museum.name} ({e}).") from None
		except httpx.HTTPError as e:
			raise RuntimeError(f"'{self.name}' could not reach {museum.name} ({type(e).__name__}).") from None
		if not works:
			what = f"“{query}”" if query else "the search"
			raise PermanentError(f"{museum.name} has no public-domain works with a picture that match {what}. Try other words.")
		random.shuffle(works)
		dscm = dsec.provider.get_service(DatasourceConfigurationManager)
		if isinstance(dscm, DatasourceConfigurationManager):
			# the list was just loaded: the kept pictures of this search's earlier lists go
			retain(dscm, scope_of(key, query, department), [w.image for w in works])
		return [w.as_dict() for w in works]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		if not isinstance(state, dict) or not isinstance(state.get("image"), str):
			return None
		key, query, department = chosen(params)
		size = target_dimensions(dsec)
		try:
			# the picture's address came in the museum's answer: it goes through the URL guard, and is kept
			buffer = await download_for(dsec, state["image"], default_hours=DEFAULT_CONTENT_HOURS, headers=PICTURE_HEADERS, ctok=lambda ct: ct.startswith("image/"),
				max_bytes=MAX_IMAGE_BYTES, scope=scope_of(key, query, department))
			image = Image.open(buffer)
			image.draft("RGB", (size[0] * 2, size[1] * 2))
			image.load()
		except UnidentifiedImageError:
			raise RuntimeError(f"'{self.name}' the picture is in a format that cannot be read.") from None
		except Exception as e:
			logger.error(f"'{self.name}' could not load the picture ({type(e).__name__}).")
			raise RuntimeError(f"'{self.name}' could not load the picture ({type(e).__name__}).") from None
		# the photograph is enhanced before anything is drawn over it: the caption page embeds the enhanced picture
		picture = enhanced(dsec, blurred_margin(image, size))
		caption = caption_of(state)
		title = f"{caption['title']}, {caption['artist']}" if caption["artist"] else caption["title"]
		if params.get("showCaption") is False:
			# the picture alone: a background page, which overlays may draw on
			return MediaRenderResult(image=picture, title=title, layer="background")
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("museum_art")
		page = await asyncio.to_thread(render_page, stm, render_dir, size, { "picture": picture_data_uri(picture), **caption, "settings": dict(params) }, current_inputs(scm))
		# with its caption: a foreground page, so no overlay covers the caption; a page Chromium could not draw still shows the work, without its
		# caption, as a background page
		return MediaRenderResult(image=page if page is not None else picture, title=title, layer="foreground" if page is not None else "background")

