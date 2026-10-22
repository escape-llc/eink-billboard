"""
OpenWeatherMap as a weather provider (`WeatherApi`, `data-weather`): the weather at the device's location, now and forecast, and nothing drawn.

The sources that show the weather (the Weather pages, the Weather Overlay, the Weather Visualizer) ask for a weather provider with `dsec.provide(WeatherApi)`:
the key and the kept answers are this provider's settings and files (it answers in SI: the units shown are the device's), so a page and an overlay of the same hours make one call, and the free
plan's calls are for new answers only.
"""
from collections import Counter
from datetime import date, datetime, timedelta, tzinfo
import logging
import re
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool
from ..metering import metered_client
from ..response_cache import cached
from ..data_source import DataSourceExecutionContext
from ..contracts.weather import DAYS_SHOWN, HOURS_SHOWN, NEEDS, Day, Point, Report, WeatherApi, device_now

# the credit its terms ask for next to its data: the Weather pages draw it (the descriptor's `credit`, which the Credits page lists, says the same)
CREDIT = "Weather data: OpenWeatherMap"
# the free plan's endpoints: the weather now, and the forecast in steps of three hours for five days
API ="https://api.openweathermap.org/data/2.5"
MAX_BYTES = 1024 * 1024

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
	async with metered_client("openweathermap", timeout=httpx.Timeout(10.0)) as client:
		try:
			await fetch(client, "weather", 0.0, 0.0, key)
		except PermanentError:
			return { "ok": False, "message": "OpenWeatherMap refused this key. A new key can take a couple of hours to start working." }
		except RuntimeError as problem:
			# 429 and the rest: our own words from `fetch`
			return { "ok": False, "message": str(problem) }
	return { "ok": True, "message": "OpenWeatherMap accepts this key." }

# one kept time for each kind of answer, a setting of the data source each: the API path, the setting and its default (hours)
CACHE_TIMES = { "weather": ("currentCacheHours", 0.5), "forecast": ("forecastCacheHours", 6.0) }

async def fetch(client: httpx.AsyncClient, path: str, latitude: float, longitude: float, key: str) -> Mapping[str, Any]:
	"""One call of the API, in `metric` (Celsius, metres per second: the report's SI). Failures say what happened and never what was asked: the address holds the key."""
	try:
		response = await client.get(f"{API}/{path}", params={ "lat": f"{latitude:.4f}", "lon": f"{longitude:.4f}", "units": "metric", "appid": key }, timeout=20.0)
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

def has_key(settings: Mapping[str, Any]|None) -> bool:
	key = (settings or {}).get("apiKey")
	return isinstance(key, str) and bool(key.strip())

class OpenWeatherMapApi(WeatherApi):
	"""
	The weather contract (`WeatherApi`) from OpenWeatherMap's free plan. Every answer comes through this source's kept answers (one kept time per kind,
	its settings). A missing location or key is a PermanentError naming the settings to fix.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def configured(self, dsec: DataSourceExecutionContext) -> bool:
		"""Set up when its key is set (whether OpenWeatherMap accepts it is the slot's to find out)."""
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		return has_key(settings)

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
		if not has_key(settings) or not isinstance(key, str):
			raise PermanentError("The OpenWeatherMap API key is not set. Add it in the OpenWeatherMap settings.")
		now = device_now(dsec.timestamp)
		zone = now.tzinfo or now.astimezone().tzinfo
		assert zone is not None
		report = Report("", system.get("timeFormat") == "12h", now, credit=CREDIT)
		latitude, longitude = float(where["latitude"]), float(where["longitude"])
		report.latitude = latitude
		# a metered client of its own (#440): every answer that is not kept is a call against the key's quota
		async with metered_client(self.id, timeout=AsyncHttpWorkerPool.REQUEST_TIMEOUT) as client:
			def answer(path: str):
				"""The API's answer for this place: kept for the time the settings give that kind of answer (it is the same for every task), so the free plan's calls are for new answers only."""
				# the key is not part of what is kept or what it is called: an answer is the same whoever asks
				name = f"{path}|{latitude:.4f}|{longitude:.4f}|metric"
				setting, default = CACHE_TIMES[path]
				return cached(dscm, settings, name, dsec.timestamp, lambda: fetch(client, path, latitude, longitude, key.strip()), default, setting)
			if "current" in needs:
				parse_current(await answer("weather"), report, zone)
			if "forecast" in needs:
				parse_forecast(await answer("forecast"), report, zone)
		return report
