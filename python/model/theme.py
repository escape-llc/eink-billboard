"""
The device's color theme, computed here and nowhere else.

A page is drawn in the **inks** of the panel (`python/model/inks.py`), not in free colors: a color e-ink panel has a handful of pure pigments and dithers everything else into dots. The theme
settings (`theme-settings.json`) choose a preset (or, for `custom`, an ink for each role) and a page background; `resolve` turns that into one ink per role **for the ink set of the panel that is
attached** (`panel_ink_set`), by a fixed fallback rule, so the same choice works on a black-and-white panel and on a six-color one. Two things then read the result:
- CSS: `css_vars` writes each role's drive color (the exact RGB of the ink) into `:root` (see `static/render/plugin.html`) and `static/render/themes.css` has a plain class for each role;
- PIL: `Palette` holds the same inks, so code that draws with PIL is in the same theme as the HTML pages.
A test renders one swatch per role in Chromium and compares it with `Palette`, so the two cannot drift.
"""
import logging
from dataclasses import dataclass, fields
from typing import Any, Mapping

from .configuration_manager import FONT_FAMILIES, SettingsConfigurationManager
from .inks import DEFAULT_INK_SET, DRIVE, INK_SETS, INKS, panel_ink_set

logger = logging.getLogger(__name__)

PRESETS = ("classic", "warm", "cool", "mono", "custom")
# what a preset chooses an ink for: the main text, the two accents, the highlight fill and the text on it (white page)
PRESET_INKS: dict[str, tuple[str, str, str, str, str]] = {
	"classic": ("black", "red", "blue", "yellow", "black"),
	"warm": ("black", "red", "orange", "yellow", "black"),
	"cool": ("black", "blue", "green", "blue", "white"),
	"mono": ("black", "black", "black", "black", "white"),
}
# on a black page every preset trades to these (mono stays one ink)
BLACK_PAGE_INKS = ("white", "yellow", "red", "yellow", "black")
BLACK_PAGE_MONO = ("white", "white", "white", "white", "black")
# the settings' names of the five custom inks, in the order of the tuples above
CUSTOM_KEYS = ("textPrimary", "textSecondary1", "textSecondary2", "fill", "textOnFill")
BACKGROUNDS = ("white", "black")
# the factory defaults (python/storage/schemas/theme.json)
DEFAULT_SETTINGS: Mapping[str, Any] = { "preset": "classic", "background": "white", "fontBody": "Lexend", "fontHeading": None, "fontOverlay": None, "fontScale": 1.0 }
# the text size of every page is multiplied by `fontScale`, within these limits (a page is laid out to fit text a little larger or smaller, not much more)
FONT_SCALE_MIN = 0.8
FONT_SCALE_MAX = 1.4

@dataclass(frozen=True, slots=True)
class Palette:
	"""
	The ink of each role, by name (`INKS`); `text_primary` is the class `text-primary`. Every ink is one the panel has (`resolve`).
	`bg_fill` is the highlight; with no ink to highlight with it is the page's own color, and `text_on_fill` is then the main text ink, so a page still reads.
	"""
	text_primary: str
	text_secondary_1: str
	text_secondary_2: str
	bg_page: str
	bg_fill: str
	text_on_fill: str
	# a solid block in the main text ink, with the page's color on it
	bg_strong: str
	text_on_strong: str
	# the outline around overlay text, so it reads over a busy picture: the page's color
	text_outline: str
	@staticmethod
	def roles() -> list[str]:
		"""The role names as CSS class names."""
		return [f.name.replace("_", "-") for f in fields(Palette)]
	def ink(self, role: str) -> str:
		"""The ink of a role named as the field (`bg_page`) or as the class (`bg-page`)."""
		return getattr(self, role.replace("-", "_"))
	def rgb(self, role: str) -> tuple[int, int, int]:
		"""The exact color the role is drawn with, and handed to the driver."""
		return DRIVE[self.ink(role)]

