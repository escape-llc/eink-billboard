import asyncio
import base64
from datetime import datetime
import io
import logging
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

import feedparser
from PIL import Image

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import PermanentError, RenderSession
from ...utils.image_utils import to_rgb
from ..content_cache import download_for, retain
from ...utils.text_utils import unescape_text
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

# the text sizes of the descriptor, as a multiple of the page's base size
FONT_SCALES = { "x-small": 0.7, "small": 0.85, "normal": 1.0, "large": 1.2, "x-large": 1.45 }
# a slide show steps through the stories: more than this is a feed that was not meant for a billboard
MAX_STORIES = 20
# a feed is text: a few hundred kilobytes is a long one
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_PICTURE_BYTES = 4 * 1024 * 1024
# how long a feed's body, and a story's picture, is trusted without asking (what the site's headers say can shorten it)
DEFAULT_FEED_HOURS = 0.25
DEFAULT_PICTURE_HOURS = 24.0
# a story's picture is shown at most this large, so it is shrunk before it goes into the page
PICTURE_BOX = (900, 900)
SUMMARY_CHARS = 700
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5" }

# a block tag ends a line of text, so it becomes a space; an inline one (<b>, <em>, <a>) leaves the words as they were
_BLOCK_TAGS = re.compile(r"</?(?:p|br|div|li|ul|ol|h[1-6]|tr|td|blockquote|figure|figcaption)[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

def plain_text(value: Any, limit: int|None = None) -> str:
	"""
	Text a feed gives as (possibly escaped) HTML, as plain text on one line. Tags are dropped, entities read, and once more for
	markup that arrived escaped (`&lt;p&gt;`). `limit` cuts at a word with an ellipsis.
	"""
	text = value if isinstance(value, str) else ""
	def strip(markup: str) -> str:
		return _TAGS.sub("", _BLOCK_TAGS.sub(" ", markup))
	text = _SPACE.sub(" ", strip(unescape_text(strip(text)))).strip()
	if limit is not None and len(text) > limit:
		cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
		text = cut.rstrip(" ,;:.-") + "…"
	return text

def _is_web_url(url: Any) -> bool:
	if not isinstance(url, str):
		return False
	parts = urlsplit(url)
	return parts.scheme in ("http", "https") and bool(parts.netloc)

def _picture_url(entry: Mapping[str, Any]) -> str|None:
	"""A story's picture: what the feed marks as one (media content or thumbnail, an image enclosure), else the first picture in its text."""
	for key in ("media_content", "media_thumbnail"):
		for media in entry.get(key) or []:
			kind = str(media.get("type") or media.get("medium") or "image")
			if kind.startswith("image") and _is_web_url(media.get("url")):
				return media["url"]
	for link in entry.get("links") or []:
		if link.get("rel") == "enclosure" and str(link.get("type") or "").startswith("image") and _is_web_url(link.get("href")):
			return link["href"]
	body = entry.get("summary") or ((entry.get("content") or [{}])[0].get("value")) or ""
	found = _IMG_SRC.search(body) if isinstance(body, str) else None
	return found.group(1) if found and _is_web_url(found.group(1)) else None

def _published(entry: Mapping[str, Any]) -> str:
	stamp = entry.get("published_parsed") or entry.get("updated_parsed")
	if not stamp:
		return ""
	when = datetime(*stamp[:6])
	return f"{when:%b} {when.day}, {when.year}"

def parse_stories(content: bytes, feed_name: str) -> list[dict]:
	"""
	The stories of an RSS or Atom document, newest first as the feed lists them: `{ feed, feed_title, title, summary, published, picture_url }`.
	A document that is no feed (an HTML page from a cookie wall or a moved feed parses as an empty one) is a RuntimeError.
	"""
	feed = feedparser.parse(content)
	if not feed.entries:
		# `version` is empty when the document is no feed at all (a cookie wall's HTML page, a moved feed's notice)
		raise RuntimeError("The feed has no entries." if feed.get("version") else "The response is not a feed.")
	feed_title = plain_text(feed.feed.get("title"))
	stories = []
	for entry in feed.entries[:MAX_STORIES]:
		body = entry.get("summary") or ((entry.get("content") or [{}])[0].get("value")) or ""
		stories.append({
			"feed": feed_name,
			"feed_title": feed_title,
			"title": plain_text(entry.get("title")) or "(untitled)",
			"summary": plain_text(body, SUMMARY_CHARS),
			"published": _published(entry),
			"picture_url": _picture_url(entry),
		})
	return stories

def _picture_data_uri(buffer: io.BytesIO) -> str:
	with Image.open(buffer) as opened:
		img = to_rgb(opened)
		img.thumbnail(PICTURE_BOX, Image.Resampling.LANCZOS)
		out = io.BytesIO()
		img.save(out, "JPEG", quality=82)
	return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	rs = RenderSession(stm, render_dir, "rss.html", theme)
	image = rs.render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=template_params["story"]["title"])

class RssAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""A feed as a slide show: `open_async` lists the stories, `render_async` draws one of them as a page."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	@staticmethod
	def _feed_url(dsec: DataSourceExecutionContext, name: str) -> str:
		"""The address of the named feed, from the feeds this data source keeps in its settings (the task stores only the name)."""
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		for entry in (settings or {}).get("feeds") or []:
			if isinstance(entry, dict) and entry.get("name") == name:
				if _is_web_url(entry.get("url")):
					return entry["url"]
				raise PermanentError(f"The feed '{name}' has no http or https address.")
		# nothing to retry: the feed was renamed or removed from the settings
		raise PermanentError(f"The feed '{name}' is not in the RSS Feed settings.")

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		name = params.get("feed")
		if not name:
			raise PermanentError("The 'feed' setting is required for the RSS Feed data source.")
		url = self._feed_url(dsec, name)
		# the feed's own body is kept briefly (its headers and validators decide); its pictures for a day
		buffer = await download_for(dsec, url, default_hours=DEFAULT_FEED_HOURS, headers=HEADERS, max_bytes=MAX_FEED_BYTES, scope=f"feed:{name}", setting="feedCacheHours")
		stories = parse_stories(buffer.getvalue(), name)
		# the list was just loaded: the pictures of stories that dropped out of the feed go now (this feed's only: another feed's stay)
		dscm = dsec.provider.get_service(DatasourceConfigurationManager)
		if isinstance(dscm, DatasourceConfigurationManager):
			retain(dscm, f"pictures:{name}", [str(s["picture_url"]) for s in stories if s.get("picture_url")])
		return stories

	async def _picture(self, dsec: DataSourceExecutionContext, story: Mapping[str, Any]) -> str|None:
		"""The story's picture as an embedded image (the page then needs no network), or None: a picture that fails is left out, not the story."""
		url = story.get("picture_url")
		if not url:
			return None
		try:
			buffer = await download_for(dsec, url, default_hours=DEFAULT_PICTURE_HOURS, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_PICTURE_BYTES, scope=f"pictures:{story.get('feed')}")
			return await asyncio.to_thread(_picture_data_uri, buffer)
		except Exception as ex:
			# the address of a picture can carry a key: say only what kind of failure it was
			self.logger.warning(f"'{self.name}' a picture could not be used ({type(ex).__name__}).")
			return None

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if state is None:
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("rss")
		_, display_config = scm.open("display").get()
		if display_config is None:
			raise ValueError("Display settings is None")
		picture = await self._picture(dsec, state) if params.get("includeImages") is True else None
		template_params = {
			"heading": params.get("title") or state.get("feed") or state.get("feed_title") or "RSS Feed",
			"story": { **state, "picture": picture },
			"font_scale": FONT_SCALES.get(str(params.get("fontSize")), 1.0),
			"settings": params,
		}
		# Chromium is slow and blocking: keep it off the event loop
		return await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), template_params, current_inputs(scm))
