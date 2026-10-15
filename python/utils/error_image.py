import logging
from dataclasses import dataclass
import os
import re
import textwrap

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import ThemeInputs
from ..plugins.plugin_base import PermanentError, RenderSession

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class WebAddress:
	"""Where people open the web app (the setup address: --public-url, else the device's own), a service the layers read so their error pages can say where to fix things."""
	url: str

ERROR_HEADING = "CANNOT SHOW THIS"

# the error page wears the device theme like the plugins' pages (static/render: plugin.html extended by error.html, which carries its own CSS; plugin.css and themes.css are shared)

def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
	return ImageFont.load_default(size=size)

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|key|appid|token|secret|password|passwd|authorization|bearer)\b(\s*[=:]\s*|\s+)\S+")
MAX_REASON = 160

def _hint(status: int) -> str:
	if status in (401, 403):
		return " Check the API key or the sign-in in the settings."
	if status == 404:
		return " Check the address in the settings."
	if status == 429:
		return " Too many requests; it will work again later."
	if status >= 500:
		return " The service has a problem; try again later."
	return ""

def safe_reason(error: BaseException) -> str:
	"""
	What the panel and the telemetry say about a failure, so the user knows what to fix: our own message when the error is one of ours (`PermanentError`),
	a sentence of our own for the usual network failures (the status the server answered, a timeout, no connection), and otherwise the type's name with the
	exception's text **cleaned**: addresses become `<address>` and anything after `key=`, `token`, `password`... is removed, since the text can hold a URL with a key in it
	and the panel is visible to anyone in the room. The full text goes to the log only.
	"""
	if isinstance(error, PermanentError):
		return str(error)
	if isinstance(error, httpx.HTTPStatusError):
		code = error.response.status_code
		return f"The server answered {code} {error.response.reason_phrase}.".replace("  ", " ") + _hint(code)
	if isinstance(error, httpx.TimeoutException):
		return "The server did not answer in time. Check the address and the network."
	if isinstance(error, (httpx.ConnectError, ConnectionError)):
		return "Could not connect to the server. Check the address and the network."
	if isinstance(error, KeyError) and error.args:
		return f"The data had no '{_clean(str(error.args[0]))}' field."
	text = _clean(str(error))
	name = type(error).__name__
	return f"{name}: {text}" if text else name

MAX_DETAIL = 2000

def error_detail(error: BaseException) -> str:
	"""The exception in full (type and text, as the log has it). It can hold an address with a key: only for a viewer on the device itself (see the telemetry route), never the panel or a remote page."""
	text = f"{type(error).__name__}: {error}".strip()
	return text if len(text) <= MAX_DETAIL else text[:MAX_DETAIL - 1] + "…"

def _clean(text: str) -> str:
	text = _URL.sub("<address>", " ".join(text.split()))
	text = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}<hidden>", text)
	return text if len(text) <= MAX_REASON else text[:MAX_REASON - 1] + "…"

def render_error_image(stm: StaticConfigurationManager|None, dimensions: tuple[int, int], title: str, lines: list[str], theme: ThemeInputs|None = None, compact: bool = False,
	address: str|None = None, heading: str = ERROR_HEADING, hint: bool = True) -> Image.Image:
	"""
	The page for a slot that failed: what failed (`title`) and why (`lines`), in the theme of the other pages (blocking: Chromium).
	`compact` is the layout for a small box (an overlay zone): the heading and the title, then the reason if it fits; nothing wraps, the rest is clipped.
	When the themed page cannot be made (no `stm`, or the browser is what failed) a plain page is drawn instead, so the user still sees the error.
	It holds nothing that changes (no clock): the same failure gives the same pixels, and the display can tell nothing needs redrawing.
	The page carries the logo (not in the compact layout) and, with `address`, says where the web app is; `heading` and `hint` change it for a page that is not an error (the setup page).
	"""
	if stm is not None:
		try:
			render_dir = os.path.join(stm.ROOT_PATH, "render")
			hint_text = (f"Check the settings in the web app at {address}" if address else "Check the settings in the web app") if hint else None
			page = { "settings": {}, "title": title, "lines": lines, "compact": compact, "heading": heading, "hint": hint_text, "logo": stm.image_data_url("logo.png") }
			image = RenderSession(stm, render_dir, "error.html", theme).render(dimensions, page)
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
