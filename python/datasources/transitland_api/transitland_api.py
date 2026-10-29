"""
Transitland as a transit provider (`TransitApi`, `data-transit`, #429): the departures and alerts of the stops the person lists (My Stops), from Transitland's REST
API, and nothing drawn. The transit pages and overlays ask `dsec.provide(TransitApi)`; the key, the stops and the kept answers are this provider's.

**The free plan is 5,000 calls a month**, so the cache guards the quota, not the trigger rate: a departures answer is kept at least 15 minutes (`departuresCacheMinutes`,
`minimum` 15: there is no "ask every time"), shared by every page and overlay of the stop, and its "as of" moment goes with it. Routine refreshes stop at a share of
the plan (`routineShare`, default 80%), so the stop lookup and Test still work to the end of it; at the whole plan the budget guard (#586) stops every call.
The key goes in the `apikey` header only, never the address. A failure is our words and the status code, never Transitland's text.
"""
from dataclasses import replace
from datetime import datetime
import logging
import math
from typing import Any, Mapping
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool
from ..contracts.transit import ADDED, CANCELLED, INTERVALS_ONLY, SCHEDULED, SKIPPED, Alert, Departure, Route, Stop, TransitApi, TransitReport, device_now
from ..data_source import DataSourceExecutionContext
from ..metering import METER, QuotaUsedUp, metered_client
from ..response_cache import cached

DATASOURCE_ID = "transitland-api"
# the credit its terms ask for where the data is shown: every transit page and overlay draws it (the descriptor's `credit` says the same, for the Credits list)
CREDIT = "Transit data: Transitland"
API = "https://transit.land/api/v2/rest"
MAX_BYTES = 4 * 1024 * 1024
# a departures answer covers this far ahead (Transitland's `next`, in seconds): kept 15 minutes or more, it still reaches past the last departure a board shows
WINDOW_SECONDS = 5400
DEPARTURES_LIMIT = 60
# the stop lookup: how many stops near the device it lists, and how many a search finds
NEARBY_LIMIT = 50
# a search by name (the stop finder) looks this far from the device: Transitland's most for a geographic query
SEARCH_RADIUS = 10000

# the settings' floors and defaults (the descriptor says the same: a hand-edited file below the floor is raised to it)
MIN_CACHE_MINUTES = 15
DEFAULT_DEPARTURES_MINUTES = 15
DEFAULT_ALERTS_MINUTES = 30
# the routes that serve a stop, asked for their alerts (`routeAlerts`)
ROUTES_LIMIT = 100
DEFAULT_LOOKUP_HOURS = 24
DEFAULT_RADIUS = 800
DEFAULT_SHARE = 80

# Transitland's trip statuses (GTFS-RT's `schedule_relationship`) in the contract's words; any other is a trip that runs as timetabled
STATUSES = { "CANCELED": CANCELLED, "DELETED": CANCELLED, "SKIPPED": SKIPPED, "ADDED": ADDED }
SEVERITIES = { "INFO": "info", "WARNING": "warning", "SEVERE": "severe" }

logger = logging.getLogger(__name__)

def refusal(status: int) -> BaseException:
	"""What an HTTP status from Transitland means, in our words (its text is never shown)."""
	if status in (401, 403):
		return PermanentError("Transitland refused the API key. Check it in the Transitland settings.")
	if status == 404:
		return PermanentError("Transitland does not know this stop. Choose it again in the Transitland settings (My Stops).")
	if status == 429:
		return RuntimeError("Transitland says too many requests were made; what was kept is shown, and it is asked again later.")
	return RuntimeError(f"Transitland answered {status}.")

async def fetch(client: httpx.AsyncClient, path: str, params: Mapping[str, Any], key: str) -> dict[str, Any]:
	"""One call of the REST API with the key in the `apikey` header: the answer as a JSON object, or our words for why not."""
	try:
		response = await client.get(f"{API}{path}", params=dict(params), headers={ "apikey": key }, timeout=20.0)
	except httpx.HTTPError as ex:
		raise RuntimeError(f"Transitland could not be reached ({type(ex).__name__}).") from None
	if response.status_code != 200:
		raise refusal(response.status_code)
	if len(response.content) > MAX_BYTES:
		raise RuntimeError("Transitland's answer is too large.")
	try:
		data = response.json()
	except ValueError:
		raise RuntimeError("Transitland's answer is not JSON.") from None
	if not isinstance(data, dict):
		raise RuntimeError("Transitland's answer is not what was expected.")
	return data

