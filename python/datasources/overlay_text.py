"""
Text for an overlay zone, drawn by Chromium as SVG on a transparent page (`static/render/overlay-text.html`): the way an overlay data source draws (#239).

The text wears the theme: the family is the theme's overlay font (`fontOverlay`, the same for every overlay), each run a text role's color, and an
outline in the theme's outline color (`text-outline`: white, or black on a black page) keeps it readable over a busy picture. The outline is a hard
stroke drawn under the letters (no blur, no gradient, which a color e-ink panel dithers into dots). Its width is the task's `outline` (0 to 1) times
a fraction of the text size, so it is the same weight in every zone.

A block is one or more lines (each of runs), with an optional drawing before it (a weather icon) as tall as the block, outlined the same way.
The page cannot run a script to fit the text, so the size is chosen here: the lines are measured with PIL in the same font file Chromium draws them with.
"""
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from PIL import Image, ImageFont

from ..model.configuration_manager import StaticConfigurationManager
from ..model.theme import ThemeInputs
from ..plugins.plugin_base import PermanentError, RenderSession

# the full outline's width (the whole stroke; half of it shows outside the letters) and a heavy weight's own-color stroke, as fractions of the text size
OUTLINE_WIDTH = 0.2
HEAVY_WIDTH = 0.044
# the gap between the drawing and the text, and how much taller than the text block the drawing is (centered on it), as fractions of the text size
ICON_GAP = 0.3
ICON_BLEED = 0.6
WEIGHTS = ("normal", "bold", "heavy")

type Run = tuple[str, str]
"""Text and its role, a text class of themes.css (`text-primary`, `text-secondary-1`, ...)."""

@dataclass(frozen=True, slots=True)
class OverlayIcon:
	"""A line drawing before the text: its strokes (`body`, in a `grid` square, no fill), their width in that grid, and the role of its color."""
	body: str
	weight: float
	role: str = "text-secondary-2"
	grid: int = 64

@dataclass(frozen=True, slots=True)
class PlacedLine:
	x: float
	baseline: float

@dataclass(frozen=True, slots=True)
class OverlayBlock:
	"""Where and how big the block is drawn, in page pixels: the font size, each line's start and baseline, the stroke widths, and the icon's square."""
	font_px: int
	lines: tuple[PlacedLine, ...]
	outline_px: float
	heavy_px: float
	icon_box: tuple[float, float, float]|None = None   # x, y, size

	@property
	def baseline(self) -> float:
		"""The first line's baseline."""
		return self.lines[0].baseline

def outline_factor(params: Mapping[str, Any]) -> float:
	"""The task's `outline` (the Overlay plugin's setting), 0 to 1; unset (a task from before it existed) is the full outline."""
	value = params.get("outline")
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		return min(max(float(value), 0.0), 1.0)
	return 1.0

def overlay_margin(params: Mapping[str, Any], default: int = 6) -> int:
	"""The task's `offset`: how far the text is from the screen's edge, in pixels."""
	offset = params.get("offset")
	return int(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool) and offset >= 0 else default

def zone_valign(params: Mapping[str, Any]) -> str:
	"""The zones are bands along the top and the bottom of the screen: the text sits near the screen's edge, not in the middle of the band."""
	zone = str(params.get("zone") or "")
	return "top" if zone.startswith("top") else "bottom" if zone.startswith("bottom") else "center"

def fit_block(lines: list[str], size: tuple[int, int], font_for: Callable[[int], ImageFont.FreeTypeFont], outline: float, heavy: bool, valign: str = "center", margin: int = 0,
		icon: bool = False, min_font_px: int = 8) -> OverlayBlock:
	"""
	The largest size (from 60% of the box's height, shared by the lines, down to `min_font_px`) at which the block, its outline and its icon included, fits in the
	`size` box; at the minimum it is clipped. `font_for(px)` is the PIL font Chromium will draw with. `valign` puts the block's ink `margin` pixels from the `top` or
	`bottom` edge (the outline included, so it is not cut at the screen's edge), or in the `center`. The block is centered across; its lines start at one edge.
	"""
	width, height = size
	count = max(1, len(lines))
	start = max(min_font_px, int(height * 0.6 / count))
	for px in range(start, min_font_px - 1, -1):
		font = font_for(px)
		ascent, descent = font.getmetrics()
		advance = ascent + descent
		boxes = [font.getbbox(line or " ", anchor="ls") for line in lines]
		top = boxes[0][1]
		bottom = (count - 1) * advance + boxes[-1][3]
		block_h = bottom - top
		text_w = max(b[2] - b[0] for b in boxes)
		# the drawing is a little taller than the text, centered on it: what it reaches past the text counts in the fit and at the edge
		side = block_h + px * ICON_BLEED if icon else 0.0
		bleed = (side - block_h) / 2 if icon else 0.0
		icon_w = side + px * ICON_GAP if icon else 0.0
		stroke = px * (OUTLINE_WIDTH * outline + (HEAVY_WIDTH if heavy else 0.0))
		if (text_w + icon_w + stroke <= width and block_h + 2 * bleed + stroke <= height) or px == min_font_px:
			break
	half = stroke / 2
	if valign == "top":
		first = margin + half + bleed - top
	elif valign == "bottom":
		first = height - margin - half - bleed - bottom
	else:
		first = (height - block_h) / 2 - top
	left = (width - (text_w + icon_w)) / 2
	text_left = left + icon_w
	placed = tuple(PlacedLine(text_left - b[0], first + i * advance) for i, b in enumerate(boxes))
	icon_box = (left, first + top - bleed, side) if icon else None
	return OverlayBlock(px, placed, px * OUTLINE_WIDTH * outline, px * HEAVY_WIDTH if heavy else 0.0, icon_box)

