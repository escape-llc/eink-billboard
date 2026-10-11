"""
The device's color theme, computed here and nowhere else.

The theme settings (`theme-settings.json`: scheme, hue, saturation, lightness) become a few HSL inputs. Two things read those inputs:
- CSS: `css_vars` writes them into `:root` (see `static/render/plugin.html`), and `static/render/themes.css` derives every role from them with
  relative color syntax, e.g. `hsl(from var(--theme-base) calc(h + var(--theme-h1-offset)) s var(--l-text-dark))`;
- PIL: `Palette` applies the same derivation in Python, so code that draws with PIL is in the same theme as the HTML pages.
A test renders one swatch per role in Chromium and compares it with `Palette`, so the two cannot drift.
"""
import colorsys
import logging
from dataclasses import dataclass, fields, replace
from typing import Any, Mapping

from .configuration_manager import FONT_FAMILIES, SettingsConfigurationManager

logger = logging.getLogger(__name__)

# the hue offsets of the two secondary colors from the base hue, in degrees
SCHEMES: dict[str, tuple[float, float]] = {
	"analogous": (-30, 30),
	"complementary": (180, 180),
	"split-complementary": (150, 210),
	"triadic": (120, 240),
	"tetradic": (90, 180),
	"monochrome": (0, 0),
}
MONOCHROME_SATURATION = 60.0
# the factory defaults (python/storage/schemas/theme.json)
DEFAULT_SETTINGS: Mapping[str, Any] = { "theme": "complementary", "hue": 220, "saturation": 80, "lightness": 50, "fontBody": "Jost", "fontHeading": None, "fontScale": 1.0, "background": "white" }
# the page behind everything: plain white (the crispest on a color e-ink panel, whose palette is a few pure colors), the theme's light tint, or black (dark mode:
# every light tone and dark tone trade places, so text reads light on dark and the panels of a page are dark)
BACKGROUNDS = ("white", "tinted", "black")
# the text size of every page is multiplied by `fontScale`, within these limits (a page is laid out to fit text a little larger or smaller, not much more)
FONT_SCALE_MIN = 0.8
FONT_SCALE_MAX = 1.4
# lightness of each tone, in percent: fixed for contrast, except the accent, which the setting moves
L_BG_LIGHT = 80.0
L_BG_DARK = 20.0
L_TEXT_DARK = 25.0
L_TEXT_LIGHT = 90.0

@dataclass(frozen=True, slots=True)
class Color:
	"""An HSL color: h in degrees, s and l in percent."""
	h: float
	s: float
	l: float
	@property
	def rgb(self) -> tuple[int, int, int]:
		r, g, b = colorsys.hls_to_rgb((self.h % 360) / 360.0, self.l / 100.0, self.s / 100.0)
		return (round(r * 255), round(g * 255), round(b * 255))
	@property
	def css(self) -> str:
		return f"hsl({_num(self.h % 360)} {_num(self.s)}% {_num(self.l)}%)"

@dataclass(frozen=True, slots=True)
class ThemeInputs:
	"""What the CSS gets: the base color, the two hue offsets, the lightness of each tone."""
	scheme: str
	hue: float
	saturation: float
	h1_offset: float
	h2_offset: float
	l_accent: float
	l_bg_light: float = L_BG_LIGHT
	l_bg_dark: float = L_BG_DARK
	l_text_dark: float = L_TEXT_DARK
	l_text_light: float = L_TEXT_LIGHT
	# the typography: families we ship (FONT_FAMILIES), and a multiplier for text sizes
	font_body: str = "Jost"
	font_heading: str = "Jost"
	font_scale: float = 1.0
	background: str = "white"

@dataclass(frozen=True, slots=True)
class Palette:
	"""One color per class of themes.css (`text-primary` is `text_primary`); the derivation is the CSS one."""
	text_primary: Color
	text_secondary_1: Color
	text_secondary_2: Color
	text_primary_light: Color
	text_secondary_1_light: Color
	text_secondary_2_light: Color
	bg_page: Color
	bg_primary: Color
	bg_secondary_1: Color
	bg_secondary_2: Color
	bg_primary_accent: Color
	bg_secondary_1_accent: Color
	bg_secondary_2_accent: Color
	bg_primary_dark: Color
	bg_secondary_1_dark: Color
	bg_secondary_2_dark: Color
	@staticmethod
	def roles() -> list[str]:
		"""The role names as CSS class names."""
		return [f.name.replace("_", "-") for f in fields(Palette)]

def _num(value: float) -> str:
	return f"{value:g}"

def _number(settings: Mapping[str, Any], name: str, low: float, high: float, problems: list[str]) -> float:
	value = settings.get(name)
	if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
		return float(value)
	problems.append(name)
	return float(DEFAULT_SETTINGS[name])

