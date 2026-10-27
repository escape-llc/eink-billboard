import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from typing import Any, cast
from unittest.mock import patch

from ..model.configuration_manager import FONT_FAMILIES, OFFERED_FONTS, StaticConfigurationManager
from ..model.inks import INK_SETS, ink_set_rgb, publish_panel_ink_set
from ..model.theme import BLACK_PAGE_INKS, DEFAULT_INPUTS, PRESETS, Palette, css_vars, current_inputs, current_palette, current_typography, inputs_from, resolve
from ..plugins import plugin_base
from ..plugins.plugin_base import RenderSession
from ..utils.image_utils import chrome_command

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
THEMES_CSS = os.path.join(STATIC, "render", "themes.css")
CHROME = chrome_command()
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

class TestResolve(unittest.TestCase):
	"""Every preset, on either page, on every ink set: the rules that hold whatever the panel has."""
	def every(self):
		for preset in PRESETS:
			for background in ("white", "black"):
				for ink_set in INK_SETS:
					yield preset, background, ink_set, { "preset": preset, "background": background, "textPrimary": "blue", "textSecondary1": "orange", "textSecondary2": "green", "fill": "yellow", "textOnFill": "white" }

	def test_every_role_is_an_ink_of_the_set(self):
		for preset, background, ink_set, settings in self.every():
			palette, _, _ = resolve(settings, ink_set)
			for role in Palette.roles():
				with self.subTest(preset=preset, background=background, ink_set=ink_set, role=role):
					self.assertIn(palette.ink(role), INK_SETS[ink_set])

	def test_text_never_equals_its_background_and_two_light_inks_are_never_paired(self):
		for preset, background, ink_set, settings in self.every():
			p, _, _ = resolve(settings, ink_set)
			with self.subTest(preset=preset, background=background, ink_set=ink_set):
				for text, behind in ((p.text_primary, p.bg_page), (p.text_secondary_1, p.bg_page), (p.text_secondary_2, p.bg_page), (p.text_outline, p.text_primary),
						(p.text_on_fill, p.bg_fill), (p.text_on_strong, p.bg_strong)):
					if text == p.text_outline and behind == p.text_primary:
						continue
					self.assertNotEqual(text, behind)
					self.assertNotEqual({text, behind}, {"white", "yellow"})

	def test_no_fill_leaves_the_page_readable(self):
		palette, _, _ = resolve({ "preset": "classic" }, "bw")
		self.assertEqual((palette.bg_fill, palette.text_on_fill), (palette.bg_page, palette.text_primary))

	def test_the_classic_preset_on_each_ink_set(self):
		def roles(ink_set):
			p, _, _ = resolve({ "preset": "classic" }, ink_set)
			return (p.text_primary, p.text_secondary_1, p.text_secondary_2, p.bg_fill, p.text_on_fill)
		self.assertEqual(roles("spectra6"), ("black", "red", "blue", "yellow", "black"))
		self.assertEqual(roles("acep7"), ("black", "red", "blue", "yellow", "black"))
		self.assertEqual(roles("bwry"), ("black", "red", "black", "yellow", "black"))
		self.assertEqual(roles("bwr"), ("black", "red", "black", "red", "white"))
		self.assertEqual(roles("bwy"), ("black", "black", "black", "yellow", "black"))
		self.assertEqual(roles("bw"), ("black", "black", "black", "white", "black"))

	def test_the_other_presets(self):
		warm, _, _ = resolve({ "preset": "warm" }, "acep7")
		self.assertEqual((warm.text_secondary_2, warm.bg_fill), ("orange", "yellow"))
		cool, _, _ = resolve({ "preset": "cool" }, "spectra6")
		self.assertEqual((cool.text_secondary_1, cool.text_secondary_2, cool.bg_fill, cool.text_on_fill), ("blue", "green", "blue", "white"))
		mono, _, _ = resolve({ "preset": "mono" }, "acep7")
		self.assertEqual((mono.text_primary, mono.text_secondary_1, mono.bg_fill, mono.text_on_fill), ("black", "black", "black", "white"))

	def test_orange_falls_back_to_red_then_black(self):
		def second(ink_set):
			return resolve({ "preset": "warm" }, ink_set)[0].text_secondary_2
		self.assertEqual((second("acep7"), second("spectra6"), second("bwry"), second("bwr"), second("bw")), ("orange", "red", "red", "red", "black"))

	def test_a_black_page_swaps_the_inks(self):
		p, _, _ = resolve({ "preset": "classic", "background": "black" }, "spectra6")
		self.assertEqual((p.bg_page, p.text_primary, p.text_secondary_1, p.text_secondary_2, p.bg_fill, p.text_on_fill, p.text_outline), ("black", "white", "yellow", "red", "yellow", "black", "black"))
		self.assertEqual((p.bg_strong, p.text_on_strong), ("white", "black"))
		p, _, _ = resolve({ "preset": "mono", "background": "black" }, "spectra6")
		self.assertEqual((p.text_primary, p.text_secondary_1, p.text_secondary_2), ("white", "white", "white"))
		self.assertEqual(BLACK_PAGE_INKS[0], "white")

	def test_yellow_text_is_never_on_white(self):
		p, _, _ = resolve({ "preset": "custom", "textPrimary": "yellow", "textSecondary1": "yellow", "textSecondary2": "yellow" }, "spectra6")
		self.assertEqual((p.text_primary, p.text_secondary_1, p.text_secondary_2), ("black", "black", "black"))
		p, _, _ = resolve({ "preset": "custom", "background": "black", "textPrimary": "yellow" }, "spectra6")
		self.assertEqual(p.text_primary, "yellow")

	def test_custom_inks_are_used_and_a_missing_one_is_the_classic_ink(self):
		p, _, _ = resolve({ "preset": "custom", "textPrimary": "blue", "textSecondary1": "green", "fill": "red", "textOnFill": "white" }, "spectra6")
		self.assertEqual((p.text_primary, p.text_secondary_1, p.text_secondary_2, p.bg_fill, p.text_on_fill), ("blue", "green", "blue", "red", "white"))

	def test_the_text_on_a_fill_it_does_not_read_on_is_black_or_white(self):
		p, _, _ = resolve({ "preset": "custom", "fill": "blue", "textOnFill": "blue" }, "spectra6")
		self.assertEqual(p.text_on_fill, "white")
		p, _, _ = resolve({ "preset": "custom", "fill": "yellow", "textOnFill": "white" }, "spectra6")
		self.assertEqual(p.text_on_fill, "black")

