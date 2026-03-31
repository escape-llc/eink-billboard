from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from PIL import Image, ImageDraw, ImageFont

from ..task.display import DisplayImage

type ImageLayerInfo = tuple[Image.Image, str]
type RenderResult = tuple[bool, ImageLayerInfo|None]
class ImageOverlay:
	def __init__(self, image: Image.Image, position: tuple):
		self.image = image
		self.position = position
	pass

@dataclass(frozen=True)
class LayerStack:
	version: int
	background: DisplayImage|None
	overlays: list[ImageOverlay]
	forground: DisplayImage|None
	priority: DisplayImage|None

@runtime_checkable
class RenderPackage(Protocol):
	def render(self) -> RenderResult:
		return (False, None)

class SimpleRenderPackage(RenderPackage):
	def __init__(self, di: DisplayImage):
		self._di = di
	def render(self) -> RenderResult:
		return (True, (self._di.img.copy(), self._di.title))

class BgFgRenderPackage(RenderPackage):
	def __init__(self, bg: DisplayImage, fg: DisplayImage):
		self._bg = bg
		self._fg = fg
	def render(self) -> RenderResult:
		if self._bg is None and self._fg is None:
			return (False, None)
		elif self._bg is not None and self._fg is not None:
			img = Image.alpha_composite(self._bg.img.convert("RGBA"), self._fg.img.convert("RGBA"))
			return (True, (img, self._fg.title))
		elif self._bg is not None:
			return (True, (self._bg.img.copy(), self._bg.title))
		else:
			return (True, (self._fg.img.copy(), self._fg.title))

class ImageCompositor:
	def __init__(self):
		self._current_stack: LayerStack = LayerStack(0, None, [], None, None)
		self._startVersion = 0
	@property
	def current_version(self) -> int:
		return self._current_stack.version
	def set_layer_background(self, image: DisplayImage|None) -> LayerStack:
		previous = self._current_stack
		self._current_stack = LayerStack(previous.version + 1, image, previous.overlays, previous.forground, previous.priority)
		return previous
	def set_layer_overlays(self, overlays: list[ImageOverlay]) -> LayerStack:
		previous = self._current_stack
		self._current_stack = LayerStack(previous.version + 1, previous.background, overlays, previous.forground, previous.priority)
		return previous
	def set_layer_forground(self, image: DisplayImage|None) -> LayerStack:
		previous = self._current_stack
		self._current_stack = LayerStack(previous.version + 1, previous.background, previous.overlays, image, previous.priority)
		return previous
	def set_layer_priority(self, image: DisplayImage|None) -> LayerStack:
		previous = self._current_stack
		self._current_stack = LayerStack(previous.version + 1, previous.background, previous.overlays, previous.forground, image)
		return previous
	def is_dirty(self) -> bool:
		return self._startVersion != self._current_stack.version
	def render(self) -> RenderPackage|None:
		if not self.is_dirty():
			return None
		self._startVersion = self._current_stack.version
		if self._current_stack.priority is not None:
			return SimpleRenderPackage(self._current_stack.priority)
#		elif self._current_stack.forground is not None and self._current_stack.background is not None:
#			return BgFgRenderPackage(self._current_stack.background, self._current_stack.forground)
		elif self._current_stack.forground is not None:
			return SimpleRenderPackage(self._current_stack.forground)
		elif self._current_stack.background is not None:
			return SimpleRenderPackage(self._current_stack.background)
		return None