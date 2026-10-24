"""
The sun and the moon where the device is (#619), calculated on the device by `astral` (no network, no key), for the Sun and Moon page and its overlay.

`astral` answers to the minute against a JPL ephemeris (Skyfield's `de421`, see test_sky), but three of its habits are ours to handle:
- a time that does not happen (the sun does not set on a polar day) is a `ValueError` whose only difference is its wording: whether the sun stays up or
  down is read from its height at noon here, never from the message;
- `sunset(day)` is the first sunset of the *calendar* day, which near the polar circle in summer is the early-morning end of the evening before: the
  day's sunset is the first one after its sunrise (the next date's when it falls after midnight);
- the moon's position (`astral.moon.elevation` / `azimuth`) reads the clock of the time given and ignores its zone: it is always given UTC.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping

from astral import Observer
from astral import moon as _moon
from astral import sun as _sun

from ...plugins.plugin_base import PermanentError

TWILIGHTS = { "civil": 6.0, "nautical": 12.0, "astronomical": 18.0 }
# astral's phase runs from 0 (new) through 14 (full) to just under 28: a cycle in 28 parts, whatever the month's real length
PHASE_CYCLE = 28.0
# the names by phase, each quarter's name a day either side of its moment
PHASE_NAMES = (
	(1.0, "New Moon"), (6.0, "Waxing Crescent"), (8.0, "First Quarter"), (13.0, "Waxing Gibbous"),
	(15.0, "Full Moon"), (20.0, "Waning Gibbous"), (22.0, "Last Quarter"), (27.0, "Waning Crescent"), (PHASE_CYCLE, "New Moon"),
)
# how often the paths across the sky are sampled (minutes)
PATH_STEP = 10
# from one of the moon's highest points to the next
LUNAR_DAY = timedelta(hours=24, minutes=50)

@dataclass(frozen=True, slots=True)
class Place:
	latitude: float
	longitude: float

	@property
	def observer(self) -> Observer:
		return Observer(self.latitude, self.longitude)

	@property
	def southern(self) -> bool:
		return self.latitude < 0

@dataclass(frozen=True, slots=True)
class SunDay:
	"""The sun on one day, in the device's zone: a time that does not happen is None. `polar` is "day" (it does not set) or "night" (it does not rise)."""
	dawn: datetime|None
	sunrise: datetime|None
	noon: datetime
	sunset: datetime|None
	dusk: datetime|None
	polar: str|None
	noon_elevation: float

	@property
	def length(self) -> timedelta|None:
		"""How long the sun is up: 24 hours on a polar day, none on a polar night, None when only one of the two happens (the day a polar day begins or ends)."""
		if self.polar == "day":
			return timedelta(hours=24)
		if self.polar == "night":
			return timedelta(0)
		if self.sunrise is None or self.sunset is None:
			return None
		return self.sunset - self.sunrise

@dataclass(frozen=True, slots=True)
class MoonDay:
	"""The moon on one day: its phase (astral's 0 to 28), its name and the share of the disc that is lit, and its rise and set (None when it does not)."""
	phase: float
	name: str
	lit: float
	waxing: bool
	moonrise: datetime|None
	moonset: datetime|None

@dataclass(frozen=True, slots=True)
class SkyPoint:
	"""A body's place in the sky: compass bearing (degrees from north, clockwise) and height above the horizon (degrees)."""
	azimuth: float
	elevation: float

@dataclass(frozen=True, slots=True)
class Sky:
	"""What the pages draw for one moment: today's sun and moon, yesterday's day length, the next full and new moons, and the paths across the sky."""
	now: datetime
	place: Place
	sun: SunDay
	moon: MoonDay
	yesterday: timedelta|None
	next_full: date
	next_new: date
	sun_now: SkyPoint
	moon_now: SkyPoint
	sun_path: tuple[tuple[datetime, SkyPoint], ...]
	moon_path: tuple[tuple[datetime, SkyPoint], ...]

def device_place(system: Mapping[str, Any]|None) -> Place:
	"""The device's location from the system settings; none is a PermanentError that says where to set it."""
	where = (system or {}).get("location")
	if isinstance(where, dict):
		lat, lon = where.get("latitude"), where.get("longitude")
		if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not isinstance(lat, bool) and not isinstance(lon, bool):
			if -90 <= lat <= 90 and -180 <= lon <= 180:
				return Place(float(lat), float(lon))
	raise PermanentError("The device has no location. Set it in the System settings.")

def depression_of(twilight: object) -> float:
	"""The sun's depth below the horizon that ends dawn and starts dusk; unset reads as civil."""
	if twilight is None:
		return TWILIGHTS["civil"]
	if twilight not in TWILIGHTS:
		raise PermanentError(f"Unknown twilight '{twilight}' (one of {', '.join(TWILIGHTS)})")
	return TWILIGHTS[str(twilight)]

def _maybe(f, *args, **kwargs) -> datetime|None:
	"""astral's answer, or None for a time that does not happen that day (its ValueError)."""
	try:
		return f(*args, **kwargs)
	except ValueError:
		return None