class TestSettings(unittest.TestCase):
	def test_bad_or_missing_values_fall_back_to_the_defaults_with_one_warning(self):
		with self.assertLogs("python.model.theme", level="WARNING") as logs:
			inputs = inputs_from({ "preset": "plaid", "background": "tinted" }, "spectra6")
		self.assertEqual(len(logs.output), 1)
		self.assertEqual(inputs, DEFAULT_INPUTS)

	def test_no_settings_is_the_default_theme(self):
		self.assertEqual(inputs_from(None, "spectra6"), DEFAULT_INPUTS)
		self.assertEqual(current_inputs(None), DEFAULT_INPUTS)

	def test_current_theme_reads_the_settings_each_time(self):
		scm = FakeSettings({ "preset": "cool" })
		self.assertEqual(current_inputs(cast(Any, scm)).preset, "cool")
		scm.settings = { "preset": "mono" }
		self.assertEqual(current_palette(cast(Any, scm)).text_secondary_1, "black")

	def test_settings_that_cannot_be_read_give_the_default_theme(self):
		with self.assertLogs("python.model.theme", level="WARNING"):
			self.assertEqual(current_inputs(cast(Any, FakeSettings(error=OSError("disk")))), DEFAULT_INPUTS)

	def test_the_theme_resolves_against_the_panel_that_is_attached(self):
		try:
			publish_panel_ink_set("bw")
			self.assertEqual(current_inputs(cast(Any, FakeSettings({ "preset": "classic" }))).palette.bg_fill, "white")
			publish_panel_ink_set("spectra6")
			self.assertEqual(current_inputs(cast(Any, FakeSettings({ "preset": "classic" }))).palette.bg_fill, "yellow")
		finally:
			publish_panel_ink_set(None)

