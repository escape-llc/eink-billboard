"""
The zones of the screen an overlay can be placed in: six fixed boxes, three across the top and three across the bottom.

A zone is laid out as the viewer sees the screen (in portrait, the panel is turned), and also carries its box on the panel itself,
where the compositor draws. The display announces the zones at startup (DisplaySettings.overlays); a plugin renders for a zone's size.
"""
from dataclasses import dataclass

from .display_messages import OverlayDefinition

ZONE_NAMES = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")

type Box = tuple[int, int, int, int]

@dataclass(frozen=True, slots=True)
class Zone:
	index: int
	name: str
	title: str
	# as the viewer sees it
	size: tuple[int, int]
	viewer_box: Box
	# on the panel: where the compositor draws, and whether the image must be turned like the backgrounds are
	panel_box: Box
	portrait: bool
	def definition(self) -> OverlayDefinition:
		return OverlayDefinition(self.index, self.title, self.size, self.name)

def zones_for(resolution: tuple[int, int], orientation: str) -> list[Zone]:
	"""The six zones for a panel of `resolution` (its own width and height) shown in `orientation` ("landscape" or "portrait")."""
	panel_width, panel_height = resolution
	portrait = orientation == "portrait"
	width, height = (panel_height, panel_width) if portrait else (panel_width, panel_height)
	margin = max(1, round(min(width, height) * 0.02))
	cell = width // 3
	zone_height = height // 5
	zones: list[Zone] = []
	for index, name in enumerate(ZONE_NAMES):
		row, column = divmod(index, 3)
		x0, x1 = column * cell + margin, (column + 1) * cell - margin
		y0, y1 = (margin, margin + zone_height) if row == 0 else (height - margin - zone_height, height - margin)
		viewer: Box = (x0, y0, x1, y1)
		# the panel shows a portrait page turned a quarter counter-clockwise (change_orientation): viewer (x, y) is panel (y, width - x)
		panel: Box = (y0, width - x1, y1, width - x0) if portrait else viewer
		title = name.replace("-", " ").capitalize()
		zones.append(Zone(index, name, title, (x1 - x0, y1 - y0), viewer, panel, portrait))
	return zones
