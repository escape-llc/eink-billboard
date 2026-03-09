from PIL import Image, ImageDraw, ImageFont

class ImageOverlay:
	def __init__(self, image: Image.Image, position: tuple):
		self.image = image
		self.position = position
	pass
class ImageCompositor:
	def __init__(self):
		self._version = 0
		self._startVersion = 0
		self.layer_background = None
		self.layer_overlays:list[ImageOverlay] = []
		self.layer_forground = None
		self.layer_priority = None
		self.composited_image = None
	def set_layer_background(self, image: Image.Image) -> int:
		self.layer_background = image
		self._version += 1
		return self._version
	def set_layer_overlays(self, overlays: list[ImageOverlay]) -> int:
		self.layer_overlays = overlays
		self._version += 1
		return self._version
	def set_layer_forground(self, image: Image.Image) -> int:
		self.layer_forground = image
		self._version += 1
		return self._version
	def set_layer_priority(self, image: Image.Image) -> int:
		self.layer_priority = image
		self._version += 1
		return self._version
	def is_dirty(self) -> bool:
		return self._startVersion != self._version
	def render(self) -> tuple[bool, Image.Image|None]:
		if self._startVersion == self._version:
			return (False, self.composited_image)
		final_image = None
		if self.layer_priority is not None:
			final_image = self.layer_priority.copy()
		elif self.layer_forground is not None:
			final_image = self.layer_forground.copy()
			# TODO if foreground has transparcency, composite onto background in "lighten" mode
		elif self.layer_background is not None:
			final_image = self.layer_background.copy()
			# add overlays
			for ovl in self.layer_overlays:
				# TODO composite overlay onto final_image
				pass
		self.composited_image = final_image
		self._startVersion = self._version
		return (True, final_image)