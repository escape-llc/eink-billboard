"""
The digital clock: HH:MM in seven-segment digits (DSEG7), as large as the widest time (`88:88`) lets it be.

The unlit segments may be drawn behind as a thin outline in a lighter ink, never a faded fill: a panel dithers anything that is not one of its inks.
"""
from datetime import datetime

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ...model.configuration_manager import StaticConfigurationManager
from ...model.theme import Palette

UNLIT = ("outline", "none")
WIDEST = "88:88"
BLANK = "!"  # DSEG7's blank digit: as wide as an 8, so a one-digit hour keeps the colon in its place
WIDTH_FILL = 0.9
HEIGHT_FILL = 0.6
MIN_LABEL_PX = 13  # AM / PM (plugin.css: --min-label)


def digital_text(t: datetime, twelve_hour: bool) -> tuple[str, str]:
	"""The digits and the AM / PM (empty on a 24-hour clock) at `t`."""
	if not twelve_hour:
		return f"{t.hour:02d}:{t.minute:02d}", ""
	hour = t.hour % 12 or 12
	return f"{hour:{BLANK}>2}:{t.minute:02d}", "AM" if t.hour < 12 else "PM"


def _mask(dimensions: tuple[int, int], centre: tuple[float, float], text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
	"""Where `text` is drawn, centred on `centre`: 255 or 0, nothing between."""
	mask = Image.new("L", dimensions, 0)
	draw = ImageDraw.Draw(mask)
	draw.fontmode = "1"
	draw.text(centre, text, font=font, anchor="mm", fill=255)
	return mask


def draw_digital(t: datetime, twelve_hour: bool, unlit: str, dimensions: tuple[int, int], palette: Palette, stm: StaticConfigurationManager, family: str) -> Image.Image:
	"""The page: the time centred in the main text ink, AM / PM under its right edge in the first secondary ink."""
	width, height = dimensions
	# DSEG7's box is the same for every time, so the size is found once from the widest
	probe = 100
	left, top, right, bottom = stm.get_font("DSEG7", probe, "bold").getbbox(WIDEST)
	size = max(1, int(probe * min(width * WIDTH_FILL / (right - left), height * HEIGHT_FILL / (bottom - top))))
	digits_font = stm.get_font("DSEG7", size, "bold")
	digits, suffix = digital_text(t, twelve_hour)
	image = Image.new("RGB", dimensions, palette.rgb("bg_page"))
	centre = (width / 2, height / 2)
	lit = _mask(dimensions, centre, digits, digits_font)
	if unlit == "outline":
		# a one-pixel ring around every segment (PIL's text stroke is antialiased whatever the font mode, so the ring is made from the bare mask)
		segments = _mask(dimensions, centre, WIDEST, digits_font)
		image.paste(palette.rgb("text_secondary_2"), mask=ImageChops.subtract(segments.filter(ImageFilter.MaxFilter(3)), segments))
		# a lit segment covers its ring too, so no rim of the lighter ink shows around it
		lit = lit.filter(ImageFilter.MaxFilter(3))
	image.paste(palette.rgb("text_primary"), mask=lit)
	draw = ImageDraw.Draw(image)
	# no antialiasing: a grey edge on a letter is dithered on the panel
	draw.fontmode = "1"
	if suffix:
		box = draw.textbbox(centre, WIDEST, font=digits_font, anchor="mm")
		label = stm.get_font(family, max(MIN_LABEL_PX, size // 5), "bold")
		draw.text((box[2], box[3] + size // 8), suffix, font=label, anchor="ra", fill=palette.rgb("text_secondary_1"))
	return image
