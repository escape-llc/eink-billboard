"""
Image enhancement is the photograph's (#723): a data source that returns a photograph enhances it (`enhanced`) before it draws anything over it, and the display
task enhances nothing, so a page or a caption keeps its exact inks whatever layer it is shown on.
"""
import os
import unittest

from PIL import Image

from ..datasources import data_source
from ..datasources.data_source import enhanced
from .test_datasource_fixes import make_dsec

SETTINGS = { "orientation": "landscape", "imageSettings-brightness": 0.8, "imageSettings-contrast": 1.3 }
# the data sources that return a photograph: each calls `enhanced` on it (a page they draw themselves does not)
PHOTO_SOURCES = {
	os.path.join("ai", "generate.py"), os.path.join("comicvine_covers", "comicvine_covers.py"), os.path.join("image_folder", "image_folder.py"), os.path.join("image_url", "image_url.py"),
	os.path.join("museum_art", "museum_art.py"), os.path.join("nasa_apod", "nasa_apod.py"), os.path.join("newspaper", "newspaper.py"), os.path.join("wikipedia_potd", "wikipedia_potd.py"),
}

def gradient() -> Image.Image:
	image = Image.new("RGB", (64, 8))
	for x in range(64):
		for y in range(8):
			image.putpixel((x, y), (x * 4, x * 4, x * 4))
	return image

class TestEnhanced(unittest.TestCase):
	def test_a_photograph_is_changed_by_the_display_settings_and_left_alone_without_them(self):
		picture = gradient()
		# the fake settings of the data source tests carry only the orientation: nothing to apply
		self.assertEqual(list(enhanced(make_dsec(), picture).getdata()), list(picture.getdata()))

	def test_the_settings_brighten_or_darken_the_photograph(self):
		from unittest.mock import patch
		picture = gradient()
		with patch.object(data_source, "_read_display_settings", lambda dsec: SETTINGS):
			out = enhanced(make_dsec(), picture)
		self.assertNotEqual(list(out.getdata()), list(picture.getdata()))
		# brightness below 1 darkens a white pixel; black stays black
		self.assertLess(out.getpixel((63, 0))[0], picture.getpixel((63, 0))[0])
		self.assertEqual(out.getpixel((0, 0)), (0, 0, 0))

class TestWhoEnhances(unittest.TestCase):
	def test_the_display_task_enhances_nothing(self):
		root = os.path.dirname(os.path.dirname(__file__))
		with open(os.path.join(root, "task", "display.py"), encoding="utf-8") as f:
			self.assertNotIn("apply_image_enhancement", f.read())

	def test_the_sources_that_return_a_photograph_enhance_it(self):
		root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "datasources")
		found = set()
		for folder, _, files in os.walk(root):
			for name in files:
				if name.endswith(".py"):
					with open(os.path.join(folder, name), encoding="utf-8") as f:
						if "enhanced(" in f.read() and name != "data_source.py":
							found.add(os.path.relpath(os.path.join(folder, name), root))
		self.assertEqual(found, PHOTO_SOURCES, "a source that returns a photograph calls `enhanced(dsec, picture)` (add it here); a page a source draws never does")
