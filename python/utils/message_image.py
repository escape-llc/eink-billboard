"""
The page for a message someone pushed to the panel (`POST /api/display/message`): an optional title and the text, in the theme of the other pages (static/render/message.html extends plugin.html).
The size of the type is chosen here from how much there is to say (the page cannot run a script to fit it), so a short word is big and a paragraph still fits. Blocking (Chromium).
When the themed page cannot be made (no `stm`, or the browser is what failed) a plain page is drawn, so the message is still shown.
"""
import logging
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import ThemeInputs
from ..plugins.plugin_base import RenderSession

logger = logging.getLogger(__name__)

MAX_TITLE_CHARACTERS = 80
MAX_TEXT_CHARACTERS = 1000

def text_size(dimensions: tuple[int, int], title: str, text: str) -> int:
	"""The size of the body text in pixels (the title is half as big again): a fraction of the page's height, smaller the more there is to say."""
	width, height = dimensions
	characters = len(text) + (len(title) * 2 if title else 0)
	lines = text.count("\n") + 1
	if characters <= 24 and lines == 1:
		fraction = 0.16
	elif characters <= 80 and lines <= 2:
		fraction = 0.10
	elif characters <= 200 and lines <= 5:
		fraction = 0.075
	elif characters <= 450 and lines <= 10:
		fraction = 0.055
	else:
		fraction = 0.04
	# a narrow page (a portrait panel) has less room across: the type shrinks with it
	return max(10, int(min(height * fraction, width * fraction * 1.2)))

def render_message_image(stm: StaticConfigurationManager|None, dimensions: tuple[int, int], title: str, text: str, theme: ThemeInputs|None = None) -> Image.Image:
	"""The message as an image of `dimensions` (`title` may be empty)."""
	if stm is not None:
		try:
			render_dir = os.path.join(stm.ROOT_PATH, "render")
			page = { "settings": {}, "title": title, "text": text, "text_px": text_size(dimensions, title, text) }
			image = RenderSession(stm, render_dir, "message.html", theme).render(dimensions, page)
			if image is not None:
				return image
		except Exception as e:
			logger.warning(f"The themed message page could not be rendered, drawing the plain one: {type(e).__name__}")
	return plain_message_image(dimensions, title, text)

def plain_message_image(dimensions: tuple[int, int], title: str, text: str) -> Image.Image:
	"""A black-on-white page drawn with PIL alone: no browser, no fonts, nothing that can fail the way the themed page can."""
	width, height = dimensions
	image = Image.new("RGB", (width, height), "white")
	draw = ImageDraw.Draw(image)
	# no antialiasing: a grey edge on a letter is dithered on the panel
	draw.fontmode = "1"
	size = max(10, text_size(dimensions, title, text) * 3 // 4)
	font = ImageFont.load_default(size=size)
	margin = max(8, width // 20)
	columns = max(8, (width - margin * 2) // max(1, int(size * 0.55)))
	y = margin
	for part in [title, *text.split("\n")] if title else text.split("\n"):
		for line in textwrap.wrap(part, columns) or [""]:
			if y + size > height - margin:
				return image
			draw.text((margin, y), line, font=font, fill="black")
			y += int(size * 1.3)
	return image
