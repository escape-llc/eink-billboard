"""
OpenWeatherMap as an API data source (`DataSourceApi`): the weather at the device's location, now and forecast, and nothing drawn.

The sources that show the weather (the Weather pages, the Weather Overlay) ask it with `dsec.use`: the key, the units and the kept answers are its
settings and files, so a page and an overlay of the same hours make one call, and the free plan's calls are for new answers only.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
import logging
import re
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool, client_var, tls_context
from ..response_cache import cached
from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext

# the free plan's endpoints: the weather now, and the forecast in steps of three hours for five days
API = "https://api.openweathermap.org/data/2.5"
# what can be asked for (`needs`): the weather now, the forecast (the next hours and days)
NEEDS = ("current", "forecast")
# the hours page shows the next day in steps of three hours; the days page the days the forecast reaches
HOURS_SHOWN = 8
DAYS_SHOWN = 5
MAX_BYTES = 1024 * 1024
# timezones that read in miles and degrees Fahrenheit when the units are left to the device
IMPERIAL_ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "America/Detroit",
	"America/Boise", "America/Indiana/", "America/Kentucky/", "America/Menominee", "America/North_Dakota/", "Pacific/Honolulu", "US/", "Pacific/Guam")

class HideKey(logging.Filter):
	"""OpenWeatherMap takes the key in the address, and the HTTP client logs addresses: the key is hidden in what it logs."""
	_KEY = re.compile(r"(appid=)[^&\s\"']+", re.IGNORECASE)
	def filter(self, record: logging.LogRecord) -> bool:
		# the address is an argument of the message (an object, not text), so the finished message is what is cleaned
		try:
			text = record.getMessage()
		except Exception:
			return True
		if "appid=" in text.lower():
			record.msg, record.args = self._KEY.sub(r"\g<1>***", text), None
		return True

for _name in ("httpx", "httpcore"):
	logging.getLogger(_name).addFilter(HideKey())

@dataclass(frozen=True)
class Units:
	system: str   # "metric" or "imperial", as OpenWeatherMap names them
	@property
	def temp(self) -> str:
		return "°F" if self.system == "imperial" else "°C"
	@property
	def speed(self) -> str:
		return "mph" if self.system == "imperial" else "km/h"
	def wind(self, value: float) -> int:
		"""OpenWeatherMap gives metres per second for metric and miles per hour for imperial."""
		return round(value if self.system == "imperial" else value * 3.6)

def units_for(setting: object, timezone_name: object) -> Units:
	"""`metric` or `imperial` as chosen; anything else (auto) follows the device's timezone: the US reads in miles and Fahrenheit."""
	if setting in ("metric", "imperial"):
		return Units(str(setting))
	zone = str(timezone_name or "")
	return Units("imperial" if any(zone == z or (z.endswith("/") and zone.startswith(z)) for z in IMPERIAL_ZONES) else "metric")

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
	place: str
	units: Units
	twelve_hour: bool
	now: datetime
	current: Point|None = None
	sunrise: datetime|None = None
	sunset: datetime|None = None
	hours: list[Point] = field(default_factory=list)
	days: list[Day] = field(default_factory=list)
	# where it was asked for (the season depends on the hemisphere)
	latitude: float|None = None

def device_now(timestamp: datetime) -> datetime:
	"""The slot's time where the display is: the schedule's timestamp carries the system zone (naive means local)."""
	return timestamp if timestamp.tzinfo is not None else timestamp.astimezone()

def _number(value: Any) -> float|None:
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def _condition(entry: Mapping[str, Any]) -> tuple[str, str]:
	first = (entry.get("weather") or [{}])[0]
	return str(first.get("icon") or ""), str(first.get("description") or "").strip().capitalize()

def _point(entry: Mapping[str, Any], zone: tzinfo) -> Point|None:
	main = entry.get("main") or {}
	temp, stamp = _number(main.get("temp")), _number(entry.get("dt"))
	if temp is None or stamp is None:
		return None
	icon, text = _condition(entry)
	humidity = _number(main.get("humidity"))
	return Point(datetime.fromtimestamp(stamp, zone), temp, _number(main.get("feels_like")), icon, text, None if humidity is None else round(humidity),
		_number((entry.get("wind") or {}).get("speed")), _number(entry.get("pop")), _number(main.get("temp_min")), _number(main.get("temp_max")))

