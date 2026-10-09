import logging
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import ThemeInputs
from ..plugins.plugin_base import PermanentError, RenderSession
from .file_utils import path_to_file_url

logger = logging.getLogger(__name__)

# the error page wears the device theme like the plugins' pages (static/render: plugin.html extended by error.html, plugin.css, themes.css, error.css)

def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
	return ImageFont.load_default(size=size)

def safe_reason(error: BaseException) -> str:
	"""
	What the panel may say about a failure: our own message when the error is one of ours (`PermanentError`), otherwise only the type's name.
	An exception's text can hold a URL with a key in it, and the panel is visible to anyone in the room.
	"""
	if isinstance(error, PermanentError):
		return str(error)
	return type(error).__name__

def render_error_image(stm: StaticConfigurationManager|None, dimensions: tuple[int, int], title: str, lines: list[str], theme: ThemeInputs|None = None, compact: bool = False) -> Image.Image:
	"""
	The page for a slot that failed: what failed (`title`) and why (`lines`), in the theme of the other pages (blocking: Chromium).
	`compact` is the layout for a small box (an overlay zone): the heading and the title, then the reason if it fits; nothing wraps, the rest is clipped.
	When the themed page cannot be made (no `stm`, or the browser is what failed) a plain page is drawn instead, so the user still sees the error.
	It holds nothing that changes (no clock): the same failure gives the same pixels, and the display can tell nothing needs redrawing.
	"""
	if stm is not None:
		try:
			render_dir = os.path.join(stm.ROOT_PATH, "render")
			css = path_to_file_url(os.path.join(render_dir, "error.css"))
			image = RenderSession(stm, render_dir, "error.html", css, theme).render(dimensions, { "settings": {}, "title": title, "lines": lines, "compact": compact })
			if image is not None:
				return image
		except Exception as e:
			logger.warning(f"The themed error page could not be rendered, drawing the plain one: {type(e).__name__}")
	return plain_error_image(dimensions, title, lines, compact)

def plain_error_image(dimensions: tuple[int, int], title: str, lines: list[str], compact: bool = False) -> Image.Image:
	"""A black-on-white page drawn with PIL alone: no browser, no fonts, nothing that can fail the way the themed page can."""
	width, height = dimensions
	image = Image.new("RGB", (width, height), "white")
	draw = ImageDraw.Draw(image)
	if compact:
		# a small box: the heading and the title, one line each (and the reason if there is room), clipped at the edge
		size = max(8, height // 4)
		font = _font(size)
		pad = max(2, height // 12)
		draw.rectangle((0, 0, width - 1, height - 1), outline="black", width=max(1, height // 40))
		y = pad
		for text in ["! Cannot show this", title, *lines]:
			if y + size > height - pad:
				break
			draw.text((pad * 2, y), text, font=font, fill="black")
			y += int(size * 1.25)
		return image
	margin = max(8, width // 40)
	draw.rectangle((margin // 2, margin // 2, width - margin // 2 - 1, height - margin // 2 - 1), outline="black", width=max(2, width // 200))
	heading_size = max(14, height // 12)
	body_size = max(12, height // 20)
	heading_font = _font(heading_size)
	body_font = _font(body_size)
	y = margin * 2
	draw.text((margin * 2, y), "! Cannot show this", font=heading_font, fill="black")
	y += int(heading_size * 1.6)
	body_width = max(10, (width - margin * 4) // max(1, int(body_size * 0.55)))
	for text in [title, *lines]:
		for part in textwrap.wrap(text, body_width) or [""]:
			if y + body_size > height - margin * 2:
				return image
			draw.text((margin * 2, y), part, font=body_font, fill="black")
			y += int(body_size * 1.4)
		y += int(body_size * 0.4)
	return image
