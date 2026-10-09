from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from PIL import Image, ImageDraw, ImageFont

from ..task.display_messages import DisplayImage

@dataclass(frozen=True, eq=False)
class ImageOverlay:
	"""An image drawn over the background at `position` (top-left, in background pixels).
	`wash` (0 to 1) lightens the background under the overlay toward white first, so light text reads over a busy picture (0.4 is a good start)."""
	image: Image.Image
	position: tuple[int, int]
	wash: float = 0.0

FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

def _sized(font: FontType|None, size: int) -> FontType:
	if font is None:
		return ImageFont.load_default(size=size)
	if isinstance(font, ImageFont.FreeTypeFont):
		return font.font_variant(size=size)
	return font # a bitmap font has one size

type TextRun = tuple[str, tuple[int, ...]]

def text_overlay(text: str|list[TextRun], size: tuple[int, int], position: tuple[int, int], font: FontType|None = None, color: tuple[int, ...] = (255, 255, 255), wash: float = 0.0, max_font_size: int = 48, min_font_size: int = 8) -> ImageOverlay:
	"""Text centered in a transparent `size` box, on one line. `text` is a string in `color`, or runs of `(text, color)` drawn one after another
	(e.g. a highlighted word). The font is shrunk (from its own size, or `max_font_size`, down to `min_font_size`) until the line fits;
	if it still does not fit at the minimum, it is clipped to the box. `font` is normally StaticConfigurationManager.get_font(...); without one the default font is used."""
	runs: list[TextRun] = [(text, color)] if isinstance(text, str) else list(text)
	line = "".join(part for part, _ in runs)
	width, height = size
	canvas = Image.new("RGBA", size, (255, 255, 255, 0))
	draw = ImageDraw.Draw(canvas)
	start = int(font.size) if isinstance(font, ImageFont.FreeTypeFont) else max_font_size
	chosen = _sized(font, min_font_size)
	box = draw.textbbox((0, 0), line, font=chosen)
	for n in range(max(start, min_font_size), min_font_size - 1, -1):
		candidate = _sized(font, n)
		candidate_box = draw.textbbox((0, 0), line, font=candidate)
		chosen, box = candidate, candidate_box
		if candidate_box[2] - candidate_box[0] <= width and candidate_box[3] - candidate_box[1] <= height:
			break
	# the bounding box does not start at the origin (side bearing, ascent): offset by it to center the ink, not the origin
	x = (width - (box[2] - box[0])) // 2 - box[0]
	y = (height - (box[3] - box[1])) // 2 - box[1]
	# each run starts where the line so far ends (measured on the whole prefix, so the spacing is the same as one string's)
	drawn = ""
	for part, part_color in runs:
		draw.text((x + draw.textlength(drawn, font=chosen), y), part, fill=part_color, font=chosen)
		drawn += part
	return ImageOverlay(canvas, position, wash)

type LayerStackOp = tuple["LayerStack", "LayerStack"]
@dataclass(frozen=True)
class LayerStack:
	version: int
	background: DisplayImage|None
	overlays: list[ImageOverlay]
	forground: DisplayImage|None
	priority: DisplayImage|None
	def set_foreground(self, di: DisplayImage|None) -> LayerStackOp:
		return (self, LayerStack(self.version + 1, self.background, self.overlays, di, self.priority))
	def set_background(self, di: DisplayImage|None) -> LayerStackOp:
		return (self, LayerStack(self.version + 1, di, self.overlays, self.forground, self.priority))
	def set_priority(self, di: DisplayImage|None) -> LayerStackOp:
		return (self, LayerStack(self.version + 1, self.background, self.overlays, self.forground, di))
	def set_overlays(self, overlays: list[ImageOverlay]) -> LayerStackOp:
		return (self, LayerStack(self.version + 1, self.background, overlays, self.forground, self.priority))

type RenderInfo = tuple[Image.Image, str]
@runtime_checkable
class RenderPackage(Protocol):
	def render(self) -> RenderInfo:
		...
	@property
	def version(self) -> int:
		...

class SimpleRenderPackage(RenderPackage):
	def __init__(self, version:int, di: DisplayImage):
		if di is None:
			raise ValueError("SimpleRenderPackage requires a DisplayImage")
		self._version = version
		self._di = di
	@property
	def version(self) -> int:
		return self._version
	def render(self) -> RenderInfo:
		return (self._di.img.copy(), self._di.title)

