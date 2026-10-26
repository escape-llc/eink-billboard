"""
The drawings of the sky (#619): the moon at its phase and the paths of the sun and the moon across the sky, as SVG made here from our own numbers, so a
page may put them in as markup (nothing in them comes from outside).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape

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
	"""The moon in a 64 square: the dark disc in the dark tone, the lit part in the highlight ink, an outline round both (the page's CSS
	fills each in its role's color)."""
	return (f'<circle class="moon-dark text-primary" cx="32" cy="32" r="30"/>'
		f'<g class="moon-lit fill-ink">{_moon_lit(phase, southern, 32, 32, 30)}</g>'
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

def sparkline_svg(week: tuple[tuple[date, timedelta|None], ...], today: date) -> str:
	"""The day's length over the week around today: a line through the days (a gap where a day has no length), each day's initial under it, today's
	point larger. Scaled to the week's own range, so a change of minutes shows; a week of one length is a level line."""
	if not week:
		return ""
	w, top, bottom = 280.0, 10.0, 46.0
	step = w / len(week)
	hours = [None if length is None else length.total_seconds() / 3600 for _, length in week]
	known = [h for h in hours if h is not None]
	low, high = (min(known), max(known)) if known else (0.0, 0.0)
	def y(h: float) -> float:
		return (top + bottom) / 2 if high - low < 1e-6 else bottom - (h - low) / (high - low) * (bottom - top)
	points = [(step * (i + 0.5), None if h is None else y(h)) for i, h in enumerate(hours)]
	runs: list[list[str]] = [[]]
	for x, py in points:
		if py is None:
			runs.append([])
		else:
			runs[-1].append(f"{x:.1f} {py:.1f}")
	parts = [f'<svg class="spark" viewBox="0 0 {w:.0f} 72" preserveAspectRatio="xMidYMid meet" aria-hidden="true">']
	parts += [f'<path class="spark-line text-secondary-1" d="M {" L ".join(run)}"/>' for run in runs if len(run) > 1]
	for (day, _), (x, py) in zip(week, points, strict=True):
		if py is not None:
			parts.append(f'<circle class="spark-dot {"text-primary" if day == today else "text-secondary-1"}" cx="{x:.1f}" cy="{py:.1f}" r="{7 if day == today else 3.5}"/>')
		parts.append(f'<text class="spark-day {"spark-today text-primary" if day == today else "text-secondary-2"}" x="{x:.1f}" y="68">{day.strftime("%a")[0]}</text>')
	parts.append("</svg>")
	return "".join(parts)

@dataclass(frozen=True, slots=True)
class Mark:
	"""A time on the timeline: when, what it is ("Sunrise"), its time as the page writes it, and whose it is ("sun" or "moon")."""
	when: datetime
	name: str
	label: str
	body: str

# the timeline's label: two lines (the name, the time), about this wide per character of the time's line, in the drawing's units
TIMELINE_NAME_PX = 28.0
TIMELINE_TIME_PX = 34.0
TIMELINE_CHAR = 0.58
TIMELINE_TIER = 76.0

def _label_width(mark: Mark) -> float:
	return max(len(mark.name) * TIMELINE_NAME_PX, len(mark.label) * TIMELINE_TIME_PX) * TIMELINE_CHAR

# the rows of labels on each side of the timeline, at most
TIMELINE_ROWS = 4

def _place_labels(xs: list[float], widths: list[float], width: float, gap: float = 10.0) -> list[tuple[int, int, float]]:
	"""Where each label goes: (side, tier, x), side 0 above the line and 1 below, tier 0 next to it and higher tiers further out, centred on its mark or
	else beside it. A mark runs from the line through the nearer rows to its label, so no label may cover another label or another's mark, and a label's
	own mark may not pass through a nearer label. Of the arrangements that keep all of that, the most compact (the fewest rows out, then the fewest
	labels beside their marks, then the sides alternating); a day has at most seven times, so all are searched. When none is clear, the labels are
	placed one by one clear of each other only. Kept inside the drawing."""
	n = len(xs)
	def options(i: int) -> list[tuple[int, int, float, int]]:
		x, lw = xs[i], widths[i]
		def inside(c: float) -> float:
			return min(max(c, lw / 2), width - lw / 2)
		centres = list(dict.fromkeys((inside(x), inside(x - lw / 2 + 6), inside(x + lw / 2 - 6))))
		return [(side, tier, cx, 100 * tier + 10 * k + (0 if side == i % 2 else 1)) for tier in range(TIMELINE_ROWS) for side in (0, 1) for k, cx in enumerate(centres)]
	def clear(i: int, slot: tuple[int, int, float], chosen: list[tuple[int, int, float]], of_marks: bool) -> bool:
		side, tier, cx = slot
		a, b = cx - widths[i] / 2, cx + widths[i] / 2
		for j, (s2, t2, c2) in enumerate(chosen):
			if s2 != side:
				continue
			lo, hi = c2 - widths[j] / 2, c2 + widths[j] / 2
			if t2 == tier and not (b + gap <= lo or a - gap >= hi):
				return False
			if of_marks and t2 > tier and a - 2 < xs[j] < b + 2:
				return False
			if of_marks and t2 < tier and lo - 2 < xs[i] < hi + 2:
				return False
		return True
	every = [options(i) for i in range(n)]
	best: tuple[float, list[tuple[int, int, float]]] = (math.inf, [])
	def search(i: int, chosen: list[tuple[int, int, float]], cost: float) -> None:
		nonlocal best
		if cost >= best[0]:
			return
		if i == n:
			best = (cost, list(chosen))
			return
		for side, tier, cx, c in every[i]:
			if clear(i, (side, tier, cx), chosen, True):
				chosen.append((side, tier, cx))
				search(i + 1, chosen, cost + c)
				chosen.pop()
	search(0, [], 0.0)
	if best[1] or n == 0:
		return best[1]
	chosen: list[tuple[int, int, float]] = []
	for i in range(n):
		side, tier, cx, _ = next((o for o in every[i] if clear(i, o[:3], chosen, False)), every[i][-1])
		chosen.append((side, tier, cx))
	return chosen

TIMELINE_LABEL = TIMELINE_NAME_PX + TIMELINE_TIME_PX + 8
TIMELINE_BAND = 18.0

def timeline_svg(sky: Sky, marks: list[Mark], tall: bool = False) -> str:
	"""Today from midnight to midnight: the night a thin line, the twilight and the day bands along it, and each of the day's times (the sun's and the
	moon's) marked where it falls, its name and time beside it, in time order; now is a mark under the line. A time on another day is not on it.
	The drawing is as tall as the rows of labels it uses."""
	w = 640.0 if tall else 1000.0
	midnight = datetime(sky.now.year, sky.now.month, sky.now.day, tzinfo=sky.now.tzinfo)
	def x(when: datetime) -> float:
		return (when - midnight).total_seconds() / 86400 * w
	def inside(when: datetime|None) -> bool:
		return when is not None and 0 <= (when - midnight).total_seconds() <= 86400
	shown = sorted((m for m in marks if inside(m.when)), key=lambda m: m.when)
	xs = [x(m.when) for m in shown]
	places = _place_labels(xs, [_label_width(m) for m in shown], w)
	def extent(side: int) -> float:
		tiers = [tier for s, tier, _ in places if s == side]
		return 10 + max(tiers) * TIMELINE_TIER + TIMELINE_LABEL if tiers else 22.0
	band = TIMELINE_BAND
	line = extent(0) + band / 2
	height = line + band / 2 + extent(1)
	sun = sky.sun
	parts = [f'<svg class="timeline" viewBox="0 0 {w:.0f} {height:.0f}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">',
		f'<rect class="tl-night text-primary" x="0" y="{line - 2:.1f}" width="{w:.0f}" height="4"/>']
	def span(start: datetime|None, end: datetime|None, css: str) -> None:
		a = 0.0 if start is None or start < midnight else min(x(start), w)
		b = w if end is None or (end - midnight).total_seconds() > 86400 else max(x(end), 0.0)
		if b > a:
			parts.append(f'<rect class="{css}" x="{a:.1f}" y="{line - band / 2:.1f}" width="{b - a:.1f}" height="{band:.1f}"/>')
	if sun.polar == "day":
		span(midnight, None, "tl-day text-secondary-1")
	elif sun.polar != "night":
		if sun.dawn is not None or sun.dusk is not None:
			span(sun.dawn or sun.sunrise, sun.dusk or sun.sunset, "tl-twilight text-secondary-2")
		if sun.sunrise is not None or sun.sunset is not None:
			span(sun.sunrise, sun.sunset, "tl-day text-secondary-1")
	# the hours: a tick every six, the line's ends included
	for hour in range(0, 25, 6):
		hx = min(max(w * hour / 24, 1.5), w - 1.5)
		parts.append(f'<line class="tl-hour text-primary" x1="{hx:.1f}" y1="{line - band / 2 - 4:.1f}" x2="{hx:.1f}" y2="{line + band / 2 + 4:.1f}"/>')
	for mark, mx, (side, tier, cx) in zip(shown, xs, places, strict=True):
		role = "text-secondary-1" if mark.body == "sun" else "text-secondary-2"
		out = -1 if side == 0 else 1
		edge = line + out * band / 2
		# the label's edge nearer the line; its two lines read the same either side (the name first)
		near = edge + out * (10 + tier * TIMELINE_TIER)
		top = near - TIMELINE_LABEL if side == 0 else near
		name_y, time_y = top + TIMELINE_NAME_PX, top + TIMELINE_NAME_PX + TIMELINE_TIME_PX + 2
		# the mark runs from the line to the label's near edge
		parts.append(f'<line class="tl-mark {role}" x1="{mx:.1f}" y1="{line:.1f}" x2="{mx:.1f}" y2="{near - out * 2:.1f}"/>')
		parts.append(f'<text class="tl-name {role}" x="{cx:.1f}" y="{name_y:.1f}" font-size="{TIMELINE_NAME_PX:.0f}">{escape(mark.name)}</text>')
		parts.append(f'<text class="tl-time {role}" x="{cx:.1f}" y="{time_y:.1f}" font-size="{TIMELINE_TIME_PX:.0f}">{escape(mark.label)}</text>')
	if inside(sky.now):
		nx = x(sky.now)
		parts.append(f'<path class="tl-now text-primary" d="M {nx:.1f} {line + band / 2 + 2:.1f} l -9 14 l 18 0 z"/>')
	parts.append("</svg>")
	return "".join(parts)
