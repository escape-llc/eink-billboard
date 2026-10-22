"""
The weather contract (`data-weather`): what a weather provider answers and what the Weather pages, the Weather Overlay and the Weather Visualizer draw from.
A provider implements `WeatherApi`; a consumer asks `dsec.provide(WeatherApi)` and imports nothing else of the provider's.

**A report is in SI units** (degrees Celsius, metres per second), whichever provider made it: the units a person reads are the device's (`units_of`, the
system settings: a master choice and an override for each kind of measurement), applied by whoever shows the report, so no provider knows them.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from ..data_source import DataSourceExecutionContext
from .provider import ProviderContract, device_now  # noqa: F401 (a consumer's time: one definition)

# what can be asked for (`needs`): the weather now, the forecast (the next hours and days)
NEEDS = ("current", "forecast")
# the hours page shows the next day in steps of three hours; the days page the days the forecast reaches
HOURS_SHOWN = 8
DAYS_SHOWN = 5
# timezones that read in miles and degrees Fahrenheit when the units are left to the device
IMPERIAL_ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "America/Detroit",
	"America/Boise", "America/Indiana/", "America/Kentucky/", "America/Menominee", "America/North_Dakota/", "Pacific/Honolulu", "US/", "Pacific/Guam")

# the units of each kind of measurement, as the system settings name them: the label shown, and how to get there from SI
TEMPERATURES = { "celsius": "°C", "fahrenheit": "°F" }
SPEEDS = { "km/h": 3.6, "m/s": 1.0, "mph": 3600 / 1609.344, "kn": 3600 / 1852 }

@dataclass(frozen=True)
class Units:
	"""The units a person reads, one per kind of measurement (mixed is fine: Celsius with miles per hour). A report's values are SI: these convert them."""
	temperature: str = "celsius"
	wind_speed: str = "km/h"
	@property
	def temp(self) -> str:
		return TEMPERATURES.get(self.temperature, "°C")
	@property
	def speed(self) -> str:
		return self.wind_speed if self.wind_speed in SPEEDS else "km/h"
	def degrees(self, celsius: float) -> float:
		"""A temperature of a report (Celsius) in the chosen unit."""
		return celsius * 9 / 5 + 32 if self.temperature == "fahrenheit" else celsius
	def wind(self, metres_per_second: float) -> int:
		"""A wind speed of a report (metres per second) in the chosen unit, to the nearest whole one."""
		return round(metres_per_second * SPEEDS.get(self.wind_speed, 3.6))

METRIC = Units("celsius", "km/h")
IMPERIAL = Units("fahrenheit", "mph")

def units_of(system: Mapping[str, Any]|None) -> Units:
	"""
	The device's units, from the system settings: `units` is the master choice (`metric`, `imperial`, or `auto`: the US timezones read in miles and
	Fahrenheit, the rest metric), and `temperatureUnit` and `speedUnit`, when set, override it for their kind.
	"""
	system = system or {}
	setting = system.get("units")
	if setting not in ("metric", "imperial"):
		zone = str(system.get("timezoneName") or "")
		setting = "imperial" if any(zone == z or (z.endswith("/") and zone.startswith(z)) for z in IMPERIAL_ZONES) else "metric"
	base = IMPERIAL if setting == "imperial" else METRIC
	temperature, speed = system.get("temperatureUnit"), system.get("speedUnit")
	return Units(temperature if temperature in TEMPERATURES else base.temperature, speed if speed in SPEEDS else base.wind_speed)

def device_units(dsec: DataSourceExecutionContext) -> Units:
	"""The device's units for a slot (read on every call: a change of the setting shows on the next page)."""
	# imported here: configuration_manager imports the data sources
	from ...model.configuration_manager import SettingsConfigurationManager
	scm = dsec.provider.get_service(SettingsConfigurationManager)
	system = scm.open("system").get()[1] if scm is not None else None
	return units_of(system)

@dataclass(frozen=True)
class Point:
	"""The weather at an instant (now, or one step of the forecast)."""
	when: datetime
	temp: float
	feels: float|None
	icon: str
	text: str
	humidity: int|None
	wind: float|None
	rain: float|None   # the chance of rain, 0..1
	low: float|None = None
	high: float|None = None

@dataclass(frozen=True)
class Day:
	day: date
	low: float
	high: float
	icon: str
	text: str
	rain: float|None
	humidity: int|None = None
	wind: float|None = None