def stop_path(stop_key: str) -> str:
	"""The address of a stop by its key (a Onestop ID, or `<feed>:<stop_id>`): quoted, so a key can never reach another path."""
	return "/stops/" + quote(stop_key, safe=":~-_.")

def has_key(settings: Mapping[str, Any]|None) -> bool:
	key = (settings or {}).get("apiKey")
	return isinstance(key, str) and bool(key.strip())

def _object(value: Any) -> dict[str, Any]:
	"""A JSON object of the answer, or an empty one for anything else (a missing or `null` field)."""
	return value if isinstance(value, dict) else {}

def _number(value: Any) -> float|None:
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def minutes_of(settings: Mapping[str, Any], name: str, default: float) -> float:
	"""A kept time in minutes, never under the floor (a file edited by hand cannot make every task a call)."""
	value = _number(settings.get(name))
	return max(MIN_CACHE_MINUTES, value if value is not None else default)

def _moment(text: Any) -> datetime|None:
	"""An ISO moment of Transitland's (`2026-10-28T18:05:00Z`), aware; None when it is not one."""
	if not isinstance(text, str) or not text:
		return None
	try:
		moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
	except ValueError:
		return None
	return moment if moment.tzinfo is not None else None

def _epoch(value: Any, zone: ZoneInfo) -> datetime|None:
	number = _number(value)
	return None if number is None else datetime.fromtimestamp(number, zone)

def _zone(name: Any, fallback: ZoneInfo) -> ZoneInfo:
	if isinstance(name, str) and name:
		try:
			return ZoneInfo(name)
		except (ZoneInfoNotFoundError, ValueError):
			pass
	return fallback

def _color(value: Any) -> str|None:
	"""A GTFS colour (`FF0000`) as `#ff0000`; anything else is none."""
	if isinstance(value, str) and len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
		return "#" + value.lower()
	return None

def translated(translations: Any, language: str) -> str:
	"""The text in the device's language (`en-US`: that tag, then `en`, then English, then the first there is)."""
	found = [t for t in translations if isinstance(t, dict) and isinstance(t.get("text"), str)] if isinstance(translations, list) else []
	if not found:
		return ""
	wanted = language.lower()
	for test in (lambda tag: tag == wanted, lambda tag: tag.split("-")[0] == wanted.split("-")[0], lambda tag: tag.split("-")[0] == "en", lambda tag: tag == ""):
		for t in found:
			if test(str(t.get("language") or "").lower()):
				return t["text"].strip()
	return found[0]["text"].strip()

def stop_key_of(stop: Mapping[str, Any]) -> str:
	"""How a stop is asked for again: its Onestop ID, or `<feed>:<stop_id>` when it has none."""
	onestop = stop.get("onestop_id")
	if isinstance(onestop, str) and onestop:
		return onestop
	feed = ((stop.get("feed_version") or {}).get("feed") or {}).get("onestop_id")
	stop_id = stop.get("stop_id")
	return f"{feed}:{stop_id}" if isinstance(feed, str) and feed and isinstance(stop_id, str) and stop_id else ""

def _alert(raw: Mapping[str, Any], language: str, zone: ZoneInfo, route: str = "") -> Alert|None:
	header = translated(raw.get("header_text"), language)
	if not header:
		return None
	periods = tuple((_epoch(p.get("start"), zone), _epoch(p.get("end"), zone)) for p in (raw.get("active_period") or []) if isinstance(p, dict))
	key = f"{raw.get('entity_id') or header}|" + ",".join(f"{p.get('start')}-{p.get('end')}" for p in (raw.get("active_period") or []) if isinstance(p, dict))
	severity = SEVERITIES.get(str(raw.get("severity_level") or ""), "unknown")
	return Alert(key, header, translated(raw.get("description_text"), language), severity, str(raw.get("effect") or "").lower(), str(raw.get("cause") or "").lower(),
		periods, translated(raw.get("url"), language) or None, (route,) if route else ())