def inputs_from(settings: Mapping[str, Any]|None) -> ThemeInputs:
	"""The inputs for a theme settings document; a missing or invalid value falls back to the factory default (one warning)."""
	settings = settings or {}
	problems: list[str] = []
	scheme = settings.get("theme")
	if scheme not in SCHEMES:
		problems.append("theme")
		scheme = str(DEFAULT_SETTINGS["theme"])
	hue = _number(settings, "hue", 0, 360, problems)
	saturation = _number(settings, "saturation", 0, 100, problems)
	lightness = _number(settings, "lightness", 0, 100, problems)
	if problems:
		logger.warning(f"Theme settings: invalid or missing {', '.join(problems)}; using the defaults for them")
	if scheme == "monochrome":
		saturation = MONOCHROME_SATURATION
	h1, h2 = SCHEMES[scheme]
	body = settings.get("fontBody")
	if body not in FONT_FAMILIES:
		if body is not None:
			logger.warning("Theme settings: the body font is not one we have; using the default")
		body = str(DEFAULT_SETTINGS["fontBody"])
	heading = settings.get("fontHeading")
	if heading not in FONT_FAMILIES:
		# unset: the headings wear the body font
		heading = body
	scale = settings.get("fontScale")
	if not (isinstance(scale, (int, float)) and not isinstance(scale, bool) and FONT_SCALE_MIN <= scale <= FONT_SCALE_MAX):
		scale = float(DEFAULT_SETTINGS["fontScale"])
	background = settings.get("background")
	if background not in BACKGROUNDS:
		background = str(DEFAULT_SETTINGS["background"])
	inputs = ThemeInputs(scheme, hue % 360, saturation, h1, h2, lightness, font_body=str(body), font_heading=str(heading), font_scale=float(scale), background=str(background))
	if background == "black":
		inputs = replace(inputs, l_text_dark=L_TEXT_LIGHT, l_text_light=L_TEXT_DARK, l_bg_light=L_BG_DARK, l_bg_dark=L_BG_LIGHT)
	return inputs

def palette_of(inputs: ThemeInputs) -> Palette:
	hues = { "primary": inputs.hue, "secondary_1": inputs.hue + inputs.h1_offset, "secondary_2": inputs.hue + inputs.h2_offset }
	def tone(name: str, lightness: float) -> Color:
		return Color(hues[name] % 360, inputs.saturation, lightness)
	return Palette(
		text_primary=tone("primary", inputs.l_text_dark),
		text_secondary_1=tone("secondary_1", inputs.l_text_dark),
		text_secondary_2=tone("secondary_2", inputs.l_text_dark),
		text_primary_light=tone("primary", inputs.l_text_light),
		text_secondary_1_light=tone("secondary_1", inputs.l_text_light),
		text_secondary_2_light=tone("secondary_2", inputs.l_text_light),
		bg_page=Color(0, 0, 100) if inputs.background == "white" else Color(0, 0, 0) if inputs.background == "black" else tone("primary", inputs.l_bg_light),
		bg_primary=tone("primary", inputs.l_bg_light),
		bg_secondary_1=tone("secondary_1", inputs.l_bg_light),
		bg_secondary_2=tone("secondary_2", inputs.l_bg_light),
		bg_primary_accent=tone("primary", inputs.l_accent),
		bg_secondary_1_accent=tone("secondary_1", inputs.l_accent),
		bg_secondary_2_accent=tone("secondary_2", inputs.l_accent),
		bg_primary_dark=tone("primary", inputs.l_bg_dark),
		bg_secondary_1_dark=tone("secondary_1", inputs.l_bg_dark),
		bg_secondary_2_dark=tone("secondary_2", inputs.l_bg_dark),
	)

def css_vars(inputs: ThemeInputs) -> str:
	"""The CSS custom properties themes.css derives from, for a `:root { ... }` block. HSL only: no RGB is written."""
	values = {
		"--theme-base": Color(inputs.hue, inputs.saturation, inputs.l_accent).css,
		"--theme-h1-offset": _num(inputs.h1_offset),
		"--theme-h2-offset": _num(inputs.h2_offset),
		"--l-bg-light": f"{_num(inputs.l_bg_light)}%",
		"--l-accent": f"{_num(inputs.l_accent)}%",
		"--l-bg-dark": f"{_num(inputs.l_bg_dark)}%",
		"--l-text-dark": f"{_num(inputs.l_text_dark)}%",
		"--l-text-light": f"{_num(inputs.l_text_light)}%",
		# family names are ours (FONT_FAMILIES, plain identifiers), so they need no quotes: the page escapes quotes
		# the page behind everything (the class `bg-page`)
		"--page-bg": { "white": "hsl(0 0% 100%)", "black": "hsl(0 0% 0%)" }.get(inputs.background, "hsl(from var(--theme-base) h s var(--l-bg-light))"),
		"--font-body": inputs.font_body,
		"--font-heading": inputs.font_heading,
		"--font-scale": _num(inputs.font_scale),
	}
	return " ".join(f"{name}: {value};" for name, value in values.items())

DEFAULT_INPUTS = inputs_from(DEFAULT_SETTINGS)

def current_inputs(scm: SettingsConfigurationManager|None) -> ThemeInputs:
	"""The device theme now: read on every call, so a change in the web app applies to the next render. Without settings, the factory default."""
	if scm is None:
		return DEFAULT_INPUTS
	try:
		_, settings = scm.open("theme").get()
	except Exception as e:
		logger.warning(f"Theme settings could not be read ({type(e).__name__}); using the default theme")
		return DEFAULT_INPUTS
	return inputs_from(settings)

@dataclass(frozen=True, slots=True)
class Typography:
	"""What PIL code draws text with: the family names (as `StaticConfigurationManager.get_font` takes them) and the size multiplier."""
	body: str
	heading: str
	scale: float

def typography_of(inputs: ThemeInputs) -> Typography:
	return Typography(inputs.font_body, inputs.font_heading, inputs.font_scale)

def current_typography(scm: SettingsConfigurationManager|None) -> Typography:
	"""The device's fonts now, read on every call like the palette."""
	return typography_of(current_inputs(scm))

def current_palette(scm: SettingsConfigurationManager|None) -> Palette:
	return palette_of(current_inputs(scm))
