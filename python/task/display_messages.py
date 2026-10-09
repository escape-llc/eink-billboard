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
class ComputedImage(DisplayImage):
	source: DisplayImage | PriorityImage

@dataclass(frozen=True, slots=True)
class OverlayDefinition:
	"""A zone of the screen an overlay can be placed in (python/task/overlay_zones.py). `dimensions` is the size as the viewer sees it (portrait-aware)."""
	index: int
	title: str
	dimensions: tuple[int, int]
	name: str = ""

class OverlayZones:
	"""The zones the display announced (DisplaySettings.overlays), by name: what an overlay plugin renders for."""
	def __init__(self, zones: list[OverlayDefinition]):
		self._zones = { zone.name: zone for zone in zones }
	def get(self, name: str) -> OverlayDefinition | None:
		return self._zones.get(name)
	def names(self) -> list[str]:
		return list(self._zones)

@dataclass(frozen=True, slots=True)
class OverlayImage(BasicMessage):
	"""Show `img` in the zone `zone` until the same `key` (normally the timer task's id) replaces or revokes it. `wash` lightens the background under it (0 to 1)."""
	key: str
	zone: str
	title: str
	img: Image.Image
	wash: float = 0.0

@dataclass(frozen=True, slots=True)
class OverlayRevoke(BasicMessage):
	"""Take down the overlay `key` put up, wherever it is. Nothing happens when it has none."""
	key: str

@dataclass(frozen=True, slots=True)
class DisplaySettings(BasicMessage):
	"""
	Notify tasks of the current display settings.
	"""
	name: str
	width: int
	height: int
	overlays: list[OverlayDefinition]
