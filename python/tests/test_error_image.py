import os
import shutil
import unittest
from unittest import mock

import httpx

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import inputs_from
from ..plugins.plugin_base import PermanentError
from ..utils import error_image
from ..utils.image_utils import chrome_command
from ..utils.error_image import plain_error_image, render_error_image, safe_reason

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
HAVE_CHROME = shutil.which(chrome_command()) is not None

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
		self.assertEqual(safe_reason(ConnectionError("https://api.example/x?key=SECRET failed")), "Could not connect to the server. Check the address and the network.")
		text = safe_reason(RuntimeError("bad reply from https://api.example/x?appid=SECRET with token abc123 and key=SECRET2"))
		self.assertEqual(text, "RuntimeError: bad reply from <address> with token <hidden> and key=<hidden>")
		self.assertIn("RuntimeError: " + "x" * 10, safe_reason(RuntimeError("x" * 500)))
		self.assertLessEqual(len(safe_reason(RuntimeError("x" * 500))), 180)
		response = httpx.Response(401, request=httpx.Request("GET", "https://api.example/x?appid=SECRET"))
		text = safe_reason(httpx.HTTPStatusError("boom https://api.example/x?appid=SECRET", request=response.request, response=response))
		self.assertEqual(text, "The server answered 401 Unauthorized. Check the API key or the sign-in in the settings.")
		self.assertEqual(safe_reason(KeyError("temp")), "The data had no 'temp' field.")
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

	@unittest.skipUnless(HAVE_CHROME, "needs the headless browser (EINK_CHROME, or chromium-headless-shell on PATH)")
	def test_renders_through_the_browser_with_the_theme_and_is_repeatable(self):
		warm = inputs_from({ "preset": "warm" })
		first = render_error_image(self.stm, (800, 480), "Morning slides", ["folder: Required"], warm)
		second = render_error_image(self.stm, (800, 480), "Morning slides", ["folder: Required"], warm)
		self.assertEqual(first.size, (800, 480))
		self.assertEqual(first.tobytes(), second.tobytes())
		# the page is white by default and black in dark mode
		self.assertEqual(render_error_image(self.stm, (800, 480), "Morning slides", ["folder: Required"]).convert("RGB").getpixel((5, 5)), (255, 255, 255))
		self.assertEqual(render_error_image(self.stm, (800, 480), "Morning slides", ["x"], inputs_from({ "background": "black" })).convert("RGB").getpixel((5, 5)), (0, 0, 0))
		self.assertNotEqual(first.tobytes(), plain_error_image((800, 480), "Morning slides", ["folder: Required"]).convert(first.mode).tobytes())

	@unittest.skipUnless(HAVE_CHROME, "needs the headless browser (EINK_CHROME, or chromium-headless-shell on PATH)")
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

class TestPageSecurityPolicy(unittest.TestCase):
	"""Chromium runs with --no-sandbox, so a rendered page may run no script and load nothing but our files (#190)."""
	def render(self, content: str):
		import tempfile
		from ..plugins.plugin_base import RenderSession
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		with open(os.path.join(tmp.name, "probe.html"), "w", encoding="utf-8") as f:
			f.write('{% extends "plugin.html" %}{% block content %}' + content + '{% endblock %}')
		return RenderSession(StaticConfigurationManager(STATIC), tmp.name, "probe.html", None)

	def test_every_page_carries_the_policy(self):
		html = self.render("<p>x</p>").env.get_template("probe.html").render({ "settings": {}, "style_sheets": [], "font_faces": [], "width": 10, "height": 10 })
		self.assertIn('http-equiv="Content-Security-Policy"', html)
		self.assertIn("default-src 'none'", html)
		self.assertNotIn("backgroundImageFile", html)

	@unittest.skipUnless(HAVE_CHROME, "needs chromium-headless-shell")
	def test_a_script_in_a_page_does_not_run_but_styles_still_apply(self):
		red_cover = "<script>var d=document.createElement('div');d.style='position:fixed;left:0;top:0;width:100%;height:100%;background:#f00';document.body.appendChild(d)</script>"
		green = '<div style="position:fixed;left:0;top:0;width:20px;height:20px;background:#00ff00"></div>'
		image = self.render(green + red_cover).render((200, 100), { "settings": {} })
		assert image is not None
		rgb = image.convert("RGB")
		self.assertEqual(rgb.getpixel((150, 80)), (255, 255, 255), "the script must not have drawn over the page")
		red, green_px, blue = rgb.getpixel((5, 5))
		self.assertGreater(green_px, 200)
		self.assertLess(red, 60)

class TestWhatThePageSays(unittest.TestCase):
	"""The page's words and picture: the logo, the web app's address, and the setup page's own heading (the page itself is rendered in Chromium by the tests above)."""
	def context_of(self, **kw) -> dict:
		seen: dict = {}
		session = mock.MagicMock()
		session.return_value.render.side_effect = lambda dims, page: seen.update(page) or None
		with mock.patch.object(error_image, "RenderSession", session):
			render_error_image(StaticConfigurationManager(STATIC), (800, 480), "Comic", ["Failed"], **kw)
		return seen

	def test_the_logo_is_ours_and_embedded(self):
		logo = StaticConfigurationManager(STATIC).image_data_url("logo.svg")
		assert logo is not None
		self.assertTrue(logo.startswith("data:image/svg+xml;base64,"))
		self.assertEqual(self.context_of()["logo"], logo)
		for name in ("../render/error.html", "logo.png", "nothing.png"):
			self.assertIsNone(StaticConfigurationManager(STATIC).image_data_url(name), name)

	def test_an_error_page_says_where_the_web_app_is(self):
		self.assertEqual(self.context_of(address="http://10.0.0.14:8080")["hint"], "Check the settings in the web app at http://10.0.0.14:8080")
		self.assertEqual(self.context_of()["hint"], "Check the settings in the web app")
		self.assertEqual(self.context_of()["heading"], "CANNOT SHOW THIS")

	def test_the_setup_page_is_not_an_error(self):
		page = self.context_of(heading="EINK BILLBOARD", hint=False)
		self.assertEqual((page["heading"], page["hint"]), ("EINK BILLBOARD", None))