def _after_noon(noon: datetime, f, observer: Observer, day: date, zone: tzinfo, **kwargs) -> datetime|None:
	"""The first `f` (a sunset, a dusk) after the day's noon, within a day: `f(day)` can be the early-morning end of the evening before, and the evening's
	can fall after midnight, on the next date."""
	for d in (day, day + timedelta(days=1)):
		when = _maybe(f, observer, d, tzinfo=zone, **kwargs)
		if when is not None and noon < when < noon + timedelta(hours=24):
			return when
	return None

def _before_noon(noon: datetime, f, observer: Observer, day: date, zone: tzinfo, **kwargs) -> datetime|None:
	"""`f(day)` (a sunrise, a dawn) when it comes before the day's noon."""
	when = _maybe(f, observer, day, tzinfo=zone, **kwargs)
	return when if when is not None and when < noon else None

def sun_day(place: Place, day: date, zone: tzinfo, depression: float = TWILIGHTS["civil"]) -> SunDay:
	"""The sun on `day` at `place`, in `zone`."""
	ob = place.observer
	noon = _sun.noon(ob, day, tzinfo=zone)
	height = _sun.elevation(ob, noon.astimezone(timezone.utc))
	sunrise = _before_noon(noon, _sun.sunrise, ob, day, zone)
	sunset = _after_noon(noon, _sun.sunset, ob, day, zone)
	polar = None
	if sunrise is None and sunset is None:
		# no rise and no set: up all day when it is up at noon, else down all day
		polar = "day" if height > 0 else "night"
	dawn = _before_noon(noon, _sun.dawn, ob, day, zone, depression=depression)
	dusk = _after_noon(noon, _sun.dusk, ob, day, zone, depression=depression)
	return SunDay(dawn, sunrise, noon, sunset, dusk, polar, height)

def phase_name(phase: float) -> str:
	for upto, name in PHASE_NAMES:
		if phase < upto:
			return name
	return "New Moon"

def lit_share(phase: float) -> float:
	"""The share of the disc that is lit (0 new, 1 full)."""
	return (1 - math.cos(2 * math.pi * phase / PHASE_CYCLE)) / 2

def moon_day(place: Place, day: date, zone: tzinfo) -> MoonDay:
	phase = _moon.phase(day)
	ob = place.observer
	return MoonDay(phase, phase_name(phase), lit_share(phase), phase < PHASE_CYCLE / 2,
		_maybe(_moon.moonrise, ob, day, tzinfo=zone), _maybe(_moon.moonset, ob, day, tzinfo=zone))

def next_phase(day: date, target: float) -> date:
	"""The first day from `day` on (today included) whose phase is nearest `target` (14: full, 0: new) as the phase passes it."""
	# from the day before: the moment can fall between yesterday and today, and today is then the nearer
	for i in range(-1, 32):
		d0, d1 = day + timedelta(days=i), day + timedelta(days=i + 1)
		p0, p1 = _moon.phase(d0), _moon.phase(d1)
		if target == 0:
			# the phase wraps from just under 28 to just over 0
			found = (d0 if PHASE_CYCLE - p0 < p1 else d1) if p1 < p0 else None
		else:
			found = (d0 if target - p0 < p1 - target else d1) if p0 <= target < p1 else None
		if found is not None and found >= day:
			return found
	return day

def sun_at(place: Place, when: datetime) -> SkyPoint:
	at = when.astimezone(timezone.utc)
	return SkyPoint(_sun.azimuth(place.observer, at), _sun.elevation(place.observer, at))

def moon_at(place: Place, when: datetime) -> SkyPoint:
	# astral reads the moon's clock as UTC whatever the zone given: always UTC
	at = when.astimezone(timezone.utc)
	return SkyPoint(_moon.azimuth(place.observer, at), _moon.elevation(place.observer, at))

def path(place: Place, start: datetime, end: datetime, at) -> tuple[tuple[datetime, SkyPoint], ...]:
	"""A body's place every PATH_STEP minutes from `start` to `end`, counted in UTC (a day of 23 or 25 hours has as many points), told in `start`'s zone."""
	zone = start.tzinfo
	points = []
	when, stop = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
	while when <= stop:
		points.append((when.astimezone(zone), at(place, when)))
		when += timedelta(minutes=PATH_STEP)
	return tuple(points)

def sky_of(place: Place, now: datetime, depression: float = TWILIGHTS["civil"]) -> Sky:
	"""Everything the pages draw for `now` (an aware time in the device's zone)."""
	zone = now.tzinfo
	assert zone is not None
	today = now.date()
	sun = sun_day(place, today, zone, depression)
	yesterday = sun_day(place, today - timedelta(days=1), zone, depression)
	midnight = datetime(today.year, today.month, today.day, tzinfo=zone)
	# the sun's path is today's, midnight to midnight (it ends about where it began). The moon rises some 50 minutes later each day, so a day's path breaks
	# where its two ends meet: its path is the lunar day around its highest point nearest now, whose ends are at its lowest, below the horizon
	high = max(path(place, now - timedelta(hours=12), now + timedelta(hours=12), moon_at), key=lambda item: item[1].elevation)[0]
	return Sky(now, place, sun, moon_day(place, today, zone), yesterday.length, next_phase(today, 14.0), next_phase(today, 0.0),
		sun_at(place, now), moon_at(place, now), path(place, midnight, datetime.combine(today + timedelta(days=1), datetime.min.time(), zone), sun_at),
		path(place, high - LUNAR_DAY / 2, high + LUNAR_DAY / 2, moon_at))