def parse_current(data: Mapping[str, Any], report: Report, zone: tzinfo) -> None:
	"""The answer of `/weather`, into the report. An answer that has no temperature is not one (RuntimeError)."""
	point = _point(data, zone)
	if point is None:
		raise RuntimeError("OpenWeatherMap's answer has no weather in it.")
	report.current = point
	report.place = report.place or str(data.get("name") or "")
	sys = data.get("sys") or {}
	sunrise, sunset = _number(sys.get("sunrise")), _number(sys.get("sunset"))
	report.sunrise = None if sunrise is None else datetime.fromtimestamp(sunrise, zone)
	report.sunset = None if sunset is None else datetime.fromtimestamp(sunset, zone)

def parse_forecast(data: Mapping[str, Any], report: Report, zone: tzinfo) -> None:
	"""The answer of `/forecast` (steps of three hours), into the next day of steps and the days it reaches."""
	steps = [p for p in (_point(e, zone) for e in data.get("list") or [] if isinstance(e, dict)) if p is not None]
	if not steps:
		raise RuntimeError("OpenWeatherMap's answer has no forecast in it.")
	report.place = report.place or str((data.get("city") or {}).get("name") or "")
	# the step that covers now started up to three hours ago
	upcoming = [p for p in steps if p.when + timedelta(hours=3) > report.now]
	report.hours = upcoming[:HOURS_SHOWN]
	by_day: dict[date, list[Point]] = {}
	for p in upcoming:
		by_day.setdefault(p.when.date(), []).append(p)
	for day, points in list(by_day.items())[:DAYS_SHOWN]:
		# the day's picture is the commonest condition group of its daytime steps (all of them when it has none left), drawn as day
		daytime = [p for p in points if p.icon.endswith("d")] or points
		group = Counter(p.icon[:2] for p in daytime).most_common(1)[0][0]
		chosen = next(p for p in daytime if p.icon[:2] == group)
		rains = [p.rain for p in points if p.rain is not None]
		humidities = [p.humidity for p in points if p.humidity is not None]
		winds = [p.wind for p in points if p.wind is not None]
		report.days.append(Day(day, min(p.low if p.low is not None else p.temp for p in points), max(p.high if p.high is not None else p.temp for p in points),
			group + "d", chosen.text, max(rains) if rains else None, round(sum(humidities) / len(humidities)) if humidities else None, max(winds) if winds else None))

def api_error(status: int) -> BaseException:
	"""What an HTTP status from OpenWeatherMap means for the slot, in our own words (never the address, which holds the key)."""
	if status in (401, 403):
		return PermanentError("OpenWeatherMap refused the API key. Check it in the OpenWeatherMap settings; a new key can take a couple of hours to start working.")
	if status == 429:
		return RuntimeError("OpenWeatherMap says too many requests were made; it will be tried again.")
	return RuntimeError(f"OpenWeatherMap answered {status}.")

async def check_key(key: str) -> dict[str, Any]:
	"""
	Ask OpenWeatherMap, with this key, for the weather at a fixed point and say what came of it: `{ ok, message }`, in our words (the address holds the key: it is never in a message).
	A client of our own: the web app has no pool, and a test is rare; the tests' transport is installed the same way as the pool's.
	"""
	async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), transport=AsyncHttpWorkerPool.default_transport, verify=tls_context()) as client:
		try:
			await fetch(client, "weather", 0.0, 0.0, units_for("metric", None), key)
		except PermanentError:
			return { "ok": False, "message": "OpenWeatherMap refused this key. A new key can take a couple of hours to start working." }
		except RuntimeError as problem:
			# 429 and the rest: our own words from `fetch`
			return { "ok": False, "message": str(problem) }
	return { "ok": True, "message": "OpenWeatherMap accepts this key." }

# one kept time for each kind of answer, a setting of the data source each: the API path, the setting and its default (hours)
CACHE_TIMES = { "weather": ("currentCacheHours", 0.5), "forecast": ("forecastCacheHours", 6.0) }

