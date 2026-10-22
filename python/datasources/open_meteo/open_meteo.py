"""
Open-Meteo as a weather provider (`WeatherApi`, `data-weather`): the weather at the device's location, now and forecast, with no key, and nothing drawn.

Free for non-commercial use (a hobby device is), and its data is CC BY 4.0: the report carries the credit ("Weather data by Open-Meteo.com"), which the
Weather pages show (an overlay has no room for it); the Credits page lists it from the descriptor's `credit`. One call answers the weather now, the hours and the days, kept for the settings' `cacheHours` and shared by every page and overlay. The
answer is asked in SI (Celsius, metres per second) as the contract's `Report` is; the device's units are applied by whatever shows it.
"""
from datetime import date, datetime, timedelta, timezone, tzinfo
import logging
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool
from ..contracts.weather import DAYS_SHOWN, HOURS_SHOWN, NEEDS, Day, Point, Report, WeatherApi, device_now
from ..data_source import DataSourceExecutionContext
from ..metering import metered_client
from ..response_cache import cached

API = "https://api.open-meteo.com/v1/forecast"
MAX_BYTES = 1024 * 1024
DEFAULT_CACHE_HOURS = 0.5
CREDIT = "Weather data by Open-Meteo.com"
CURRENT = "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day"
HOURLY = "temperature_2m,precipitation_probability,relative_humidity_2m,weather_code,wind_speed_10m,is_day"
DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,sunrise,sunset"
# the hours page shows steps of three hours, as the other provider's forecast is made of
STEP_HOURS = 3

# WMO weather interpretation codes (Open-Meteo's `weather_code`): the icon group the pages draw (OpenWeatherMap's codes, which the contract uses) and the words
WMO: dict[int, tuple[str, str]] = {
	0: ("01", "Clear sky"), 1: ("02", "Mainly clear"), 2: ("03", "Partly cloudy"), 3: ("04", "Overcast"),
	45: ("50", "Fog"), 48: ("50", "Freezing fog"),
	51: ("09", "Light drizzle"), 53: ("09", "Drizzle"), 55: ("09", "Dense drizzle"), 56: ("09", "Light freezing drizzle"), 57: ("09", "Freezing drizzle"),
	61: ("10", "Light rain"), 63: ("10", "Rain"), 65: ("10", "Heavy rain"), 66: ("13", "Light freezing rain"), 67: ("13", "Freezing rain"),
	71: ("13", "Light snow"), 73: ("13", "Snow"), 75: ("13", "Heavy snow"), 77: ("13", "Snow grains"),
	80: ("09", "Light showers"), 81: ("09", "Showers"), 82: ("09", "Violent showers"), 85: ("13", "Snow showers"), 86: ("13", "Heavy snow showers"),
	95: ("11", "Thunderstorm"), 96: ("11", "Thunderstorm with hail"), 99: ("11", "Thunderstorm with heavy hail"),
}

def _number(value: Any) -> float|None:
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def condition(code: Any, is_day: Any = 1) -> tuple[str, str]:
	"""The icon code (`03d`) and the words for a WMO code; an unknown code reads as cloud, which says nothing wrong."""
	group, text = WMO.get(int(code) if isinstance(code, (int, float)) and not isinstance(code, bool) else -1, ("03", "Cloudy"))
	return group + ("n" if is_day == 0 else "d"), text

def _chance(percent: Any) -> float|None:
	value = _number(percent)
	return None if value is None else max(0.0, min(value / 100, 1.0))

