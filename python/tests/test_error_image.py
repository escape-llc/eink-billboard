import os
import shutil
import unittest
from unittest import mock

from ..model.configuration_manager import StaticConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..utils import error_image
from ..utils.error_image import plain_error_image, render_error_image, safe_reason

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
HAVE_CHROME = shutil.which("chromium-headless-shell") is not None

class PlainErrorImageTests(unittest.TestCase):
	def test_same_failure_gives_the_same_pixels(self):
		first = plain_error_image((800, 480), "Morning slides", ["folder: Required"])
		second = plain_error_image((800, 480), "Morning slides", ["folder: Required"])
		self.assertEqual(first.size, (800, 480))
		self.assertEqual(first.tobytes(), second.tobytes())

	def test_a_different_failure_looks_different(self):
		first = plain_error_image((800, 480), "Morning slides", ["folder: Required"])
		other = plain_error_image((800, 480), "Morning slides", ["ConnectError"])
		self.assertNotEqual(first.tobytes(), other.tobytes())

	def test_fits_any_panel_even_with_far_too_much_text(self):
		for size in ((800, 480), (400, 300), (1872, 1404)):
			with self.subTest(size):
				image = plain_error_image(size, "T" * 300, ["line"] * 60)
				self.assertEqual(image.size, size)
				self.assertNotEqual(image.convert("L").getextrema(), (255, 255))

	def test_the_reason_never_carries_a_url_or_other_exception_text(self):
		self.assertEqual(safe_reason(ConnectionError("https://api.example/x?key=SECRET failed")), "ConnectionError")
		self.assertEqual(safe_reason(PermanentError("folder: Required")), "folder: Required")

class ThemedErrorImageTests(unittest.TestCase):
	def setUp(self):
		self.stm = StaticConfigurationManager(os.path.abspath(STATIC))

	def test_the_page_extends_the_plugin_page_and_uses_the_theme_classes(self):
		with open(os.path.join(STATIC, "render", "error.html"), encoding="utf-8") as f:
			html = f.read()
		self.assertIn('extends "plugin.html"', html)
		for theme_class in ("text-primary", "text-secondary-1", "text-secondary-2"):
			self.assertIn(theme_class, html)

	@unittest.skipUnless(HAVE_CHROME, "needs chromium-headless-shell on PATH")
	def test_renders_through_the_browser_with_the_theme_and_is_repeatable(self):
		first = render_error_image(self.stm, (800, 480), "Morning slides", ["folder: Required"])
		second = render_error_image(self.stm, (800, 480), "Morning slides", ["folder: Required"])
		self.assertEqual(first.size, (800, 480))
		self.assertEqual(first.tobytes(), second.tobytes())
		# the theme's background, not the plain page's white
		self.assertNotEqual(first.convert("RGB").getpixel((5, 5)), (255, 255, 255))
		self.assertNotEqual(first.tobytes(), plain_error_image((800, 480), "Morning slides", ["folder: Required"]).convert(first.mode).tobytes())

	@unittest.skipUnless(HAVE_CHROME, "needs chromium-headless-shell on PATH")
	def test_the_compact_page_fits_an_overlay_zone(self):
		image = render_error_image(self.stm, (246, 96), "Today", ["PermanentError: a very long reason that cannot fit on one line of a small box"], None, True)
		self.assertEqual(image.size, (246, 96))
		self.assertNotEqual(image.tobytes(), plain_error_image((246, 96), "Today", ["x"], True).convert(image.mode).tobytes())

	def test_the_compact_plain_page_is_the_zone_size(self):
		image = plain_error_image((246, 96), "Today", ["a reason"], True)
		self.assertEqual(image.size, (246, 96))
		# drawn, not blank
		self.assertIsNotNone(image.convert("L").point(lambda v: 255 - v).getbbox())

	def test_falls_back_to_the_plain_page_when_the_browser_fails(self):
		with mock.patch.object(error_image, "RenderSession", side_effect=RuntimeError("no browser")):
			image = render_error_image(self.stm, (800, 480), "T", ["x"])
		self.assertEqual(image.tobytes(), plain_error_image((800, 480), "T", ["x"]).tobytes())

	def test_without_static_resources_it_is_the_plain_page(self):
		image = render_error_image(None, (800, 480), "T", ["x"])
		self.assertEqual(image.tobytes(), plain_error_image((800, 480), "T", ["x"]).tobytes())