class TestTypography(unittest.TestCase):
	def test_the_defaults_are_lexend_at_full_size(self):
		self.assertEqual((DEFAULT_INPUTS.font_body, DEFAULT_INPUTS.font_heading, DEFAULT_INPUTS.font_scale), ("Lexend", "Lexend", 1.0))
		# a document from before the fonts existed reads the same, and says nothing about it
		with self.assertNoLogs("python.model.theme", level="WARNING"):
			self.assertEqual(inputs_from({ "preset": "warm" }).font_body, "Lexend")

	def test_choices_are_read_and_the_heading_follows_the_body_when_unset(self):
		inputs = inputs_from({ "fontBody": "League Spartan", "fontHeading": None, "fontScale": 1.25 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("League Spartan", "League Spartan", 1.25))
		inputs = inputs_from({ "fontBody": "Lexend", "fontHeading": "Fira Sans", "fontScale": 0.8 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("Lexend", "Fira Sans", 0.8))

	def test_the_overlays_share_one_font_and_it_follows_the_heading_when_unset(self):
		self.assertEqual(inputs_from({ "fontBody": "Lexend", "fontHeading": "League Spartan" }).font_overlay, "League Spartan")
		self.assertEqual(inputs_from({ "fontBody": "League Spartan" }).font_overlay, "League Spartan")
		self.assertEqual(inputs_from({ "fontBody": "Lexend", "fontOverlay": "Fira Sans" }).font_overlay, "Fira Sans")
		self.assertEqual(inputs_from({ "fontBody": "Lexend", "fontOverlay": "../x" }).font_overlay, "Lexend")
		self.assertIn("--font-overlay: Fira Sans;", css_vars(inputs_from({ "fontOverlay": "Fira Sans" })))
		self.assertEqual(current_typography(cast(Any, FakeSettings({ "fontOverlay": "DSEG7" }))).overlay, "DSEG7")

	def test_only_the_fonts_we_ship_and_sizes_in_range_are_used(self):
		inputs = inputs_from({ "fontBody": "../../etc/passwd", "fontHeading": "Comic Sans", "fontScale": 9 })
		self.assertEqual((inputs.font_body, inputs.font_heading, inputs.font_scale), ("Lexend", "Lexend", 1.0))
		self.assertEqual(inputs_from({ "fontScale": 0.5 }).font_scale, 1.0)
		self.assertEqual(inputs_from({ "fontScale": True }).font_scale, 1.0)

	def test_the_css_gets_the_variables_without_quotes(self):
		text = css_vars(inputs_from({ "fontBody": "DSEG7", "fontHeading": "League Spartan", "fontScale": 1.2 }))
		self.assertIn("--font-body: DSEG7;", text)
		self.assertIn("--font-heading: League Spartan;", text)
		self.assertIn("--font-scale: 1.2;", text)
		self.assertNotIn('"', text)

	def test_pil_code_reads_the_same_choice_each_time(self):
		scm = FakeSettings({ "fontBody": "League Spartan", "fontScale": 1.2 })
		self.assertEqual(current_typography(cast(Any, scm)).body, "League Spartan")
		scm.settings = { "fontBody": "Lexend", "fontScale": 1.0 }
		self.assertEqual((current_typography(cast(Any, scm)).body, current_typography(cast(Any, scm)).scale), ("Lexend", 1.0))
		self.assertEqual(current_typography(None).body, "Lexend")

class TestBackground(unittest.TestCase):
	def test_the_page_is_white_unless_asked_otherwise(self):
		self.assertEqual(DEFAULT_INPUTS.background, "white")
		self.assertEqual(inputs_from({ "background": "plaid" }).background, "white")
		self.assertEqual(DEFAULT_INPUTS.palette.rgb("bg_page"), (255, 255, 255))
		self.assertIn("--page-bg: #ffffff;", css_vars(DEFAULT_INPUTS))

	def test_the_overlay_outline_is_the_pages_color(self):
		for background, rgb, css in (("white", (255, 255, 255), "#ffffff"), ("black", (0, 0, 0), "#000000")):
			with self.subTest(background=background):
				inputs = inputs_from({ "background": background }, "spectra6")
				self.assertEqual(inputs.palette.rgb("text_outline"), rgb)
				self.assertIn(f"--outline-color: {css};", css_vars(inputs))

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
	def test_css_vars_are_drive_hex_only(self):
		text = css_vars(inputs_from({ "preset": "warm" }, "acep7"))
		self.assertIn("--ink-text-secondary-2: #ff8000;", text)
		self.assertIn("--ink-bg-fill: #ffff00;", text)
		self.assertNotIn("hsl", text)
		self.assertNotIn("rgb", text)
		for role in Palette.roles():
			if role not in ("bg-page", "text-outline"):
				self.assertRegex(text, rf"--ink-{role}: #[0-9a-f]{{6}};")

	def test_every_themes_css_class_is_a_palette_role(self):
		with open(THEMES_CSS, encoding="utf-8") as f:
			css = f.read()
		classes = set(re.findall(r"^\.((?:text|bg|fill)-[a-z0-9-]+)\s*\{", css, re.MULTILINE)) - { "bg-transparent", "fill-ink" }
		self.assertEqual(classes, set(Palette.roles()))

	def test_themes_css_derives_nothing(self):
		with open(THEMES_CSS, encoding="utf-8") as f:
			css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.DOTALL)
		self.assertNotRegex(css, r"hsl|rgb|color-mix|calc\(")

	def test_render_session_puts_the_theme_after_the_stylesheets(self):
		captured = {}
		def fake_render(html, args):
			captured["html"] = html
			return None
		inputs = inputs_from({ "preset": "cool" })
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}x{% endblock %}')
			with patch.object(plugin_base, "render_html_arglist", fake_render):
				RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs).render((100, 50), { "settings": {} })
		html = captured["html"]
		self.assertIn(css_vars(inputs), html)
		self.assertGreater(html.index(css_vars(inputs)), html.index("themes.css"))