class AlertsSeen:
	"""The alerts of an answer, each once by its key, while they are not over: one seen on several routes is one alert that names them all."""
	def __init__(self, language: str, zone: ZoneInfo, fetched_at: datetime):
		self.language, self.zone, self.fetched_at = language, zone, fetched_at
		self.found: dict[str, Alert] = {}

	def note(self, alerts: Any, route: str = "") -> None:
		for raw in alerts if isinstance(alerts, list) else []:
			alert = _alert(raw, self.language, self.zone, route) if isinstance(raw, dict) else None
			if alert is None or not any(end is None or end > self.fetched_at for _, end in alert.periods or ((None, None),)):
				continue
			known = self.found.get(alert.key)
			if known is None:
				self.found[alert.key] = alert
			elif route and route not in known.routes:
				self.found[alert.key] = replace(known, routes=known.routes + (route,))

	def alerts(self) -> list[Alert]:
		return list(self.found.values())

def _departure(raw: Mapping[str, Any], zone: ZoneInfo, platform: str|None) -> Departure|None:
	times = _object(raw.get("departure")) if _object(raw.get("departure")).get("scheduled_utc") else _object(raw.get("arrival"))
	scheduled = _moment(times.get("scheduled_utc"))
	if scheduled is None:
		return None
	estimated = _moment(times.get("estimated_utc"))
	trip = _object(raw.get("trip"))
	route = _object(trip.get("route"))
	relationship = str(raw.get("schedule_relationship") or trip.get("schedule_relationship") or "")
	delay = times.get("estimated_delay") if isinstance(times.get("estimated_delay"), int) else times.get("delay") if isinstance(times.get("delay"), int) else None
	headsign = str(raw.get("stop_headsign") or trip.get("trip_headsign") or route.get("route_long_name") or "").strip()
	return Departure((estimated or scheduled).astimezone(zone), scheduled.astimezone(zone), estimated is not None, delay, headsign,
		Route(str(route.get("route_short_name") or "").strip(), str(route.get("route_long_name") or "").strip(), _color(route.get("route_color")), _color(route.get("route_text_color"))),
		STATUSES.get(relationship, SCHEDULED), platform)

def _routes_wanted(text: Any) -> set[str]:
	"""A stop's route filter (`23, 45X`): the route names to keep, in lower case; empty keeps every route."""
	return { part.strip().lower() for part in text.split(",") if part.strip() } if isinstance(text, str) else set()

def parse_departures(data: Mapping[str, Any], entry: Mapping[str, Any], fetched_at: datetime, language: str, device_zone: ZoneInfo) -> TransitReport:
	"""
	The departures answer, normalized: the stop and, for a station, its platforms' departures too, soonest first; the alerts of the stop, its routes and trips,
	each once, kept while they are not over; the route filter of the stop's entry applied. An answer with no stop in it is not one (RuntimeError).
	"""
	stops = [s for s in (data.get("stops") or []) if isinstance(s, dict)]
	if not stops:
		raise RuntimeError("Transitland's answer has no stop in it.")
	stop = stops[0]
	parent = _object(stop.get("parent"))
	zone = _zone(stop.get("stop_timezone") or parent.get("stop_timezone"), device_zone)
	report = TransitReport(Stop(stop_key_of(stop) or str(entry.get("stopKey") or ""), str(stop.get("stop_name") or entry.get("name") or "").strip(), zone.key,
		str(stop.get("platform_code") or "") or None), fetched_at.astimezone(zone), CREDIT, int(_number(entry.get("walkMinutes")) or 0))
	wanted = _routes_wanted(entry.get("routes"))
	seen = AlertsSeen(language, zone, fetched_at)
	intervals = 0
	places = [(stop, report.stop.platform)] + [(c, str(c.get("platform_code") or "") or None) for c in (stop.get("children") or []) if isinstance(c, dict)]
	for place, platform in places:
		seen.note(place.get("alerts"))
		for raw in place.get("departures") or []:
			if not isinstance(raw, dict):
				continue
			trip = _object(raw.get("trip"))
			if trip.get("frequencies"):
				intervals += 1
			departure = _departure(raw, zone, platform)
			if departure is None:
				continue
			if wanted and departure.route.short_name.lower() not in wanted and departure.route.long_name.lower() not in wanted:
				continue
			seen.note(trip.get("alerts"), departure.route.label)
			seen.note(_object(trip.get("route")).get("alerts"), departure.route.label)
			report.departures.append(departure)
	report.departures.sort(key=lambda d: (d.when, d.route.label, d.headsign))
	report.alerts = seen.alerts()
	if intervals and not any(d.live for d in report.departures) and intervals >= len(report.departures):
		report.notes.append(INTERVALS_ONLY)
	return report

