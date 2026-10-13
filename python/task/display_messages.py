from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Mapping
from PIL import Image

from .messages import BasicMessage

# how a playlist page is shown (the readme's "Display Architecture"):
# - "background": the page, with the overlays drawn on it when nothing above it is showing;
# - "blend": washes over the current background (the previous page), hiding the overlays;
# - "override": obscures everything under it (only a priority image is drawn over it).
type DisplayLayer = Literal["background", "blend", "override"]
DISPLAY_LAYERS: tuple[DisplayLayer, ...] = ("background", "blend", "override")

@dataclass(frozen=True, slots=True)
class DisplayImage(BasicMessage):
	"""
	A playlist page. A `background` page ends the page above it (a blend or override), so the next background track, an error page
	or "Playback stopped" is never hidden behind an old one; a `blend` or `override` page replaces the one before it and keeps the background.
	"""
	title: str
	img: Image.Image
	layer: DisplayLayer = field(default="background", kw_only=True)
	# who made the image (see source_router.py): `kind`, `title`, `plugin`, and the playlist's `name`; None when nobody says
	origin: Mapping[str, str]|None = field(default=None, kw_only=True)

@dataclass(frozen=True, slots=True)
class PriorityImage(DisplayImage):
	duration: timedelta

@dataclass(frozen=True, slots=True)
class PriorityRevoke(BasicMessage):
	"""Take down the priority image titled `title` (the one showing, or one still queued) before its time is up. Nothing happens when there is none."""
	title: str

@dataclass(frozen=True, slots=True)
class BlendImage(DisplayImage):
	"""A timer task's image that washes over the current background for `duration`, hiding the overlays meanwhile. Blends queue like priority images."""
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
	"""Show `img` in the zone `zone` until the same `key` (normally the timer task's id) replaces or revokes it. What it does not draw is transparent."""
	key: str
	zone: str
	title: str
	img: Image.Image
	origin: Mapping[str, str]|None = None

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
