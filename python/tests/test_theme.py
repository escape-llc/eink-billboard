import os
import re
import shutil
import tempfile
import unittest
from typing import Any, cast
from unittest.mock import patch

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import DEFAULT_INPUTS, SCHEMES, Color, Palette, css_vars, current_inputs, current_palette, current_typography, inputs_from, palette_of
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

class TestTypography(unittest.TestCase):
	def test_the_defaults_are_jost_at_full_size(self):
		self.assertEqual((DEFAULT_INPUTS.font_body, DEFAULT_INPUTS.font_heading, DEFAULT_INPUTS.font_scale), ("Jost", "Jost", 1.0))
		# a document from before the fonts existed reads the same, and says nothing about it
		with self.assertNoLogs("python.model.theme", level="WARNING"):
			self.assertEqual(inputs_from({ "theme": "analogous", "hue": 10, "saturation": 50, "lightness": 50 }).font_body, "Jost")

	def test_choices_are_read_and_the_heading_follows_the_body_when_unset(self):
		inputs = inputs_from({ "fontBody": "Napoli", "fontHeading": None, "fontScale": 1.25 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("Napoli", "Napoli", 1.25))
		inputs = inputs_from({ "fontBody": "Jost", "fontHeading": "Dogica", "fontScale": 0.8 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("Jost", "Dogica", 0.8))

	def test_the_overlays_share_one_font_and_it_follows_the_heading_when_unset(self):
		self.assertEqual(inputs_from({ "fontBody": "Jost", "fontHeading": "Napoli" }).font_overlay, "Napoli")
		self.assertEqual(inputs_from({ "fontBody": "Napoli" }).font_overlay, "Napoli")
		self.assertEqual(inputs_from({ "fontBody": "Jost", "fontOverlay": "Dogica" }).font_overlay, "Dogica")
		self.assertEqual(inputs_from({ "fontBody": "Jost", "fontOverlay": "../x" }).font_overlay, "Jost")
		self.assertIn("--font-overlay: Dogica;", css_vars(inputs_from({ "fontOverlay": "Dogica" })))
		self.assertEqual(current_typography(FakeSettings({ "fontOverlay": "DS-Digital" })).overlay, "DS-Digital")  # type: ignore[arg-type]

	def test_only_the_fonts_we_ship_and_sizes_in_range_are_used(self):
		inputs = inputs_from({ "fontBody": "../../etc/passwd", "fontHeading": "Comic Sans", "fontScale": 9 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("Jost", "Jost", 1.0))
		self.assertEqual(inputs_from({ "fontScale": 0.5 }).font_scale, 1.0)
		self.assertEqual(inputs_from({ "fontScale": True }).font_scale, 1.0)

	def test_the_css_gets_the_variables_without_quotes(self):
		text = css_vars(inputs_from({ "fontBody": "DS-Digital", "fontHeading": "Napoli", "fontScale": 1.2 }))
		self.assertIn("--font-body: DS-Digital;", text)
		self.assertIn("--font-heading: Napoli;", text)
		self.assertIn("--font-scale: 1.2;", text)
		self.assertNotIn('"', text)

	def test_pil_code_reads_the_same_choice_each_time(self):
		scm = FakeSettings({ "fontBody": "Napoli", "fontScale": 1.2 })
		self.assertEqual(current_typography(cast(Any, scm)).body, "Napoli")
		scm.settings = { "fontBody": "Jost", "fontScale": 1.0 }
		self.assertEqual((current_typography(cast(Any, scm)).body, current_typography(cast(Any, scm)).scale), ("Jost", 1.0))
		self.assertEqual(current_typography(None).body, "Jost")

class TestBackground(unittest.TestCase):
	def test_the_page_is_white_unless_asked_otherwise(self):
		self.assertEqual(DEFAULT_INPUTS.background, "white")
		self.assertEqual(inputs_from({ "theme": "analogous", "hue": 10, "saturation": 50, "lightness": 50 }).background, "white")
		self.assertEqual(inputs_from({ "background": "plaid" }).background, "white")
		self.assertEqual(palette_of(DEFAULT_INPUTS).bg_page.rgb, (255, 255, 255))
		self.assertIn("--page-bg: hsl(0 0% 100%);", css_vars(DEFAULT_INPUTS))

	def test_the_overlay_outline_is_white_or_black_on_a_black_page(self):
		for background, rgb, css in (("white", (255, 255, 255), "hsl(0 0% 100%)"), ("tinted", (255, 255, 255), "hsl(0 0% 100%)"), ("black", (0, 0, 0), "hsl(0 0% 0%)")):
			with self.subTest(background=background):
				inputs = inputs_from({ "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50, "background": background })
				self.assertEqual(palette_of(inputs).text_outline.rgb, rgb)
				self.assertIn(f"--outline-color: {css};", css_vars(inputs))

	def test_tinted_is_the_themes_light_color(self):
		inputs = inputs_from({ "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50, "background": "tinted" })
		self.assertEqual(palette_of(inputs).bg_page, palette_of(inputs).bg_primary)
		self.assertIn("--page-bg: hsl(from var(--theme-base) h s var(--l-bg-light));", css_vars(inputs))

	def test_black_is_dark_mode_with_the_tones_traded(self):
		light = inputs_from({ "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 })
		dark = inputs_from({ "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50, "background": "black" })
		self.assertEqual(palette_of(dark).bg_page.rgb, (0, 0, 0))
		self.assertIn("--page-bg: hsl(0 0% 0%);", css_vars(dark))
		# text that was dark is light, a panel that was light is dark, and the other way round
		self.assertEqual((dark.l_text_dark, dark.l_text_light, dark.l_bg_light, dark.l_bg_dark), (light.l_text_light, light.l_text_dark, light.l_bg_dark, light.l_bg_light))
		self.assertGreater(palette_of(dark).text_primary.l, 80)
		self.assertLess(palette_of(dark).bg_primary.l, 30)
		self.assertEqual(palette_of(dark).bg_primary_accent, palette_of(light).bg_primary_accent)

class TestPagesUseTheTheme(unittest.TestCase):
	"""No page sets a font of its own: the body font is the theme's (plugin.css), headings take var(--font-heading), overlay text var(--font-overlay)."""
	def test_no_page_names_a_font_family(self):
		root = os.path.dirname(STATIC)
		pages = [os.path.join(d, f) for top in ("datasources", "static") for d, _, files in os.walk(os.path.join(root, top)) for f in files if f.endswith(".html")]
		self.assertGreater(len(pages), 4)
		for page in pages:
			with open(page, encoding="utf-8") as f:
				text = f.read()
			with self.subTest(os.path.relpath(page, root)):
				for found in re.findall(r"font-family:\s*([^;]+);", text):
					# the faces plugin.html declares are the only literal names; a page uses the variables
					if os.path.basename(page) == "plugin.html":
						continue
					self.assertRegex(found, r"var\(--font-(body|heading|overlay)", f"{page} sets a font of its own")

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
				RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs).render((100, 50), { "settings": {} })
		html = captured["html"]
		self.assertIn(css_vars(inputs), html)
		self.assertGreater(html.index(css_vars(inputs)), html.index("themes.css"))
		self.assertNotIn("theme-triadic", html)

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestFontsInChromium(unittest.TestCase):
	"""The theme's fonts reach a page: the same text in another body font, or at another size, draws differently."""
	def _page(self, **theme):
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block style %}<style>.t { font-size: calc(10dvh * var(--font-scale)); } .h { font-family: var(--font-heading); }</style>{% endblock %}'
					'{% block content %}<div class="t">Hamburgefonstiv</div><div class="t h">Hamburgefonstiv</div>{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from({ "theme": "analogous", "hue": 200, "saturation": 50, "lightness": 50, **theme })).render((400, 200), { "settings": {} })
		assert image is not None
		return image.convert("L").tobytes()

	def test_font_and_scale_change_the_page(self):
		base = self._page()
		self.assertNotEqual(base, self._page(fontBody="Napoli"))
		self.assertNotEqual(base, self._page(fontHeading="Dogica"))
		self.assertNotEqual(base, self._page(fontScale=1.4))
		self.assertEqual(base, self._page(fontBody="Jost", fontScale=1.0))

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestBackgroundInChromium(unittest.TestCase):
	def _corner(self, **theme):
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}<div style="font-size:30px">Hello</div>{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from({ "theme": "analogous", "hue": 200, "saturation": 50, "lightness": 50, **theme })).render((200, 100), { "settings": {} })
		assert image is not None
		return image.convert("RGB").getpixel((190, 90))

	def test_the_page_behind_is_white_tinted_or_black(self):
		self.assertEqual(self._corner(), (255, 255, 255))
		self.assertEqual(self._corner(background="black"), (0, 0, 0))
		tinted = self._corner(background="tinted")
		self.assertNotIn(tinted, ((255, 255, 255), (0, 0, 0)))
		want = palette_of(inputs_from({ "theme": "analogous", "hue": 200, "saturation": 50, "lightness": 50, "background": "tinted" })).bg_page.rgb
		# Chromium and Python round the derived color differently by a step at most
		self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(tinted, want)), (tinted, want))

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
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "swatches.html", inputs_from(settings)).render((len(roles) * SWATCH, 3 * SWATCH), { "settings": {} })
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