def add_route_alerts(report: TransitReport, data: Mapping[str, Any], entry: Mapping[str, Any], language: str) -> None:
	"""
	The alerts of the routes that serve the stop (the `/routes` answer), added to the report's: each once, the routes it was seen on named, the stop's route filter
	applied, kept while they are not over (as of when the departures were asked).
	"""
	seen = AlertsSeen(language, ZoneInfo(report.stop.zone), report.fetched_at)
	seen.found = { a.key: a for a in report.alerts }
	wanted = _routes_wanted(entry.get("routes"))
	for route in data.get("routes") or []:
		if not isinstance(route, dict):
			continue
		short, long = str(route.get("route_short_name") or "").strip(), str(route.get("route_long_name") or "").strip()
		if wanted and short.lower() not in wanted and long.lower() not in wanted:
			continue
		seen.note(route.get("alerts"), short or long)
	report.alerts = seen.alerts()

def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
	"""The distance between two points (haversine, on a sphere: near enough for a walk to a stop)."""
	p1, p2 = math.radians(lat1), math.radians(lat2)
	a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
	return 6371000 * 2 * math.asin(math.sqrt(a))

def distance_text(metres: float) -> str:
	"""A distance as a walk reads it: "120 m" below a kilometre, then "2.4 km" (whole kilometres from 10)."""
	if metres < 1000:
		return f"{round(metres)} m"
	km = metres / 1000
	return f"{km:.1f} km" if km < 10 else f"{round(km)} km"

def nearby_choices(data: Mapping[str, Any], latitude: float|None, longitude: float|None) -> list[dict[str, str]]:
	"""
	The stops of an answer as choices, nearest the point first, labelled so stops of the same name can be told apart: "Main St & 3rd, platform 2 (120 m)". A stop
	with no key to ask it by again is left out, and so is one with no position when there is a point; with no point (a search from a device with no location)
	they are in the order of their names, with no distance.
	"""
	found: list[tuple[float, dict[str, str]]] = []
	for stop in data.get("stops") or []:
		if not isinstance(stop, dict):
			continue
		key = stop_key_of(stop)
		point = (stop.get("geometry") or {}).get("coordinates") if isinstance(stop.get("geometry"), dict) else None
		placed = isinstance(point, list) and len(point) >= 2 and _number(point[0]) is not None and _number(point[1]) is not None
		if not key or (latitude is not None and longitude is not None and not placed):
			continue
		distance = _metres(latitude, longitude, float(point[1]), float(point[0])) if latitude is not None and longitude is not None and isinstance(point, list) else 0.0
		name = str(stop.get("stop_name") or key).strip()
		detail = str(stop.get("platform_code") or "").strip()
		detail = f"platform {detail}" if detail else str(stop.get("stop_desc") or "").strip()
		far = f" ({distance_text(distance)})" if latitude is not None and longitude is not None else ""
		found.append((distance, { "name": f"{name}{', ' + detail if detail else ''}{far}", "value": key }))
	return [choice for _, choice in sorted(found, key=lambda pair: (pair[0], pair[1]["name"]))]

def looks_like_key(text: str) -> bool:
	"""Whether what was typed is a stop's key rather than its name: a Onestop ID (`s-...`) or `<feed>:<stop_id>`, with no spaces."""
	return not any(c.isspace() for c in text) and (text.startswith("s-") or ":" in text)

def client() -> httpx.AsyncClient:
	"""The provider's metered client (#440): every call is counted against its plan on the System page."""
	return metered_client(DATASOURCE_ID, timeout=AsyncHttpWorkerPool.REQUEST_TIMEOUT)

