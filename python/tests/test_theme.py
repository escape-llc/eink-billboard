import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import DEFAULT_INPUTS, SCHEMES, Color, Palette, css_vars, current_inputs, current_palette, inputs_from, palette_of
from ..plugins import plugin_base
from ..plugins.plugin_base import RenderSession
from ..utils.image_utils import LINUX_CHROME_HEADLESS, WIN_CHROME_HEADLESS, os_type

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
THEMES_CSS = os.path.join(STATIC, "render", "themes.css")
CHROME = WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS
HAVE_CHROME = shutil.which(CHROME) is not None

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: open("theme").get() returns (rev, settings)."""
	def __init__(self, settings=None, error: Exception|None = None):
		self.settings = settings
		self.error = error
	def open(self, name):
		if self.error is not None:
			raise self.error
		assert name == "theme"
		return self
	def get(self):
		return ("rev", self.settings)

class TestSchemes(unittest.TestCase):
	def test_every_scheme_has_its_hue_offsets(self):
		expected = { "analogous": (-30, 30), "complementary": (180, 180), "split-complementary": (150, 210), "triadic": (120, 240), "tetradic": (90, 180), "monochrome": (0, 0) }
		self.assertEqual(SCHEMES, expected)
		for scheme, (h1, h2) in expected.items():
			with self.subTest(scheme=scheme):
				palette = palette_of(inputs_from({ "theme": scheme, "hue": 10, "saturation": 80, "lightness": 50 }))
				self.assertEqual(palette.text_primary.h, 10)
				self.assertEqual(palette.text_secondary_1.h, (10 + h1) % 360)
				self.assertEqual(palette.text_secondary_2.h, (10 + h2) % 360)

	def test_monochrome_uses_its_own_saturation(self):
		inputs = inputs_from({ "theme": "monochrome", "hue": 200, "saturation": 90, "lightness": 50 })
		self.assertEqual(inputs.saturation, 60)
		self.assertEqual(palette_of(inputs).bg_primary.s, 60)

	def test_roles_have_their_lightness(self):
		palette = palette_of(inputs_from({ "theme": "triadic", "hue": 0, "saturation": 100, "lightness": 40 }))
		self.assertEqual((palette.text_primary.l, palette.text_primary_light.l), (25, 90))
		self.assertEqual((palette.bg_primary.l, palette.bg_primary_accent.l, palette.bg_primary_dark.l), (80, 40, 20))

	def test_color_rgb(self):
		self.assertEqual(Color(0, 100, 50).rgb, (255, 0, 0))
		self.assertEqual(Color(120, 100, 50).rgb, (0, 255, 0))
		self.assertEqual(Color(600, 100, 50).rgb, (0, 0, 255))
		self.assertEqual(Color(0, 0, 100).rgb, (255, 255, 255))
		self.assertEqual(Color(-120, 100, 25).rgb, (0, 0, 128))

class TestSettings(unittest.TestCase):
	def test_bad_or_missing_values_fall_back_to_the_defaults_with_one_warning(self):
		with self.assertLogs("python.model.theme", level="WARNING") as logs:
			inputs = inputs_from({ "theme": "plaid", "hue": "red", "saturation": 120, "lightness": True })
		self.assertEqual(len(logs.output), 1)
		self.assertEqual(inputs, DEFAULT_INPUTS)

	def test_no_settings_is_the_default_theme(self):
		with self.assertLogs("python.model.theme", level="WARNING"):
			self.assertEqual(inputs_from(None), DEFAULT_INPUTS)
		self.assertEqual(current_inputs(None), DEFAULT_INPUTS)

	def test_current_theme_reads_the_settings_each_time(self):
		scm = FakeSettings({ "theme": "triadic", "hue": 30, "saturation": 50, "lightness": 60 })
		self.assertEqual(current_inputs(scm).scheme, "triadic")  # type: ignore[arg-type]
		scm.settings = { "theme": "analogous", "hue": 30, "saturation": 50, "lightness": 60 }
		self.assertEqual(current_palette(scm).text_secondary_1.h, 0)  # type: ignore[arg-type]

	def test_settings_that_cannot_be_read_give_the_default_theme(self):
		with self.assertLogs("python.model.theme", level="WARNING"):
			self.assertEqual(current_inputs(FakeSettings(error=OSError("disk"))), DEFAULT_INPUTS)  # type: ignore[arg-type]

class TestCss(unittest.TestCase):
	def test_css_vars_are_hsl_only(self):
		text = css_vars(inputs_from({ "theme": "split-complementary", "hue": 10, "saturation": 85, "lightness": 45 }))
		self.assertIn("--theme-base: hsl(10 85% 45%);", text)
		self.assertIn("--theme-h1-offset: 150;", text)
		self.assertIn("--theme-h2-offset: 210;", text)
		self.assertIn("--l-accent: 45%;", text)
		self.assertNotIn("rgb", text)
		self.assertNotIn("#", text)

	def test_every_themes_css_class_is_a_palette_role(self):
		with open(THEMES_CSS, encoding="utf-8") as f:
			css = f.read()
		classes = set(re.findall(r"^\.((?:text|bg)-[a-z0-9-]+)\s*\{", css, re.MULTILINE)) - { "bg-transparent" }
		self.assertEqual(classes, set(Palette.roles()))

	def test_themes_css_uses_hsl_only(self):
		with open(THEMES_CSS, encoding="utf-8") as f:
			css = f.read()
		self.assertNotRegex(css, r"rgb\(|#[0-9a-fA-F]{3,8}\b")

	def test_render_session_puts_the_theme_after_the_stylesheets(self):
		captured = {}
		def fake_render(html, args):
			captured["html"] = html
			return None
		inputs = inputs_from({ "theme": "triadic", "hue": 100, "saturation": 70, "lightness": 50 })
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}x{% endblock %}')
			with patch.object(plugin_base, "render_html_arglist", fake_render):
				RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", None, inputs).render((100, 50), { "settings": {} })
		html = captured["html"]
		self.assertIn(css_vars(inputs), html)
		self.assertGreater(html.index(css_vars(inputs)), html.index("themes.css"))
		self.assertNotIn("theme-triadic", html)

SWATCH = 20
@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestCssMatchesPython(unittest.TestCase):
	"""The CSS derivation (themes.css, in Chromium) and the Python one (Palette) give the same colors."""
	def _render(self, settings):
		roles = Palette.roles()
		swatches = "".join(
			f'<div class="{role}" style="position:absolute;left:{i * SWATCH}px;top:0;width:{SWATCH}px;height:{SWATCH}px;'
			f'{"background-color:currentColor" if role.startswith("text-") else ""}"></div>'
			for i, role in enumerate(roles))
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "swatches.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}' + swatches + '{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "swatches.html", None, inputs_from(settings)).render((len(roles) * SWATCH, 3 * SWATCH), { "settings": {} })
		self.assertIsNotNone(image)
		return roles, image.convert("RGB")

	def test_swatches(self):
		for settings in (
			{ "theme": "complementary", "hue": 220, "saturation": 80, "lightness": 50 },
			{ "theme": "split-complementary", "hue": 10, "saturation": 85, "lightness": 35 },
			{ "theme": "monochrome", "hue": 300, "saturation": 40, "lightness": 70 },
		):
			roles, image = self._render(settings)
			palette = palette_of(inputs_from(settings))
			for i, role in enumerate(roles):
				with self.subTest(theme=settings["theme"], role=role):
					got = image.getpixel((i * SWATCH + SWATCH // 2, SWATCH // 2))
					want = getattr(palette, role.replace("-", "_")).rgb
					self.assertTrue(all(abs(g - w) <= 1 for g, w in zip(got, want)), f"{role}: CSS {got}, Python {want}")

if __name__ == "__main__":
	unittest.main()
