import asyncio
import base64
import io
from typing import Any, Mapping

from PIL import Image, ImageFont

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs, current_typography
from ...plugins.plugin_base import RenderSession
from ...utils.image_utils import to_rgb
from ..content_cache import download_for, retain
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from .strips import strips_async

# a strip does not change once published: its picture is kept for a day (the site's headers can shorten that)
DEFAULT_CONTENT_HOURS = 24.0
# the page's line height (comic.html uses it too): what the words above and below the strip take is counted with it
LINE_HEIGHT = 1.2
# the words may take at most this much of the page; past it the caption goes, then the title, never the strip
MOST_FOR_WORDS = 0.75

def line_count(text: str, font: ImageFont.FreeTypeFont, width: int) -> int:
	"""How many lines `text` takes at `width`, breaking between words (a word wider than the line is a line of its own)."""
	lines, current = 0, ""
	for word in text.split():
		candidate = f"{current} {word}" if current else word
		if current and font.getlength(candidate) > width:
			lines += 1
			current = word
		else:
			current = candidate
	return lines + (1 if current else 0)

def words_that_fit(title: str, caption: str, font: ImageFont.FreeTypeFont, size: tuple[int, int]) -> tuple[str, str]:
	"""The title and caption to print with the strip: a caption (SMBC's hovertext can be long) that would leave the strip less than a quarter of the page is left out, then the title."""
	width, height = size
	room = height * MOST_FOR_WORDS
	def tall(text: str) -> float:
		return line_count(text, font, width) * font.size * LINE_HEIGHT if text else 0.0
	if tall(title) + tall(caption) > room:
		caption = ""
	if tall(title) > room:
		title = ""
	return title, caption

def strip_data_uri(buffer: io.BytesIO, size: tuple[int, int]) -> str:
	"""The strip as an embedded PNG (line art stays sharp), no larger than the page; a transparent strip is put on white paper."""
	with Image.open(buffer) as opened:
		img = to_rgb(opened)
		img.thumbnail(size, Image.Resampling.LANCZOS)
		out = io.BytesIO()
		img.save(out, "PNG", optimize=True)
	return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")

def render_page(stm: StaticConfigurationManager, render_dir: str, size: tuple[int, int], params: dict, theme: ThemeInputs | None = None) -> Image.Image | None:
	"""Blocking: Chromium draws the page."""
	return RenderSession(stm, render_dir, "comic.html", theme).render(size, params)

class ComicFeedAsync(DataSource, MediaListAsync, MediaRenderAsync):
	"""A web comic as a slide show: `open_async` lists the strips of its feed, `render_async` prints one on a page."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		name = params.get("comic")
		strips = await strips_async(str(name), dsec)
		# the list was just loaded: the pictures of strips that left this comic's feed go now (this comic's only)
		dscm = dsec.provider.get_service(DatasourceConfigurationManager)
		if isinstance(dscm, DatasourceConfigurationManager):
			retain(dscm, f"pictures:{name}", [str(s["image_url"]) for s in strips])
		return strips
	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if state is None:
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		_, display_settings = scm.open("display").get()
		if display_settings is None:
			raise ValueError("display settings is None")
		size = target_dimensions(dsec, display_settings)
		# a strip does not change once published: kept for a day, and what left the feed goes (per comic)
		buffer = await download_for(dsec, state["image_url"], default_hours=DEFAULT_CONTENT_HOURS, scope=f"pictures:{state.get('name', '')}")
		page = await self.page_params(stm, scm, params, state, size, buffer)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("comic")
		image = await asyncio.to_thread(render_page, stm, render_dir, size, page, current_inputs(scm))
		return None if image is None else MediaRenderResult(image=image, title=state.get("title") or "Comic")
	@staticmethod
	async def page_params(stm: StaticConfigurationManager, scm: SettingsConfigurationManager, params: Mapping[str, Any], state: Mapping[str, Any], size: tuple[int, int], buffer: io.BytesIO) -> dict:
		"""What comic.html is given: the strip, and the title and caption that fit at the task's text size (none when Show Caption is off)."""
		typography = current_typography(scm)
		text_px = max(1, round(int(params.get("fontSize") or 12) * typography.scale))
		# titleCaption is a boolean setting (older documents may hold the string "true")
		title, caption = "", ""
		if params.get("titleCaption") in (True, "true"):
			title, caption = str(state.get("title") or ""), str(state.get("caption") or "")
			font = stm.get_font(typography.body, font_size=text_px)
			if font is not None:
				title, caption = words_that_fit(title, caption, font, size)
		strip = await asyncio.to_thread(strip_data_uri, buffer, size)
		# `settings` is the task's: the template may read it
		return { "strip": strip, "title": title, "caption": caption, "text_px": text_px, "line_height": LINE_HEIGHT, "settings": dict(params) }