async def check_key(key: str) -> dict[str, Any]:
	"""Ask Transitland, with this key, for one operator (the cheapest call there is): `{ ok, message }` in our words. Not kept: a Test is rare, and counted."""
	async with client() as http:
		try:
			await fetch(http, "/operators", { "limit": 1 }, key)
		except PermanentError:
			return { "ok": False, "message": "Transitland refused this key." }
		except RuntimeError as problem:
			return { "ok": False, "message": str(problem) }
	return { "ok": True, "message": "Transitland accepts this key." }

async def check_stop(key: str, stop_key: str) -> dict[str, Any]:
	"""Ask Transitland for a stop by its key: `{ ok, message }`, with the stop's name when it knows it."""
	async with client() as http:
		try:
			data = await fetch(http, stop_path(stop_key), {}, key)
		except PermanentError as problem:
			return { "ok": False, "message": str(problem) if "key" in str(problem) else "Transitland does not know this stop." }
		except RuntimeError as problem:
			return { "ok": False, "message": str(problem) }
	stops = [s for s in (data.get("stops") or []) if isinstance(s, dict)]
	if not stops:
		return { "ok": False, "message": "Transitland does not know this stop." }
	return { "ok": True, "message": f"Transitland knows this stop: {str(stops[0].get('stop_name') or stop_key).strip()}." }

async def nearby(dscm: DatasourceConfigurationManager, settings: Mapping[str, Any], latitude: float, longitude: float, now: datetime) -> list[dict[str, str]]:
	"""The stops near a point (the stop lookup), kept `lookupCacheHours` by the rounded point and the radius, so opening the form spends no quota."""
	key = str(settings.get("apiKey") or "").strip()
	radius = int(_number(settings.get("radius")) or DEFAULT_RADIUS)
	# about 100 m: a device that moves a little asks again, one that stays never does
	name = f"stops|{latitude:.3f}|{longitude:.3f}|{radius}"
	async with client() as http:
		data = await cached(dscm, settings, name, now, lambda: fetch(http, "/stops", { "lat": f"{latitude:.5f}", "lon": f"{longitude:.5f}", "radius": radius, "limit": NEARBY_LIMIT }, key),
			DEFAULT_LOOKUP_HOURS, "lookupCacheHours")
	return nearby_choices(data, latitude, longitude)

async def search(dscm: DatasourceConfigurationManager, settings: Mapping[str, Any], text: str, where: tuple[float, float]|None, now: datetime) -> list[dict[str, str]]:
	"""
	The stop finder: the stops whose name holds what was typed, within SEARCH_RADIUS of the device (anywhere when it has no location), or the stop of a key typed
	(or stored: the form asks for a stored value's own entry, to name it). Kept `lookupCacheHours` by what was asked, so the same search spends no quota.
	"""
	key = str(settings.get("apiKey") or "").strip()
	asked = text.strip()
	params: dict[str, Any]
	if looks_like_key(asked):
		name, params = f"stop-key|{asked}", { "stop_key": asked }
	else:
		name, params = f"search|{asked.casefold()}", { "search": asked, "limit": NEARBY_LIMIT }
		if where is not None:
			name += f"|{where[0]:.3f}|{where[1]:.3f}"
			params.update({ "lat": f"{where[0]:.5f}", "lon": f"{where[1]:.5f}", "radius": SEARCH_RADIUS })
	async with client() as http:
		data = await cached(dscm, settings, name, now, lambda: fetch(http, "/stops", params, key), DEFAULT_LOOKUP_HOURS, "lookupCacheHours")
	return nearby_choices(data, where[0] if where is not None else None, where[1] if where is not None else None)

def stop_entry(settings: Mapping[str, Any], name: Any) -> Mapping[str, Any]:
	"""The entry of My Stops a task names; a name that is not one is a PermanentError that says where to look."""
	for entry in settings.get("stops") or []:
		if isinstance(entry, dict) and entry.get("name") == name and isinstance(entry.get("stopKey"), str) and entry["stopKey"].strip():
			return entry
	if not isinstance(name, str) or not name:
		raise PermanentError("No stop is chosen. Choose one of My Stops (Transitland settings).")
	raise PermanentError(f"'{name}' is not one of My Stops. Add it in the Transitland settings, or choose another.")