async def fetch(client: httpx.AsyncClient, path: str, latitude: float, longitude: float, units: Units, key: str) -> Mapping[str, Any]:
	"""One call of the API. Failures say what happened and never what was asked: the address holds the key."""
	try:
		response = await client.get(f"{API}/{path}", params={ "lat": f"{latitude:.4f}", "lon": f"{longitude:.4f}", "units": units.system, "appid": key }, timeout=20.0)
	except httpx.HTTPError as ex:
		raise RuntimeError(f"OpenWeatherMap could not be reached ({type(ex).__name__}).") from None
	if response.status_code != 200:
		raise api_error(response.status_code)
	if len(response.content) > MAX_BYTES:
		raise RuntimeError("OpenWeatherMap's answer is too large.")
	try:
		data = response.json()
	except ValueError:
		raise RuntimeError("OpenWeatherMap's answer is not JSON.") from None
	if not isinstance(data, dict):
		raise RuntimeError("OpenWeatherMap's answer is not what was expected.")
	return data

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

def prompt_fields(report: Report) -> dict[str, str]:
	"""
	What a prompt may say about this report (the names are the descriptor's `tokens`): only what is known, so a value that is missing leaves its field out.
	Units are the report's; a temperature is rounded to a degree.
	"""
	units = report.units
	fields: dict[str, str|None] = { "place": report.place or None, "sunrise": _clock(report.sunrise, report.twelve_hour), "sunset": _clock(report.sunset, report.twelve_hour),
		"daypart": daypart(report.now, report.sunrise, report.sunset), "season": season(report.now.date(), report.latitude) }
	now = report.current
	if now is not None:
		fields.update({ "condition": now.text.lower() or None, "temp": f"{round(now.temp)}{units.temp}",
			"feels": None if now.feels is None else f"{round(now.feels)}{units.temp}", "humidity": None if now.humidity is None else f"{now.humidity}%",
			"wind": None if now.wind is None else f"{units.wind(now.wind)} {units.speed}" })
	today = next((d for d in report.days if d.day == report.now.date()), None)
	if today is not None:
		fields.update({ "high": f"{round(today.high)}{units.temp}", "low": f"{round(today.low)}{units.temp}", "rain": None if today.rain is None else f"{round(today.rain * 100)}%" })
	return { name: value for name, value in fields.items() if value }

class OpenWeatherMapApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, { "needs": [...] })` answers a `Report` of the weather at the device's location: `needs` is `current` (the weather now) and/or
	`forecast` (the next hours and days); only those are asked. Every answer comes through this source's kept answers (one kept time per kind, its
	settings). A missing location or key is a PermanentError naming the settings to fix.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def prompt_fields(self, data: Any) -> Mapping[str, str]:
		"""The values of the fields a prompt may use (`tokens` in the descriptor) for a `Report` this source answered."""
		return prompt_fields(data)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Report:
		needs = { n for n in (params.get("needs") or ()) if n in NEEDS }
		scm = dsec.provider.required(SettingsConfigurationManager)
		_, system = scm.open("system").get()
		system = system or {}
		where = system.get("location")
		if not isinstance(where, dict) or _number(where.get("latitude")) is None or _number(where.get("longitude")) is None:
			raise PermanentError("The device has no location. Set it in the System settings.")
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		_, settings = dscm.open().get()
		settings = settings or {}
		key = settings.get("apiKey")
		if not isinstance(key, str) or not key.strip():
			raise PermanentError("The OpenWeatherMap API key is not set. Add it in the OpenWeatherMap settings.")
		now = device_now(dsec.timestamp)
		zone = now.tzinfo or now.astimezone().tzinfo
		assert zone is not None
		report = Report("", units_for(settings.get("units"), system.get("timezoneName")), system.get("timeFormat") == "12h", now)
		latitude, longitude = float(where["latitude"]), float(where["longitude"])
		report.latitude = latitude
		client = client_var.get()
		def answer(path: str):
			"""The API's answer for this place: kept for the time the settings give that kind of answer (it is the same for every task), so the free plan's calls are for new answers only."""
			# the key is not part of what is kept or what it is called: an answer is the same whoever asks
			name = f"{path}|{latitude:.4f}|{longitude:.4f}|{report.units.system}"
			setting, default = CACHE_TIMES[path]
			return cached(dscm, settings, name, dsec.timestamp, lambda: fetch(client, path, latitude, longitude, report.units, key.strip()), default, setting)
		if "current" in needs:
			parse_current(await answer("weather"), report, zone)
		if "forecast" in needs:
			parse_forecast(await answer("forecast"), report, zone)
		return report