class TestNoTranslucency(unittest.TestCase):
	"""A page is made of the panel's inks only: a tint, a fade, a gradient or a shadow is a color the panel does not have, and is dithered into dots."""
	BANNED = r"opacity|rgba\(|hsla\(|linear-gradient|radial-gradient|conic-gradient|box-shadow|text-shadow|drop-shadow|color-mix|backdrop-filter"
	def test_no_page_or_stylesheet_fades_tints_or_shades(self):
		root = os.path.dirname(STATIC)
		files = [os.path.join(d, f) for top in ("datasources", "static") for d, _, names in os.walk(os.path.join(root, top)) for f in names
			if f.endswith((".html", ".css")) and "waveshare_epd" not in d]
		self.assertGreater(len(files), 10)
		for path in files:
			with open(path, encoding="utf-8") as f:
				text = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.DOTALL)
			with self.subTest(os.path.relpath(path, root)):
				self.assertNotRegex(text, self.BANNED)

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestFontsInChromium(unittest.TestCase):
	"""The theme's fonts reach a page: the same text in another body font, or at another size, draws differently."""
	def _page(self, **theme):
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block style %}<style>.t { font-size: calc(10dvh * var(--font-scale)); } .h { font-family: var(--font-heading); }</style>{% endblock %}'
					'{% block content %}<div class="t">Hamburgefonstiv</div><div class="t h">Hamburgefonstiv</div>{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from({ **theme })).render((400, 200), { "settings": {} })
		assert image is not None
		return image.convert("L").tobytes()

	def test_font_and_scale_change_the_page(self):
		base = self._page()
		self.assertNotEqual(base, self._page(fontBody="League Spartan"))
		self.assertNotEqual(base, self._page(fontHeading="Fira Sans"))
		self.assertNotEqual(base, self._page(fontScale=1.4))
		self.assertEqual(base, self._page(fontBody="Lexend", fontScale=1.0))

