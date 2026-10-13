from dataclasses import dataclass, replace
from typing import Mapping, Protocol, runtime_checkable
from PIL import Image

from ..task.display_messages import DisplayImage

@dataclass(frozen=True, eq=False)
class ImageOverlay:
	"""An image drawn over the background at `position` (top-left, in background pixels). What it does not draw is transparent; an outline that keeps
	its text readable over a busy picture is part of the image (the data source draws it, e.g. the Today page's outlined text)."""
	image: Image.Image
	position: tuple[int, int]
	# who made it (the telemetry says so); see python/task/source_router.py
	origin: Mapping[str, str]|None = None

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
	def layers(self) -> list[dict]:
		"""What `commit` draws now, back to front, as `{ layer, title }` (the overlays as `{ layer: "overlays", count }`): what the telemetry says was shown."""
		stack = self._current_stack
		def entry(layer: str, di: DisplayImage) -> dict:
			return { "layer": layer, "title": di.title, **({ "origin": dict(di.origin) } if di.origin else {}) }
		if stack.priority is not None:
			return [entry("priority", stack.priority)]
		if stack.forground is not None and stack.forground.layer != "blend":
			return [entry("override", stack.forground)]
		shown: list[dict] = [entry("background", stack.background)] if stack.background is not None else []
		if stack.forground is not None:
			shown.append(entry("blend", stack.forground))
		if stack.blend is not None:
			shown.append(entry("timer-blend", stack.blend))
		if len(shown) == 1 and stack.background is not None and stack.overlays:
			origins = [dict(o.origin) for o in stack.overlays if o.origin]
			shown.append({ "layer": "overlays", "count": len(stack.overlays), **({ "origins": origins } if origins else {}) })
		return shown
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