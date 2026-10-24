"""
The drawings of the sky (#619): the moon at its phase and the paths of the sun and the moon across the sky, as SVG made here from our own numbers, so a
page may put them in as markup (nothing in them comes from outside).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .sky import PHASE_CYCLE, Sky, SkyPoint, sun_at

def _moon_lit(phase: float, southern: bool, cx: float, cy: float, r: float, attrs: str = "") -> str:
	"""The lit part of the disc as a path: the limb on the lit side and the terminator, an ellipse whose width follows the phase. North of the equator a
	waxing moon is lit on the right; south of it, on the left."""
	k = (phase % PHASE_CYCLE) / PHASE_CYCLE
	rx = abs(math.cos(2 * math.pi * k)) * r
	gibbous = 0.25 < k < 0.75
	d = f"M{cx:.2f} {cy - r:.2f}A{r:.2f} {r:.2f} 0 0 1 {cx:.2f} {cy + r:.2f}A{rx:.2f} {r:.2f} 0 0 {1 if gibbous else 0} {cx:.2f} {cy - r:.2f}Z"
	left = (k >= 0.5) != southern
	return f'<path d="{d}"{attrs}' + (f' transform="matrix(-1 0 0 1 {2 * cx:.2f} 0)"' if left else "") + "/>"

def moon_strokes(phase: float, southern: bool) -> str:
	"""The moon for an overlay's icon (python/datasources/overlay_text.py OverlayIcon), in the 64 grid: the disc's outline, and its lit part filled (an icon
	is strokes, but a fill of the element's own wins over the group's none), so the dark part shows the picture through it."""
	return '<circle cx="32" cy="32" r="22"/>' + _moon_lit(phase, southern, 32, 32, 22, ' fill="currentColor"')

def _moon_disc(phase: float, southern: bool) -> str:
	"""The moon in a 64 square: the dark disc in the dark tone, the lit part in the first secondary's light tone, an outline round both (the page's CSS
	fills each in its role's color)."""
	return (f'<circle class="moon-dark text-primary" cx="32" cy="32" r="30"/>'
		f'<g class="moon-lit text-secondary-1-light">{_moon_lit(phase, southern, 32, 32, 30)}</g>'
		f'<circle class="moon-edge text-primary" cx="32" cy="32" r="30" fill="none"/>')

def moon_svg(phase: float, southern: bool, css_class: str = "moon") -> str:
	"""The moon for a page."""
	return f'<svg class="{css_class}" viewBox="0 0 64 64" aria-hidden="true">{_moon_disc(phase, southern)}</svg>'

# the arc's drawing area, in its own units (the page scales it): as wide in both orientations, taller on a tall page, the ground under the horizon
# holding the compass points and the times
ARC_W = 1000.0
ARC_TOP = 40.0
ARC_GROUND = 150.0

@dataclass(frozen=True, slots=True)
class Frame:
	width: float
	height: float
	top: float

	@property
	def horizon(self) -> float:
		return self.height - ARC_GROUND

	def y(self, elevation: float) -> float:
		"""The height in the sky down the drawing (a point below the horizon goes down into the ground, cut at the drawing's edge)."""
		return min(self.horizon - elevation * (self.horizon - ARC_TOP) / self.top, self.height + 10)

def _x(azimuth: float, centre: float, width: float = ARC_W) -> float:
	"""The compass bearing across the drawing, the side of the sky that faces the equator in the middle (south in the north, north in the south)."""
	return ((azimuth - centre + 540.0) % 360.0) / 360.0 * width

def _paths(points: tuple[tuple[datetime, SkyPoint], ...], centre: float, frame: Frame) -> tuple[str, str]:
	"""The path as two `d` strings, the part above the horizon and the part below, cut where it wraps from one edge of the drawing to the other."""
	above: list[str] = []
	below: list[str] = []
	last: tuple[float, float, bool]|None = None
	for _, p in points:
		x, y, up = _x(p.azimuth, centre, frame.width), frame.y(p.elevation), p.elevation >= 0
		if last is not None and abs(x - last[0]) < frame.width / 2:
			# the segment goes with the end that is higher: it crosses the horizon at most once in a step
			(above if (up or last[2]) else below).append(f"M{last[0]:.1f} {last[1]:.1f}L{x:.1f} {y:.1f}")
		last = (x, y, up)
	return "".join(above), "".join(below)

