from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from PIL import Image, ImageDraw, ImageFont

from ..task.display import DisplayImage

class ImageOverlay:
	def __init__(self, image: Image.Image, position: tuple):
		self.image = image
		self.position = position
	pass

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
		elif self._current_stack.background is not None:
			return SimpleRenderPackage(self._current_stack.version, self._current_stack.background)
		return None