SWATCH = 20
@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestCssMatchesPython(unittest.TestCase):
	"""Every role renders in Chromium as exactly its ink's drive color, which is the one Python draws with."""
	def _render(self, settings, ink_set):
		roles = Palette.roles()
		swatches = "".join(
			f'<div class="{role}" style="position:absolute;left:{i * SWATCH}px;top:0;width:{SWATCH}px;height:{SWATCH}px;'
			f'{"background-color:currentColor" if role.startswith("text-") else ""}"></div>'
			for i, role in enumerate(roles))
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "swatches.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}' + swatches + '{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "swatches.html", inputs_from(settings, ink_set)).render((len(roles) * SWATCH, 3 * SWATCH), { "settings": {} })
		self.assertIsNotNone(image)
		return roles, image.convert("RGB")

	def test_swatches(self):
		for settings, ink_set in (({ "preset": "classic" }, "spectra6"), ({ "preset": "warm" }, "acep7"), ({ "preset": "cool", "background": "black" }, "spectra6"), ({ "preset": "classic" }, "bw")):
			roles, image = self._render(settings, ink_set)
			palette = inputs_from(settings, ink_set).palette
			for i, role in enumerate(roles):
				with self.subTest(settings=settings, ink_set=ink_set, role=role):
					self.assertEqual(image.getpixel((i * SWATCH + SWATCH // 2, SWATCH // 2)), palette.rgb(role))

@unittest.skipUnless(sys.platform != "win32" and HAVE_CHROME, f"needs {CHROME} on PATH and fontconfig (Linux; see AGENTS.md, Test environment)")
class TestAPageIsMadeOfInksOnly(unittest.TestCase):
	"""The default theme on a six-color panel: text in every role and a fill behind it draw nothing but the panel's inks, so nothing is left to dither."""
	def test_every_pixel_is_a_drive_color_of_the_set(self):
		roles = ["text-primary", "text-secondary-1", "text-secondary-2", "text-on-fill"]
		body = "".join(f'<div class="{role}" style="font-size:22px;font-weight:bold">Hamburgefonstiv {role}</div>' for role in roles)
		body += '<div class="bg-fill text-on-fill" style="font-size:22px">On the highlight</div><div class="bg-strong text-on-strong" style="font-size:22px">On a solid block</div>'
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}' + body + '{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from({}, "spectra6")).render((500, 260), { "settings": {} })
		assert image is not None
		allowed = set(ink_set_rgb("spectra6"))
		found = {color for _, color in image.convert("RGB").getcolors(maxcolors=1 << 20) or []}
		self.assertTrue(found <= allowed, sorted(found - allowed)[:5])
		self.assertGreater(len(found), 3)

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestBackgroundInChromium(unittest.TestCase):
	def _corner(self, **theme):
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block content %}<div style="font-size:30px">Hello</div>{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from(theme, "spectra6")).render((200, 100), { "settings": {} })
		assert image is not None
		return image.convert("RGB").getpixel((190, 90))

	def test_the_page_behind_is_white_or_black(self):
		self.assertEqual(self._corner(), (255, 255, 255))
		self.assertEqual(self._corner(background="black"), (0, 0, 0))

if __name__ == "__main__":
	unittest.main()

class TestOfferedFonts(unittest.TestCase):
	"""What the theme offers is a subset of what we ship, and the schema's `font` lookup says exactly that."""
	def _lookup(self) -> list[dict[str, str]]:
		with open(os.path.join(os.path.dirname(STATIC), "storage", "schemas", "theme.json"), encoding="utf-8") as f:
			return json.load(f)["schema"]["lookups"]["font"]["items"]

	def test_every_offered_font_is_shipped_and_the_clock_digits_are_not_offered(self):
		self.assertTrue(set(OFFERED_FONTS) <= set(FONT_FAMILIES))
		self.assertIn("DSEG7", FONT_FAMILIES)
		self.assertNotIn("DSEG7", OFFERED_FONTS)
		self.assertEqual(len(OFFERED_FONTS), len(set(OFFERED_FONTS)))

	def test_the_font_lookup_is_the_offered_list_in_order(self):
		self.assertEqual([item["value"] for item in self._lookup()], list(OFFERED_FONTS))

	def test_every_shipped_font_has_its_files_and_licence(self):
		for family, variants in FONT_FAMILIES.items():
			for variant in variants:
				with self.subTest(family=family, weight=variant["font-weight"]):
					self.assertTrue(os.path.isfile(os.path.join(STATIC, "fonts", variant["file"])))
			self.assertTrue(os.path.isfile(os.path.join(STATIC, "fonts", os.path.dirname(variants[0]["file"]), "OFL.txt")))

	def test_a_variable_font_declares_the_weight_it_is_drawn_at(self):
		faces = {(f["font_family"], f["font_weight"]) for f in StaticConfigurationManager(STATIC).enum_fonts()}
		self.assertIn(("Lexend", "500"), faces)
		self.assertIn(("Lexend", "700"), faces)
		self.assertIn(("Atkinson Hyperlegible", "normal"), faces)

	def test_no_font_folder_is_left_that_nothing_ships(self):
		shipped = {os.path.dirname(v["file"]) for variants in FONT_FAMILIES.values() for v in variants}
		self.assertEqual({d for d in os.listdir(os.path.join(STATIC, "fonts")) if os.path.isdir(os.path.join(STATIC, "fonts", d))}, shipped)

# family: (weight, the size a text is drawn at from), measured in the test container (Chromium, fontconfig without antialiasing)
# a serif is for headings only, from 22 px, and offered in bold; Lexend, Fira Sans and League Spartan "normal" are their 500
SOLID_BODY = { "Lexend": ("normal", 15), "Atkinson Hyperlegible": ("normal", 22), "Fira Sans": ("normal", 16), "Barlow Semi Condensed": ("normal", 15), "League Spartan": ("normal", 18), "Bitter": ("bold", 22) }
MIN_SOLID = 0.80
SAMPLE = "Hamburgefonstiv 0123456789 Quick brown fox"

def solid_share(image, threshold=128) -> float:
	"""The share of the ink pixels that sit in a solid 2x2 block: 85 % and up reads as solid, under 60 % as wispy."""
	grey = image.convert("L")
	w, h = grey.size
	px = grey.load()
	ink = [[px[x, y] < threshold for x in range(w)] for y in range(h)]
	total = solid = 0
	for y in range(h):
		for x in range(w):
			if not ink[y][x]:
				continue
			total += 1
			if any(all(0 <= xx < w and 0 <= yy < h and ink[yy][xx] for xx in (x0, x0 + 1) for yy in (y0, y0 + 1)) for x0 in (x - 1, x) for y0 in (y - 1, y)):
				solid += 1
	return solid / total if total else 0.0

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
@unittest.skipUnless(sys.platform.startswith("linux"), "the antialiasing setting is fontconfig's (Linux)")
class TestStrokeSolidity(unittest.TestCase):
	"""Text is drawn without antialiasing, so a one-pixel stroke is wispy: the offered fonts hold their floors, and so do the clock's digits."""
	def _share(self, family: str, weight: str, px: int, text: str = SAMPLE) -> float:
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as f:
				f.write('{% extends "plugin.html" %}{% block style %}<style>.t { font-size: ' + str(px) + 'px; font-weight: ' + weight + '; white-space: nowrap; }</style>{% endblock %}'
					'{% block content %}<div class="t">' + text + '</div>{% endblock %}')
			image = RenderSession(StaticConfigurationManager(STATIC), folder, "page.html", inputs_from({ "fontBody": family })).render((800, 80), { "settings": {} })
		assert image is not None
		return solid_share(image)

	def test_body_text_is_solid_at_its_floor(self):
		for family, (weight, px) in SOLID_BODY.items():
			with self.subTest(family=family):
				share = self._share(family, weight, px)
				self.assertGreaterEqual(share, MIN_SOLID, f"{family} {weight} at {px} px: {share:.0%}")

	def test_every_offered_font_but_the_serif_is_solid_in_bold_at_13_px(self):
		for family in (f for f in OFFERED_FONTS if f != "Bitter"):
			with self.subTest(family=family):
				share = self._share(family, "bold", 13)
				self.assertGreaterEqual(share, MIN_SOLID, f"{family} bold at 13 px: {share:.0%}")

	def test_the_clock_digits_are_solid(self):
		share = self._share("DSEG7", "bold", 40, "88:88")
		self.assertGreaterEqual(share, MIN_SOLID, f"DSEG7 88:88: {share:.0%}")