@dataclass(frozen=True, slots=True)
class ThemeInputs:
	"""What a page is rendered with: the resolved inks, the ink set they were resolved for and the typography."""
	palette: Palette
	ink_set: str = DEFAULT_INK_SET
	preset: str = "classic"
	background: str = "white"
	# the typography: families we ship (FONT_FAMILIES), and a multiplier for text sizes
	font_body: str = "Lexend"
	font_heading: str = "Lexend"
	# the text of the overlays (the date in a corner): one font for all of them, so they look alike
	font_overlay: str = "Lexend"
	font_scale: float = 1.0

def _readable(text: str, behind: str) -> bool:
	"""Whether text of this ink can be read on that one: not the same ink, and neither yellow on white nor white on yellow (two light inks)."""
	return text != behind and {text, behind} != {"white", "yellow"}

def _first(chain: list[str], have: tuple[str, ...], ok=lambda ink: True) -> str|None:
	return next((ink for ink in chain if ink in have and ok(ink)), None)

def _fallback(page: str) -> str:
	"""The ink that always reads on the page: black on white, white on black."""
	return "white" if page == "black" else "black"

def _text_ink(chosen: str, have: tuple[str, ...], page: str) -> str:
	"""The ink for a text role: the chosen one if the panel has it and it reads on the page, else its nearest (orange: red), else black (white on a black page)."""
	chain = [chosen, "red"] if chosen == "orange" else [chosen]
	return _first(chain, have, lambda ink: _readable(ink, page)) or _fallback(page)

def _fill_ink(chosen: str, have: tuple[str, ...], page: str) -> str|None:
	"""The ink of the highlight: the chosen one, else red; for another color the panel has none like, black (white on a black page); None when it should be left unfilled (yellow with no yellow or red)."""
	if chosen == "yellow":
		return _first(["yellow", "red"], have, lambda ink: ink != page)
	return _first([chosen, "red", _fallback(page)], have, lambda ink: ink != page)

# these fills are light: the text on one is black (the rest are dark: white)
_LIGHT_FILLS = ("white", "yellow", "orange")

def resolve(settings: Mapping[str, Any]|None, ink_set: str) -> tuple[Palette, str, str]:
	"""
	The palette for theme settings on a panel with this ink set, with the preset and the background it used (a value that is missing or not valid reads as the factory default, with one warning).
	Every role is an ink of the set; no text role is the ink of the page it is on; yellow is never text on white and white never on yellow; and with no fill, `bg_fill` is the page and
	`text_on_fill` the main text, so a page still reads.
	"""
	settings = settings or {}
	have = INK_SETS.get(ink_set) or INK_SETS[DEFAULT_INK_SET]
	problems: list[str] = []
	preset = settings.get("preset")
	if preset not in PRESETS:
		if preset is not None:
			problems.append("preset")
		preset = str(DEFAULT_SETTINGS["preset"])
	background = settings.get("background")
	if background not in BACKGROUNDS:
		if background is not None:
			problems.append("background")
		background = str(DEFAULT_SETTINGS["background"])
	if problems:
		logger.warning(f"Theme settings: invalid {', '.join(problems)}; using the default for them")
	if preset == "custom":
		classic = PRESET_INKS["classic"] if background == "white" else BLACK_PAGE_INKS
		chosen: tuple[str, ...] = tuple(str(settings.get(key)) if settings.get(key) in INKS else classic[i] for i, key in enumerate(CUSTOM_KEYS))
	elif background == "black":
		chosen = BLACK_PAGE_MONO if preset == "mono" else BLACK_PAGE_INKS
	else:
		chosen = PRESET_INKS[preset]
	primary = _text_ink(chosen[0], have, background)
	secondary_1 = _text_ink(chosen[1], have, background)
	secondary_2 = _text_ink(chosen[2], have, background)
	fill = _fill_ink(chosen[3], have, background)
	if fill is None:
		fill_ink, on_fill = background, primary
	else:
		fill_ink = fill
		# the chosen text ink if the fill is the chosen one too, it reads on it and the panel has it; else black or white by how light the fill is
		wanted = chosen[4] if fill == chosen[3] and chosen[4] in have and _readable(chosen[4], fill) else None
		on_fill = wanted or _first(["black", "white"] if fill in _LIGHT_FILLS else ["white", "black"], have, lambda ink: _readable(ink, fill)) or _fallback(fill)
	palette = Palette(
		text_primary=primary, text_secondary_1=secondary_1, text_secondary_2=secondary_2,
		bg_page=background, bg_fill=fill_ink, text_on_fill=on_fill,
		bg_strong=primary, text_on_strong=background, text_outline=background,
	)
	return palette, str(preset), str(background)

