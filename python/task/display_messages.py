from dataclasses import dataclass
from datetime import timedelta
from PIL import Image

from .messages import BasicMessage

@dataclass(frozen=True, slots=True)
class DisplayImage(BasicMessage):
	title: str
	img: Image.Image

@dataclass(frozen=True, slots=True)
class PriorityImage(DisplayImage):
	duration: timedelta

@dataclass(frozen=True, slots=True)
class OverlayDefinition:
	index: int
	title: str
	dimensions: tuple[int, int]

@dataclass(frozen=True, slots=True)
class DisplaySettings(BasicMessage):
	"""
	Notify tasks of the current display settings.
	"""
	name: str
	width: int
	height: int
	overlays: list[OverlayDefinition]
