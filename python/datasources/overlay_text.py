"""
A line of text for an overlay zone, drawn by Chromium as SVG on a transparent page (`static/render/overlay-text.html`).

The text wears the theme: the family is the theme's overlay font (`fontOverlay`, the same for every overlay), each run a text role's color, and an
outline in the theme's outline color (`text-outline`: white, or black on a black page) keeps it readable over a busy picture. The outline is a hard
stroke drawn under the letters (no blur, no gradient, which a color e-ink panel dithers into dots). Its width is the task's `outline` (0 to 1) times
a fraction of the text size, so it is the same weight in every zone.

The page cannot run a script to fit the text, so the size is chosen here: the line is measured with PIL in the same font file Chromium draws it with.
"""
import os
from dataclasses import dataclass
from typing import Any, Mapping

from PIL import Image, ImageFont

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import ThemeInputs
from ..plugins.plugin_base import PermanentError, RenderSession

# the full outline's width (the whole stroke; half of it shows outside the letters) and a heavy weight's own-color stroke, as fractions of the text size
OUTLINE_WIDTH = 0.2
HEAVY_WIDTH = 0.044
WEIGHTS = ("normal", "bold", "heavy")

@dataclass(frozen=True, slots=True)
class OverlayLine:
	"""Where and how big the line is drawn, in page pixels: the font size, the baseline, and the stroke widths."""
	font_px: int
	baseline: float
	outline_px: float
	heavy_px: float

def outline_factor(params: Mapping[str, Any]) -> float:
	"""The task's `outline` (the Overlay plugin's setting), 0 to 1; unset (a task from before it existed) is the full outline."""
	value = params.get("outline")
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		return min(max(float(value), 0.0), 1.0)
	return 1.0

def fit_line(line: str, size: tuple[int, int], font_for, outline: float, heavy: bool, valign: str = "center", margin: int = 0, min_font_px: int = 8) -> OverlayLine:
	"""
	The largest size (from 60% of the box's height down to `min_font_px`) at which `line`, its outline included, fits in the `size` box;
	at the minimum it is clipped. `font_for(px)` is the PIL font Chromium will draw with. `valign` puts the ink `margin` pixels from the `top` or
	`bottom` edge (the outline included, so it is not cut at the screen's edge), or in the `center`.
	"""
	width, height = size
	start = max(min_font_px, int(height * 0.6))
	for px in range(start, min_font_px - 1, -1):
		font: ImageFont.FreeTypeFont = font_for(px)
		left, top, right, bottom = font.getbbox(line, anchor="ls")
		stroke = px * (OUTLINE_WIDTH * outline + (HEAVY_WIDTH if heavy else 0.0))
		if right - left + stroke <= width and bottom - top + stroke <= height or px == min_font_px:
			break
	half = stroke / 2
	if valign == "top":
		baseline = margin + half - top
	elif valign == "bottom":
		baseline = height - margin - half - bottom
	else:
		baseline = (height - (bottom - top)) / 2 - top
	return OverlayLine(px, baseline, px * OUTLINE_WIDTH * outline, px * HEAVY_WIDTH if heavy else 0.0)

def render_overlay_text(stm: StaticConfigurationManager, theme: ThemeInputs, size: tuple[int, int], runs: list[tuple[str, str]], outline: float, weight: str = "bold", valign: str = "center", margin: int = 0) -> Image.Image:
	"""
	`runs` are `(text, role)` drawn one after another on one line, the role a text class of themes.css (`text-primary`, `text-secondary-1`, ...).
	Blocking (runs Chromium). A page Chromium does not draw is an error: the layer shows its error page in the zone.
	"""
	if weight not in WEIGHTS:
		raise PermanentError(f"Unknown weight '{weight}' (one of {', '.join(WEIGHTS)})")
	face = "normal" if weight == "normal" else "bold"
	family = theme.font_overlay
	line = "".join(text for text, _ in runs)
	placed = fit_line(line, size, lambda px: stm.get_font(family, px, face), outline, weight == "heavy", valign, margin)
	render_dir = os.path.join(stm.ROOT_PATH, "render")
	image = RenderSession(stm, render_dir, "overlay-text.html", theme).render(size, {
		"settings": {},
		"runs": runs,
		"line": line,
		"font_px": placed.font_px,
		"baseline": round(placed.baseline, 2),
		"outline_px": round(placed.outline_px, 2),
		"heavy_px": round(placed.heavy_px, 2),
		"font_weight": face,
	}, transparent=True)
	if image is None:
		raise RuntimeError("The overlay's text could not be drawn")
	return image.convert("RGBA")