class BgFgRenderPackage(RenderPackage):
	def __init__(self, version:int, bg: DisplayImage, fg: DisplayImage):
		if bg is None or fg is None:
			raise ValueError("BgFgRenderPackage requires both background and foreground images")
		if bg.img.size != fg.img.size:
			raise ValueError("BgFgRenderPackage requires background and foreground images to be the same size")
		self._version = version
		self._bg = bg
		self._fg = fg
	@property
	def version(self) -> int:
		return self._version
	def render(self) -> RenderInfo:
		img = Image.alpha_composite(self._bg.img.convert("RGBA"), self._fg.img.convert("RGBA"))
		return (img, self._fg.title)

class OverlayRenderPackage(RenderPackage):
	"""The background with the overlays drawn over it, in order; the title is the background's."""
	def __init__(self, version:int, base: DisplayImage, overlays: list[ImageOverlay]):
		if base is None:
			raise ValueError("OverlayRenderPackage requires a background image")
		self._version = version
		self._base = base
		self._overlays = list(overlays)
	@property
	def version(self) -> int:
		return self._version
	def render(self) -> RenderInfo:
		canvas = self._base.img.convert("RGBA")
		for overlay in self._overlays:
			picture = overlay.image.convert("RGBA")
			x, y = overlay.position
			# the part of the overlay that lies on the background: one that hangs off the edge is cut, not an error
			left, top = max(x, 0), max(y, 0)
			right, bottom = min(x + picture.width, canvas.width), min(y + picture.height, canvas.height)
			if right <= left or bottom <= top:
				continue
			if overlay.wash > 0:
				region = canvas.crop((left, top, right, bottom))
				# CSS "lighten" against white is white, so the wash is a blend toward white; the background's own transparency is kept
				washed = Image.blend(region.convert("RGB"), Image.new("RGB", region.size, (255, 255, 255)), min(overlay.wash, 1.0)).convert("RGBA")
				washed.putalpha(region.getchannel("A"))
				canvas.paste(washed, (left, top))
			canvas.alpha_composite(picture.crop((left - x, top - y, right - x, bottom - y)), (left, top))
		return (canvas.convert(self._base.img.mode), self._base.title)

class ImageCompositor:
	def __init__(self):
		self._current_stack: LayerStack = LayerStack(0, None, [], None, None)
		self._startVersion = self._current_stack.version
	@property
	def current_version(self) -> int:
		return self._current_stack.version
	def set_layer_background(self, bk: DisplayImage|None) -> LayerStackOp:
		previous, self._current_stack = self._current_stack.set_background(bk)
		return (previous, self._current_stack)
	def set_layer_overlays(self, overlays: list[ImageOverlay]) -> LayerStackOp:
		previous, self._current_stack = self._current_stack.set_overlays(overlays)
		return (previous, self._current_stack)
	def set_layer_forground(self, fg: DisplayImage|None) -> LayerStackOp:
		previous, self._current_stack = self._current_stack.set_foreground(fg)
		return (previous, self._current_stack)
	def set_layer_priority(self, pri: DisplayImage|None) -> LayerStackOp:
		previous, self._current_stack = self._current_stack.set_priority(pri)
		return (previous, self._current_stack)
	def is_dirty(self) -> bool:
		return self._startVersion != self._current_stack.version
	def commit(self) -> RenderPackage|None:
		if not self.is_dirty():
			return None
		self._startVersion = self._current_stack.version
		if self._current_stack.priority is not None:
			return SimpleRenderPackage(self._current_stack.version, self._current_stack.priority)
#		elif self._current_stack.forground is not None and self._current_stack.background is not None:
#			return BgFgRenderPackage(self._current_stack.version, self._current_stack.background, self._current_stack.forground)
		elif self._current_stack.forground is not None:
			return SimpleRenderPackage(self._current_stack.version, self._current_stack.forground)
		elif self._current_stack.background is not None and self._current_stack.overlays:
			return OverlayRenderPackage(self._current_stack.version, self._current_stack.background, self._current_stack.overlays)
		elif self._current_stack.background is not None:
			return SimpleRenderPackage(self._current_stack.version, self._current_stack.background)
		return None