@dataclass
class Report:
	"""
	The weather at the device's location, in SI units (temperatures in Celsius, wind in metres per second, the chance of rain 0 to 1). `icon` codes are
	OpenWeatherMap's (`01d` to `50n`: the condition group and day or night), which the icons and the overlay read: another provider maps its own codes to them.
	"""
	place: str
	twelve_hour: bool
	now: datetime
	current: Point|None = None
	sunrise: datetime|None = None
	sunset: datetime|None = None
	hours: list[Point] = field(default_factory=list)
	days: list[Day] = field(default_factory=list)
	# where it was asked for (the season depends on the hemisphere)
	latitude: float|None = None
	# the provider's credit, which its terms ask to be shown with its data (the Weather pages' footer; an overlay has no room, and is a fragment over another page)
	credit: str = ""

# the parts of a day, from the sun: the twilight on either side of sunrise and sunset is dawn and dusk
TWILIGHT = timedelta(minutes=45)
SEASONS = ("winter", "spring", "summer", "autumn")

def daypart(now: datetime, sunrise: datetime|None, sunset: datetime|None) -> str|None:
	"""`dawn`, `day`, `dusk` or `night`, or None when the sun's times are not known."""
	if sunrise is None or sunset is None:
		return None
	if abs(now - sunrise) <= TWILIGHT:
		return "dawn"
	if abs(now - sunset) <= TWILIGHT:
		return "dusk"
	return "day" if sunrise < now < sunset else "night"

def season(day: date, latitude: float|None) -> str|None:
	"""The meteorological season (whole months) where the display is: the other way round south of the equator."""
	if latitude is None:
		return None
	north = SEASONS[(day.month % 12) // 3]
	return north if latitude >= 0 else SEASONS[(SEASONS.index(north) + 2) % 4]

def _clock(moment: datetime|None, twelve_hour: bool) -> str|None:
	if moment is None:
		return None
	return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'}" if twelve_hour else f"{moment.hour:02d}:{moment.minute:02d}"

# the fields a prompt may use for the weather (`tokensFrom: ["data-weather"]`), filled by `prompt_fields`
TOKENS: tuple[Mapping[str, str], ...] = (
	{ "name": "place", "description": "The place the weather is for, as the weather provider names it (Seattle)." },
	{ "name": "condition", "description": "The sky and weather now, in words (light rain, clear sky)." },
	{ "name": "temp", "description": "The temperature now, with its unit (18°C)." },
	{ "name": "feels", "description": "What the temperature feels like now, with its unit." },
	{ "name": "humidity", "description": "The humidity now (64%)." },
	{ "name": "wind", "description": "The wind speed now, with its unit (12 km/h)." },
	{ "name": "high", "description": "Today's highest temperature, with its unit." },
	{ "name": "low", "description": "Today's lowest temperature, with its unit." },
	{ "name": "rain", "description": "Today's chance of rain (40%)." },
	{ "name": "sunrise", "description": "When the sun rises today, on the device's clock." },
	{ "name": "sunset", "description": "When the sun sets today, on the device's clock." },
	{ "name": "daypart", "description": "dawn, day, dusk or night, from the sun's times." },
	{ "name": "season", "description": "winter, spring, summer or autumn where the device is (the other way round south of the equator)." },
)

def prompt_fields(report: Report, units: Units) -> dict[str, str]:
	"""
	What a prompt may say about this report (the names are `TOKENS`): only what is known, so a value that is missing leaves its field out.
	In the device's units; a temperature is rounded to a degree. The same for every provider: it reads only the report.
	"""
	fields: dict[str, str|None] = { "place": report.place or None, "sunrise": _clock(report.sunrise, report.twelve_hour), "sunset": _clock(report.sunset, report.twelve_hour),
		"daypart": daypart(report.now, report.sunrise, report.sunset), "season": season(report.now.date(), report.latitude) }
	now = report.current
	if now is not None:
		fields.update({ "condition": now.text.lower() or None, "temp": f"{round(units.degrees(now.temp))}{units.temp}",
			"feels": None if now.feels is None else f"{round(units.degrees(now.feels))}{units.temp}", "humidity": None if now.humidity is None else f"{now.humidity}%",
			"wind": None if now.wind is None else f"{units.wind(now.wind)} {units.speed}" })
	today = next((d for d in report.days if d.day == report.now.date()), None)
	if today is not None:
		fields.update({ "high": f"{round(units.degrees(today.high))}{units.temp}", "low": f"{round(units.degrees(today.low))}{units.temp}", "rain": None if today.rain is None else f"{round(today.rain * 100)}%" })
	return { name: value for name, value in fields.items() if value }

class WeatherApi(ProviderContract):
	"""
	`open_async(dsec, { "needs": [...] })` answers a `Report` of the weather at the device's location: `needs` is `current` (the weather now) and/or
	`forecast` (the next hours and days); only those are asked. A missing location, or a setting of the provider's own, is a PermanentError naming the
	settings to fix.
	"""
	capability = "data-weather"
	noun = "weather"
	setting = "weatherProvider"
	tokens = TOKENS

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Report:
		raise NotImplementedError