class TransitlandApi(TransitApi):
	"""
	The transit contract from Transitland's REST API. A stop's departures (with the alerts that come with them, at no extra cost) are kept for `departuresCacheMinutes`
	and shared by every page and overlay of the stop; a missing key or stop is a PermanentError naming the settings to fix.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	def configured(self, dsec: DataSourceExecutionContext) -> bool:
		"""Set up when its key is set (whether Transitland accepts it is the slot's to find out)."""
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		return has_key(settings)

	def stop_names(self, dsec: DataSourceExecutionContext) -> list[str]:
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		return [str(e["name"]) for e in (settings or {}).get("stops") or [] if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"]]

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> TransitReport:
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		_, settings = dscm.open().get()
		settings = settings or {}
		if not has_key(settings):
			raise PermanentError("The Transitland API key is not set. Add it in the Transitland settings.")
		entry = stop_entry(settings, params.get("stop"))
		key, stop_key = str(settings["apiKey"]).strip(), str(entry["stopKey"]).strip()
		scm = dsec.provider.get_service(SettingsConfigurationManager)
		system = (scm.open("system").get()[1] if scm is not None else None) or {}
		now = device_now(dsec.timestamp)
		device_zone = _zone(system.get("timezoneName"), ZoneInfo("UTC"))
		share = (_number(settings.get("routineShare")) or DEFAULT_SHARE) / 100
		language = str(system.get("locale") or "en-US")
		# the kept times are minutes, with a floor; the cache counts hours
		hours = { **settings, "departuresCacheHours": minutes_of(settings, "departuresCacheMinutes", DEFAULT_DEPARTURES_MINUTES) / 60,
			"alertsCacheHours": minutes_of(settings, "alertsCacheMinutes", DEFAULT_ALERTS_MINUTES) / 60 }
		async with client() as http:
			def asker(path: str, query: Mapping[str, Any]):
				async def ask() -> dict[str, Any]:
					# the routine share of the plan (#429): past it, what was kept is shown, and the lookups and Test keep the rest
					used = METER.share(self.id)
					if used is not None and used >= share:
						raise QuotaUsedUp(f"Transitland's routine refreshes stop at {round(share * 100)}% of the monthly quota; what was kept is shown until the period resets.")
					data = await fetch(http, path, query, key)
					# the moment it was asked goes with it: a kept answer is shown "as of" then, not as of the slot that reads it
					return { "answer": data, "fetched_at": now.isoformat() }
				return ask
			kept = await cached(dscm, hours, f"departures|{stop_key}|{WINDOW_SECONDS}", dsec.timestamp,
				asker(stop_path(stop_key) + "/departures", { "next": WINDOW_SECONDS, "include_alerts": "true", "limit": DEPARTURES_LIMIT }), DEFAULT_DEPARTURES_MINUTES / 60, "departuresCacheHours")
			fetched_at = _moment(kept.get("fetched_at")) or now
			answer = kept.get("answer")
			if not isinstance(answer, dict):
				raise RuntimeError("Transitland's kept answer could not be read.")
			report = parse_departures(answer, entry, fetched_at, language, device_zone)
			# a route's alerts are a call of their own, kept longer: only when asked, and only for a stop with a Onestop ID (Transitland finds the routes by it)
			if params.get("routeAlerts") is True and ":" not in stop_key:
				try:
					routes = await cached(dscm, hours, f"routes|{stop_key}", dsec.timestamp,
						asker("/routes", { "serves_stop_onestop_id": stop_key, "include_alerts": "true", "limit": ROUTES_LIMIT }), DEFAULT_ALERTS_MINUTES / 60, "alertsCacheHours")
				except (RuntimeError, QuotaUsedUp) as problem:
					# the departures are worth showing without them: the stop's own alerts are there already
					self.logger.info(f"'{self.id}' the routes' alerts could not be had ({type(problem).__name__}); the stop's own are shown.")
				else:
					if isinstance(routes.get("answer"), dict):
						add_route_alerts(report, routes["answer"], entry, language)
		return report