COMPASS = (("N", 0.0), ("NE", 45.0), ("E", 90.0), ("SE", 135.0), ("S", 180.0), ("SW", 225.0), ("W", 270.0), ("NW", 315.0))

def arc_svg(sky: Sky, rise_label: str, set_label: str, tall: bool = False) -> str:
	"""The sky as the device sees it: the horizon with its compass points, the sun's path today and the moon's around now (solid above the horizon,
	dotted below), where each is now when it is up, and the sunrise's and sunset's times under the points where the sun crosses the horizon."""
	centre = 0.0 if sky.place.southern else 180.0
	# a tall page's drawing is narrower in its own units, so its lines and letters come out bigger on the narrow page
	frame = Frame(*((640.0, 860.0) if tall else (ARC_W, 520.0)), max([p.elevation for _, p in sky.sun_path] + [p.elevation for _, p in sky.moon_path] + [20.0]) * 1.08)
	h, w = frame.horizon, frame.width
	sun_up, sun_down = _paths(sky.sun_path, centre, frame)
	moon_up, moon_down = _paths(sky.moon_path, centre, frame)
	parts = [f'<svg class="arc" viewBox="0 0 {w:.0f} {frame.height:.0f}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">',
		f'<rect class="arc-ground text-primary-light" x="0" y="{h:.1f}" width="{w:.0f}" height="{ARC_GROUND:.1f}"/>',
		f'<path class="arc-moon-below text-secondary-2" d="{moon_down}"/><path class="arc-sun-below text-secondary-1" d="{sun_down}"/>',
		f'<path class="arc-moon text-secondary-2" d="{moon_up}"/><path class="arc-sun text-secondary-1" d="{sun_up}"/>',
		f'<line class="arc-horizon text-primary" x1="0" y1="{h:.1f}" x2="{w:.0f}" y2="{h:.1f}"/>']
	for name, bearing in COMPASS:
		x = _x(bearing, centre, w)
		if 8 < x < w - 8:
			parts.append(f'<line class="arc-tick text-primary" x1="{x:.1f}" y1="{h:.1f}" x2="{x:.1f}" y2="{h + 14:.1f}"/>')
			parts.append(f'<text class="arc-compass text-primary{" arc-cardinal" if len(name) == 1 else ""}" x="{x:.1f}" y="{h + 50:.1f}">{name}</text>')
	# where the sun crosses the horizon, with its time under the compass points (kept inside the drawing)
	for when, label in ((sky.sun.sunrise, rise_label), (sky.sun.sunset, set_label)):
		if when is None or not label:
			continue
		x = _x(sun_at(sky.place, when).azimuth, centre, w)
		parts.append(f'<circle class="arc-cross text-primary" cx="{x:.1f}" cy="{h:.1f}" r="8"/>')
		parts.append(f'<text class="arc-time text-secondary-1" x="{min(max(x, 70.0), w - 70.0):.1f}" y="{h + 112:.1f}">{label}</text>')
	# the moon, then the sun, where they are now and up (the sun drawn last, over the moon); one below the horizon is not in this sky
	if sky.moon_now.elevation >= 0:
		mx, my = _x(sky.moon_now.azimuth, centre, w), frame.y(sky.moon_now.elevation)
		parts.append(f'<g class="arc-moon-now" transform="translate({mx - 22:.1f} {my - 22:.1f}) scale(0.6875)">{_moon_disc(sky.moon.phase, sky.place.southern)}</g>')
	if sky.sun_now.elevation >= 0:
		sx, sy = _x(sky.sun_now.azimuth, centre, w), frame.y(sky.sun_now.elevation)
		parts.append(f'<circle class="arc-sun-now text-secondary-1" cx="{sx:.1f}" cy="{sy:.1f}" r="20"/>')
	parts.append("</svg>")
	return "".join(parts)
