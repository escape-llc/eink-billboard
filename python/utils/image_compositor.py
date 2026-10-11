from dataclasses import dataclass, replace
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
	"""
	The layers (the readme's "Display Architecture"). What is shown, back to front:
	- `background`, or the theme's color when there is none;
	- `forground`, the playlist's page above the background: an `override` page is shown alone (on the theme's color) and nothing below it is
	  drawn; a `blend` page washes over the background;
	- `blend`, a timer task's image for a while, washing over what is under it (a playlist override hides it);
	- the `overlays`, only when nothing above the background is showing;
	- `priority`, over everything.
	"""
	version: int
	background: DisplayImage|None
	overlays: list[ImageOverlay]
	forground: DisplayImage|None
	priority: DisplayImage|None
	blend: DisplayImage|None = None
	def _with(self, **changes) -> LayerStackOp:
		return (self, replace(self, version=self.version + 1, **changes))
	def set_foreground(self, di: DisplayImage|None) -> LayerStackOp:
		return self._with(forground=di)
	def set_background(self, di: DisplayImage|None) -> LayerStackOp:
		return self._with(background=di)
	def set_priority(self, di: DisplayImage|None) -> LayerStackOp:
		return self._with(priority=di)
	def set_blend(self, di: DisplayImage|None) -> LayerStackOp:
		return self._with(blend=di)
	def set_overlays(self, overlays: list[ImageOverlay]) -> LayerStackOp:
		return self._with(overlays=overlays)

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

class StackRenderPackage(RenderPackage):
	"""
	Images alpha-composited in order over a base: the background, or the theme's color (`fill`) when there is none. What is transparent in an
	image shows what is under it; an opaque one covers it. The title is the top image's. A layer of another size than the base is fitted to it.
	"""
	def __init__(self, version:int, base: DisplayImage|None, layers: list[DisplayImage], fill: tuple[int, int, int]):
		if not layers:
			raise ValueError("StackRenderPackage requires at least one image to draw")
		self._version = version
		self._base = base
		self._layers = list(layers)
		self._fill = fill
	@property
	def version(self) -> int:
		return self._version
	def render(self) -> RenderInfo:
		size = self._base.img.size if self._base is not None else self._layers[0].img.size
		canvas = self._base.img.convert("RGBA") if self._base is not None else Image.new("RGBA", size, (*self._fill, 255))
		for layer in self._layers:
			picture = layer.img.convert("RGBA")
			if picture.size != size:
				picture = picture.resize(size)
			canvas.alpha_composite(picture)
		mode = self._base.img.mode if self._base is not None and self._base.img.mode in ("RGB", "RGBA", "L") else "RGB"
		return (canvas.convert(mode), self._layers[-1].title)

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
		# the theme's background color, under a page that has no background (or transparency over nothing); the display sets it before each commit
		self.fill: tuple[int, int, int] = (255, 255, 255)
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
	def set_layer_blend(self, blend: DisplayImage|None) -> LayerStackOp:
		previous, self._current_stack = self._current_stack.set_blend(blend)
		return (previous, self._current_stack)
	def is_dirty(self) -> bool:
		return self._startVersion != self._current_stack.version
	def commit(self) -> RenderPackage|None:
		if not self.is_dirty():
			return None
		self._startVersion = self._current_stack.version
		stack = self._current_stack
		if stack.priority is not None:
			return SimpleRenderPackage(stack.version, stack.priority)
		if stack.forground is not None and stack.forground.layer != "blend":
			# obscures everything under it, a timer blend included; transparency shows the theme's color, not the background
			return StackRenderPackage(stack.version, None, [stack.forground], self.fill)
		washes = [di for di in (stack.forground, stack.blend) if di is not None]
		if washes:
			# a playlist blend page and then a timer blend, over the background; the overlays are not drawn
			return StackRenderPackage(stack.version, stack.background, washes, self.fill)
		if stack.background is not None and stack.overlays:
			return OverlayRenderPackage(stack.version, stack.background, stack.overlays)
		if stack.background is not None:
			return SimpleRenderPackage(stack.version, stack.background)
		return None