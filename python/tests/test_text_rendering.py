"""Text reaches the panel as solid inks (#684): the renderer draws it without antialiasing and without subpixel colour, so a letter has no grey or coloured fringe for the quantizer to dither."""
import shutil
import sys
import unittest

from ..datasources.overlay_text import OverlayIcon, render_overlay
from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import DEFAULT_INPUTS
from ..utils.error_image import plain_error_image
from ..utils.image_utils import chrome_command, render_html_arglist
from ..utils.message_image import plain_message_image
from .test_datasource_fixes import STATIC

CHROME = chrome_command()
HAVE_CHROME = shutil.which(CHROME) is not None

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; background: #ffffff; }
p { margin: 6px 12px; font-family: sans-serif; }
.black { color: #000000; font-size: 18px; }
.red { color: #ff0000; font-size: 18px; }
.big { color: #000000; font-size: 40px; font-weight: bold; }
.small { color: #0000ff; font-size: 12px; }
</style></head><body>
<p class="big">Heading 0123456789</p>
<p class="black">The quick brown fox jumps over the lazy dog. Sphinx of black quartz, judge my vow.</p>
<p class="red">The quick brown fox jumps over the lazy dog. Sphinx of black quartz, judge my vow.</p>
<p class="small">The quick brown fox jumps over the lazy dog (blue, small).</p>
</body></html>"""

# fontconfig is Linux's: the browser on Windows draws its own way, and the panel never runs there
@unittest.skipUnless(HAVE_CHROME and sys.platform != "win32", f"needs {CHROME} on PATH, on Linux (see AGENTS.md, Test environment)")
class TestTextIsSolid(unittest.TestCase):
	def test_every_pixel_is_one_of_the_inks_the_page_used(self):
		image = render_html_arglist(PAGE, ["--window-size=800,480"])
		self.assertIsNotNone(image, "Failed to render image")
		assert image is not None
		colors = { color for _, color in (image.convert("RGB").getcolors(maxcolors=1 << 20) or []) }
		self.assertEqual(colors - { (255, 255, 255), (0, 0, 0), (255, 0, 0), (0, 0, 255) }, set(), "text has fringe pixels that are not a solid ink")
		# the text really is there, in each colour
		self.assertTrue({ (0, 0, 0), (255, 0, 0), (0, 0, 255) } <= colors)

@unittest.skipUnless(HAVE_CHROME and sys.platform != "win32", f"needs {CHROME} on PATH, on Linux (see AGENTS.md, Test environment)")
class TestOverlayIsBinary(unittest.TestCase):
	"""An overlay (text, its outline and a line icon on a transparent page) is composited onto a picture: a pixel is either there or not, so the quantizer never has a blend to dither."""
	def test_every_pixel_is_transparent_or_opaque_and_the_opaque_ones_are_few_flat_colors(self):
		icon = OverlayIcon('<circle cx="32" cy="32" r="18"/><path d="M8 54 L56 54"/><path d="M20 20 L44 44"/>', 4)
		image = render_overlay(StaticConfigurationManager(STATIC), DEFAULT_INPUTS, (400, 120), [[("Sunny ", "text-primary"), ("21", "text-secondary-1")], [("Wind 5 m/s", "text-secondary-2")]], 1.0, icon=icon)
		pixels = image.convert("RGBA").getcolors(maxcolors=1 << 20) or []
		partial = sum(n for n, (_, _, _, a) in pixels if 0 < a < 255)
		self.assertEqual(partial, 0, "pixels with partial alpha are blended with the picture under them")
		opaque = { (r, g, b) for _, (r, g, b, a) in pixels if a == 255 }
		# the outline and three roles (text, text, icon): one flat color each, with no shades between
		self.assertLessEqual(len(opaque), 4, f"{len(opaque)} opaque colors")

class TestPilTextIsSolid(unittest.TestCase):
	"""The pages drawn with PIL alone (the fallbacks when the browser fails) have black text on white and nothing between."""
	def test_the_plain_message_page(self):
		image = plain_message_image((800, 480), "A title", "Some words that fill a few lines of the plain page, drawn with PIL alone. " * 3)
		self.assertEqual({ color for _, color in image.convert("RGB").getcolors(maxcolors=1 << 20) or [] }, { (255, 255, 255), (0, 0, 0) })

	def test_the_plain_error_page(self):
		for compact in (False, True):
			with self.subTest(compact=compact):
				image = plain_error_image((800, 480), "Failed", ["The reason it failed, in a few words.", "A second line."], compact)
				self.assertEqual({ color for _, color in image.convert("RGB").getcolors(maxcolors=1 << 20) or [] }, { (255, 255, 255), (0, 0, 0) })

if __name__ == '__main__':
	unittest.main()