def inputs_from(settings: Mapping[str, Any]|None, ink_set: str|None = None) -> ThemeInputs:
	"""The inputs for a theme settings document on a panel (the attached one's ink set, unless one is given); a missing or invalid value falls back to the factory default."""
	settings = settings or {}
	ink_set = ink_set or panel_ink_set()
	palette, preset, background = resolve(settings, ink_set)
	body = settings.get("fontBody")
	if body not in FONT_FAMILIES:
		if body is not None:
			logger.warning("Theme settings: the body font is not one we have; using the default")
		body = str(DEFAULT_SETTINGS["fontBody"])
	heading = settings.get("fontHeading")
	if heading not in FONT_FAMILIES:
		# unset: the headings wear the body font
		heading = body
	overlay = settings.get("fontOverlay")
	if overlay not in FONT_FAMILIES:
		# unset: the overlays wear the heading font
		overlay = heading
	scale = settings.get("fontScale")
	if not (isinstance(scale, (int, float)) and not isinstance(scale, bool) and FONT_SCALE_MIN <= scale <= FONT_SCALE_MAX):
		scale = float(DEFAULT_SETTINGS["fontScale"])
	return ThemeInputs(palette, ink_set, preset, background, font_body=str(body), font_heading=str(heading), font_overlay=str(overlay), font_scale=float(scale))

def _num(value: float) -> str:
	return f"{value:g}"

def hex_of(rgb: tuple[int, int, int]) -> str:
	return "#%02x%02x%02x" % rgb

def css_vars(inputs: ThemeInputs) -> str:
	"""The CSS custom properties themes.css reads, for a `:root { ... }` block: the drive color (exact `#rrggbb`) of each role, and the typography."""
	palette = inputs.palette
	values = { f"--ink-{role}": hex_of(palette.rgb(role)) for role in Palette.roles() if role not in ("bg-page", "text-outline") }
	values.update({
		# the page behind everything (the class `bg-page`) and the outline around overlay text (`text-outline`)
		"--page-bg": hex_of(palette.rgb("bg_page")),
		"--outline-color": hex_of(palette.rgb("text_outline")),
		# family names are ours (FONT_FAMILIES, plain identifiers), so they need no quotes: the page escapes quotes
		"--font-body": inputs.font_body,
		"--font-heading": inputs.font_heading,
		"--font-overlay": inputs.font_overlay,
		"--font-scale": _num(inputs.font_scale),
	})
	return " ".join(f"{name}: {value};" for name, value in values.items())

DEFAULT_INPUTS = inputs_from(DEFAULT_SETTINGS, DEFAULT_INK_SET)

def current_inputs(scm: SettingsConfigurationManager|None) -> ThemeInputs:
	"""The device theme now, for the panel that is attached: read on every call, so a change in the web app applies to the next render. Without settings, the factory default."""
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
	overlay: str
	scale: float

def typography_of(inputs: ThemeInputs) -> Typography:
	return Typography(inputs.font_body, inputs.font_heading, inputs.font_overlay, inputs.font_scale)

def current_typography(scm: SettingsConfigurationManager|None) -> Typography:
	"""The device's fonts now, read on every call like the palette."""
	return typography_of(current_inputs(scm))

def current_palette(scm: SettingsConfigurationManager|None) -> Palette:
	return current_inputs(scm).palette