def fit_line(line: str, size: tuple[int, int], font_for: Callable[[int], ImageFont.FreeTypeFont], outline: float, heavy: bool, valign: str = "center", margin: int = 0, min_font_px: int = 8) -> OverlayBlock:
	"""One line: `fit_block` with nothing before it."""
	return fit_block([line], size, font_for, outline, heavy, valign, margin, False, min_font_px)

MIN_READABLE_PX = 16

def lines_that_fit(stm: StaticConfigurationManager, theme: ThemeInputs, size: tuple[int, int], texts: list[str], outline: float, weight: str = "bold",
		valign: str = "center", margin: int = 0, min_px: int = MIN_READABLE_PX) -> int:
	"""How many of `texts` (from the first) the zone shows at a readable size (`min_px`, at least one): the text is measured as `render_overlay` will draw it."""
	face = "normal" if weight == "normal" else "bold"
	for count in range(len(texts), 1, -1):
		block = fit_block(texts[:count], size, lambda px: stm.get_font(theme.font_overlay, px, face), outline, weight == "heavy", valign, margin)
		if block.font_px >= min_px:
			return count
	return min(1, len(texts))

def render_overlay(stm: StaticConfigurationManager, theme: ThemeInputs, size: tuple[int, int], lines: list[list[Run]], outline: float, weight: str = "bold",
		valign: str = "center", margin: int = 0, icon: OverlayIcon|None = None) -> Image.Image:
	"""
	A block of `lines`, each of runs drawn one after another, with an optional `icon` before it. Blocking (runs Chromium).
	A page Chromium does not draw is an error: the layer shows its error page in the zone.
	"""
	if weight not in WEIGHTS:
		raise PermanentError(f"Unknown weight '{weight}' (one of {', '.join(WEIGHTS)})")
	face = "normal" if weight == "normal" else "bold"
	family = theme.font_overlay
	texts = ["".join(text for text, _ in runs) for runs in lines]
	block = fit_block(texts, size, lambda px: stm.get_font(family, px, face), outline, weight == "heavy", valign, margin, icon is not None)
	icon_params = None
	if icon is not None and block.icon_box is not None:
		x, y, side = block.icon_box
		scale = side / icon.grid
		# the outline is as wide on the drawing as on the letters: in the drawing's grid, the line plus the outline's stroke
		icon_params = { "body": icon.body, "role": icon.role, "x": round(x, 2), "y": round(y, 2), "scale": round(scale, 4),
			"weight": icon.weight, "outline": round(icon.weight + block.outline_px / scale, 3) if block.outline_px > 0 else 0 }
	render_dir = os.path.join(stm.ROOT_PATH, "render")
	image = RenderSession(stm, render_dir, "overlay-text.html", theme).render(size, {
		"settings": {},
		"lines": [{ "runs": runs, "text": text, "x": round(p.x, 2), "baseline": round(p.baseline, 2) } for runs, text, p in zip(lines, texts, block.lines, strict=True)],
		"icon": icon_params,
		"font_px": block.font_px,
		"outline_px": round(block.outline_px, 2),
		"heavy_px": round(block.heavy_px, 2),
		"font_weight": face,
	}, transparent=True)
	if image is None:
		raise RuntimeError("The overlay's text could not be drawn")
	return image.convert("RGBA")

def render_overlay_text(stm: StaticConfigurationManager, theme: ThemeInputs, size: tuple[int, int], runs: list[Run], outline: float, weight: str = "bold", valign: str = "center", margin: int = 0) -> Image.Image:
	"""One line of runs (the Today data source)."""
	return render_overlay(stm, theme, size, [runs], outline, weight, valign, margin)