def _block(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
	"""One part of the answer (`current`, `hourly`, `daily`), or nothing."""
	value = data.get(name)
	return value if isinstance(value, dict) else {}

def _column(block: Mapping[str, Any], name: str, n: int) -> Any:
	values = block.get(name)
	return values[n] if isinstance(values, list) and n < len(values) else None

def parse(data: Mapping[str, Any], report: Report, zone: tzinfo, needs: set[str]) -> None:
	"""Open-Meteo's answer (`timeformat=unixtime`) into the report: the weather now and/or the forecast. An answer without what is asked is not one (RuntimeError)."""
	offset = timedelta(seconds=_number(data.get("utc_offset_seconds")) or 0)
	daily, hourly = _block(data, "daily"), _block(data, "hourly")
	# a day of the forecast is a day where the place is: its midnight, read in the place's own offset
	days = [(datetime.fromtimestamp(t, timezone.utc) + offset).date() if isinstance(t, (int, float)) else None for t in (daily.get("time") or [])]
	today = next((n for n, d in enumerate(days) if d == report.now.date()), None)
	if today is not None:
		rise, sset = _number(_column(daily, "sunrise", today)), _number(_column(daily, "sunset", today))
		report.sunrise = None if rise is None else datetime.fromtimestamp(rise, zone)
		report.sunset = None if sset is None else datetime.fromtimestamp(sset, zone)
	if "current" in needs:
		now = _block(data, "current")
		temp, stamp = _number(now.get("temperature_2m")), _number(now.get("time"))
		if temp is None or stamp is None:
			raise RuntimeError("Open-Meteo's answer has no weather in it.")
		icon, text = condition(now.get("weather_code"), now.get("is_day"))
		humidity = _number(now.get("relative_humidity_2m"))
		report.current = Point(datetime.fromtimestamp(stamp, zone), temp, _number(now.get("apparent_temperature")), icon, text,
			None if humidity is None else round(humidity), _number(now.get("wind_speed_10m")), None)
	if "forecast" in needs:
		times = [t for t in (hourly.get("time") or []) if isinstance(t, (int, float))]
		if not times or not days:
			raise RuntimeError("Open-Meteo's answer has no forecast in it.")
		# the step that covers now started at the hour before it; then every third hour
		first = max([n for n, t in enumerate(times) if t <= report.now.timestamp()] or [0])
		for n in range(first, len(times), STEP_HOURS):
			temp = _number(_column(hourly, "temperature_2m", n))
			if temp is None:
				continue
			icon, text = condition(_column(hourly, "weather_code", n), _column(hourly, "is_day", n))
			humidity = _number(_column(hourly, "relative_humidity_2m", n))
			report.hours.append(Point(datetime.fromtimestamp(times[n], zone), temp, None, icon, text, None if humidity is None else round(humidity),
				_number(_column(hourly, "wind_speed_10m", n)), _chance(_column(hourly, "precipitation_probability", n))))
			if len(report.hours) == HOURS_SHOWN:
				break
		humidity_by_day: dict[date, list[float]] = {}
		for n, t in enumerate(times):
			value = _number(_column(hourly, "relative_humidity_2m", n))
			if value is not None:
				humidity_by_day.setdefault((datetime.fromtimestamp(t, timezone.utc) + offset).date(), []).append(value)
		for n, day in enumerate(days):
			if day is None or day < report.now.date() or len(report.days) == DAYS_SHOWN:
				continue
			high, low = _number(_column(daily, "temperature_2m_max", n)), _number(_column(daily, "temperature_2m_min", n))
			if high is None or low is None:
				continue
			icon, text = condition(_column(daily, "weather_code", n))
			wet = humidity_by_day.get(day)
			report.days.append(Day(day, low, high, icon, text, _chance(_column(daily, "precipitation_probability_max", n)),
				round(sum(wet) / len(wet)) if wet else None, _number(_column(daily, "wind_speed_10m_max", n))))

def api_error(status: int) -> BaseException:
	"""What an HTTP status from Open-Meteo means for the slot, in our own words."""
	if status == 429:
		return RuntimeError("Open-Meteo says too many requests were made; it will be tried again.")
	return RuntimeError(f"Open-Meteo answered {status}.")

async def fetch(client: httpx.AsyncClient, latitude: float, longitude: float) -> Mapping[str, Any]:
	"""One call of the API, in SI (Celsius, metres per second), every time as a Unix time. Failures are our words."""
	params = { "latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}", "current": CURRENT, "hourly": HOURLY, "daily": DAILY, "timezone": "auto",
		"timeformat": "unixtime", "wind_speed_unit": "ms", "temperature_unit": "celsius", "forecast_days": str(DAYS_SHOWN + 1) }
	try:
		response = await client.get(API, params=params, timeout=20.0)
	except httpx.HTTPError as ex:
		raise RuntimeError(f"Open-Meteo could not be reached ({type(ex).__name__}).") from None
	if response.status_code != 200:
		raise api_error(response.status_code)
	if len(response.content) > MAX_BYTES:
		raise RuntimeError("Open-Meteo's answer is too large.")
	try:
		data = response.json()
	except ValueError:
		raise RuntimeError("Open-Meteo's answer is not JSON.") from None
	if not isinstance(data, dict):
		raise RuntimeError("Open-Meteo's answer is not what was expected.")
	return data

class OpenMeteoApi(WeatherApi):
	"""
	The weather contract (`WeatherApi`) from Open-Meteo: no key, so it is set up as it is installed. A missing location is a PermanentError naming the
	settings to fix. Open-Meteo names no place, and the stored location has only its coordinates: the report's place is empty.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

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
		now = device_now(dsec.timestamp)
		zone = now.tzinfo or now.astimezone().tzinfo
		assert zone is not None
		latitude, longitude = float(where["latitude"]), float(where["longitude"])
		report = Report("", system.get("timeFormat") == "12h", now, latitude=latitude, credit=CREDIT)
		if not needs:
			return report
		# a metered client of its own (#440): every answer that is not kept is a call counted against the free plan's day
		async with metered_client(self.id, timeout=AsyncHttpWorkerPool.REQUEST_TIMEOUT) as client:
			data = await cached(dscm, settings or {}, f"forecast|{latitude:.4f}|{longitude:.4f}", dsec.timestamp,
				lambda: fetch(client, latitude, longitude), DEFAULT_CACHE_HOURS, "cacheHours")
		parse(data, report, zone, needs)
		return report

