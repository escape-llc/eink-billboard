import asyncio
import atexit
import json
import logging
from dataclasses import replace
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
from PIL import Image

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.weather import weather as weather_module
from ..datasources.weather.icons import icon_svg
from ..datasources.weather.weather import HideKey, Page, Report, Units, WeatherAsync, api_error, chosen_views, page_params, parse_current, parse_forecast, units_for
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import client_var
from ..utils.image_utils import LINUX_CHROME_HEADLESS, WIN_CHROME_HEADLESS, os_type
from .fake_internet import FakeInternet, fixture_text
from .test_datasource_fixes import STATIC, FakeRenderSession, _Cob
from .utils import save_datasource_settings

# the display is on the US west coast in October (daylight time); "now" is Wednesday 7 October 2026, noon, which is where the fixtures start
ZONE = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=ZONE)
SEATTLE = { "latitude": 47.61, "longitude": -122.33 }
KEY = "good-key"

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: the display, system and theme documents."""
	THEME = { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 }
	def __init__(self, orientation: str = "landscape", **system):
		self.docs = { "display": { "orientation": orientation }, "system": { "timeFormat": "24h", "timezoneName": "America/Los_Angeles", "location": SEATTLE, **system }, "theme": self.THEME }
	def open(self, name: str):
		return _Cob(self.docs.get(name))

def weather_settings(settings: dict|None = None) -> DatasourceConfigurationManager:
	"""The data source's own folder in a private storage, with its settings written (`cacheHours` 0 unless a test asks: most tests count calls)."""
	folder = tempfile.mkdtemp(prefix="eink-weather-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	save_datasource_settings(cm, "weather", { "apiKey": KEY, "units": "auto", "cacheHours": 0, **(settings or {}) })
	return cm.datasource_manager("weather")

def make_context(settings: dict|None = None, orientation: str = "landscape", dscm: DatasourceConfigurationManager|None = None, now: datetime = NOW, **system) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, dscm or weather_settings(settings))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, **system)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, (800, 480), now)

def report(**more) -> Report:
	import json
	r = Report("", Units("metric"), False, NOW, **more)
	parse_current(json.loads(fixture_text("weather-current.json")), r, ZONE)
	parse_forecast(json.loads(fixture_text("weather-forecast.json")), r, ZONE)
	return r

class TestChoices(unittest.TestCase):
	def test_views_come_in_page_order_and_none_is_now(self):
		self.assertEqual(chosen_views({ "views": ["days", "current"] }), ["current", "days"])
		self.assertEqual(chosen_views({ "views": [] }), ["current"])
		self.assertEqual(chosen_views({}), ["current"])
		self.assertEqual(chosen_views({ "views": ["bogus", "hours"] }), ["hours"])

	def test_units_follow_the_choice_then_the_timezone(self):
		self.assertEqual(units_for("metric", "America/New_York").system, "metric")
		self.assertEqual(units_for("imperial", "Europe/Paris").system, "imperial")
		for zone in ("America/Los_Angeles", "America/Indiana/Knox", "Pacific/Honolulu"):
			self.assertEqual(units_for("auto", zone).system, "imperial", zone)
		for zone in ("Europe/London", "America/Toronto", "Asia/Tokyo", None):
			self.assertEqual(units_for("auto", zone).system, "metric", zone)

	def test_wind_is_converted_for_metric_only(self):
		self.assertEqual(Units("metric").wind(10), 36)
		self.assertEqual(Units("imperial").wind(10), 10)

class TestParsing(unittest.TestCase):
	def test_the_current_weather(self):
		r = report()
		assert r.current is not None
		self.assertEqual((r.place, round(r.current.temp), r.current.icon, r.current.text, r.current.humidity), ("Seattle", 14, "03d", "Scattered clouds", 71))
		self.assertEqual(r.sunrise, datetime(2026, 10, 7, 7, 2, tzinfo=ZONE))

	def test_the_next_hours_start_at_the_step_that_covers_now(self):
		r = report()
		self.assertEqual(len(r.hours), 8)
		# the first step of the fixture starts at 11:00 local (18:00 UTC) and covers noon
		self.assertEqual(r.hours[0].when, datetime(2026, 10, 7, 11, 0, tzinfo=ZONE))
		self.assertEqual([b.when - a.when for a, b in zip(r.hours, r.hours[1:])], [timedelta(hours=3)] * 7)

	def test_days_have_a_range_a_daytime_picture_and_a_chance_of_rain(self):
		r = report()
		self.assertLessEqual(len(r.days), 5)
		self.assertEqual(r.days[0].day, NOW.date())
		for day in r.days:
			self.assertLess(day.low, day.high)
			self.assertTrue(day.icon.endswith("d"))
		self.assertIsNotNone(r.days[0].rain)

	def test_an_answer_without_weather_is_not_one(self):
		with self.assertRaises(RuntimeError):
			parse_current({ "cod": 200 }, Report("", Units("metric"), False, NOW), ZONE)
		with self.assertRaises(RuntimeError):
			parse_forecast({ "list": [] }, Report("", Units("metric"), False, NOW), ZONE)

class TestPages(unittest.TestCase):
	def test_now_in_metric_and_24_hours(self):
		p = page_params(Page("current", report()), {})
		self.assertEqual((p["heading"], p["temp"], p["unit"], p["wind"], p["humidity"]), ("Seattle", "14°", "°C", "13 km/h", "71%"))
		self.assertEqual((p["sunrise"], p["sunset"]), ("07:02", "18:09"))
		self.assertIn("<svg", p["icon"])

	def test_the_hours_in_12_hour_clock_and_imperial(self):
		r = report()
		r.units, r.twelve_hour = Units("imperial"), True
		p = page_params(Page("hours", r), { "title": "Home" })
		self.assertEqual(p["heading"], "Home")
		self.assertEqual(p["hours"][0]["label"], "11 AM")
		self.assertEqual(page_params(Page("current", r), {})["wind"], "4 mph")
		self.assertEqual(page_params(Page("current", r), {})["sunset"], "6:09 PM")

	def test_the_hours_start_at_the_step_that_covers_now(self):
		import json
		data = json.loads(fixture_text("weather-forecast.json"))
		def first(hour: int, minute: int) -> str:
			r = Report("", Units("metric"), False, NOW.replace(hour=hour, minute=minute))
			parse_forecast(data, r, ZONE)
			return page_params(Page("hours", r), {})["hours"][0]["label"]
		# the steps are at 11:00, 14:00, 17:00: half past two is in the 14:00 step, and the minute before a step is still in the one before
		self.assertEqual(first(14, 0), "14:00")
		self.assertEqual(first(14, 28), "14:00")
		self.assertEqual(first(16, 59), "14:00")
		self.assertEqual(first(17, 0), "17:00")

	def test_the_hours_have_no_high_and_low_rows_and_the_days_do(self):
		self.assertEqual([r["key"] for r in page_params(Page("hours", report()), {})["rows"]], ["temp", "rain", "humidity", "wind"])
		self.assertEqual([r["key"] for r in page_params(Page("days", report()), {})["rows"]], ["high", "low", "rain", "humidity", "wind"])

	def test_the_hour_that_starts_a_day_is_marked_and_the_weekday_said(self):
		hours = page_params(Page("hours", report()), {})["hours"]
		# the fixture's steps are 11:00, 14:00, 17:00, 20:00, then 23:00, 02:00 (the next day) ...
		self.assertEqual([h["label"] for h in hours][:6], ["11:00", "14:00", "17:00", "20:00", "23:00", "02:00"])
		self.assertEqual([h["new_day"] for h in hours][:6], [False, False, False, False, False, True])
		self.assertEqual([h["day"] for h in hours][:6], ["Wed", "", "", "", "", "Thu"])
		self.assertEqual(sum(h["new_day"] for h in hours), 1)
		# the second day wears the colors the other way round
		self.assertEqual([h["alt"] for h in hours][:7], [False, False, False, False, False, True, True])

	def test_the_days_say_today_then_the_weekday(self):
		days = page_params(Page("days", report()), {})["days"]
		self.assertEqual([d["label"] for d in days][:3], ["Today", "Thu", "Fri"])

	def test_the_chance_of_rain_is_always_shown_even_when_it_is_zero(self):
		r = report()
		for step in range(len(r.hours)):
			r.hours[step] = replace(r.hours[step], rain=0.0)
		self.assertEqual({ h["rain"] for h in page_params(Page("hours", r), {})["hours"] }, { "0%" })
		r.hours[0] = replace(r.hours[0], rain=0.37)
		r.hours[1] = replace(r.hours[1], rain=None)
		hours = page_params(Page("hours", r), {})["hours"]
		self.assertEqual((hours[0]["rain"], hours[1]["rain"]), ("37%", ""))
		self.assertTrue(all(d["rain"].endswith("%") for d in page_params(Page("days", report()), {})["days"]))

	def test_every_icon_code_has_a_drawing(self):
		for code in ("01d", "01n", "02d", "02n", "03d", "04n", "09d", "10d", "11d", "13n", "50d", "", "99x"):
			self.assertTrue(icon_svg(code).startswith("<svg"), code)

class TestCache(unittest.IsolatedAsyncioTestCase):
	"""The API's answers are kept for the data source's `cacheHours`, shared by every page and task, and the free plan's calls are for new answers only."""
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	def asked(self) -> list[str]:
		return [r.url.path.rsplit("/", 1)[-1] for r in self.fake.requests]

	async def open(self, dscm, views, now=NOW):
		return await WeatherAsync("weather", "Weather").open_async(make_context(dscm=dscm, now=now), { "views": views })

	async def test_a_second_visit_in_six_hours_asks_nobody(self):
		dscm = weather_settings({ "cacheHours": 6 })
		await self.open(dscm, ["current", "hours"])
		await self.open(dscm, ["current", "days"], NOW + timedelta(hours=5))
		self.assertEqual(sorted(self.asked()), ["forecast", "weather"], "one call of each, for every page")
		await self.open(dscm, ["current"], NOW + timedelta(hours=7))
		self.assertEqual(sorted(self.asked()), ["forecast", "weather", "weather"], "the current answer was older than six hours")

	async def test_the_default_is_six_hours_and_zero_asks_every_time(self):
		dscm = weather_settings()
		self.assertEqual(dscm.open().get()[1]['cacheHours'], 0)
		cm_settings = weather_settings({ "cacheHours": 6 })
		await self.open(cm_settings, ["current"])
		await self.open(cm_settings, ["current"])
		self.assertEqual(self.asked(), ["weather"])
		await self.open(dscm, ["current"])
		await self.open(dscm, ["current"])
		self.assertEqual(self.asked()[1:], ["weather", "weather"])

	async def test_a_place_or_units_that_changed_is_a_new_question(self):
		dscm = weather_settings({ "cacheHours": 6 })
		ds = WeatherAsync("weather", "Weather")
		await ds.open_async(make_context(dscm=dscm), { "views": ["current"] })
		await ds.open_async(make_context(dscm=dscm, location={ "latitude": 40.0, "longitude": -74.0 }), { "views": ["current"] })
		self.assertEqual(self.asked(), ["weather", "weather"])

	async def test_the_key_is_never_kept_or_named_in_the_cache(self):
		dscm = weather_settings({ "cacheHours": 6 })
		await self.open(dscm, ["current", "days"])
		names = dscm.list_files("cache-")
		self.assertEqual(len(names), 2)
		for name in names:
			self.assertRegex(name, r"^cache-[0-9a-f]{16}$")
			self.assertNotIn(KEY, json.dumps(dscm.file(name).get()[1]))

	async def test_when_the_api_is_down_the_old_answer_is_used(self):
		dscm = weather_settings({ "cacheHours": 1 })
		await self.open(dscm, ["current"])
		def down(request: httpx.Request) -> httpx.Response:
			raise httpx.ConnectError("down")
		client_var.set(httpx.AsyncClient(transport=httpx.MockTransport(down)))
		pages = await self.open(dscm, ["current"], NOW + timedelta(hours=3))
		self.assertEqual([p.view for p in pages], ["current"], "the old answer")

	async def test_five_slots_at_once_ask_once(self):
		dscm = weather_settings({ "cacheHours": 6 })
		await asyncio.gather(*(self.open(dscm, ["current"]) for _ in range(5)))
		self.assertEqual(self.asked(), ["weather"])

class TestOpen(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	def asked(self) -> list[str]:
		return [r.url.path.rsplit("/", 1)[-1] for r in self.fake.requests]

	async def test_one_page_per_view_in_order_and_only_the_calls_they_need(self):
		ds = WeatherAsync("weather", "Weather")
		pages = await ds.open_async(make_context(), { "views": ["current"] })
		self.assertEqual([p.view for p in pages], ["current"])
		self.assertEqual(self.asked(), ["weather"])
		pages = await ds.open_async(make_context(), { "views": ["days", "hours", "current"] })
		self.assertEqual([p.view for p in pages], ["current", "hours", "days"])
		self.assertEqual(sorted(self.asked()[1:]), ["forecast", "weather"])

	async def test_the_request_names_the_place_and_the_units(self):
		await WeatherAsync("weather", "Weather").open_async(make_context(), { "views": ["current"] })
		query = self.fake.requests[0].url.params
		self.assertEqual((query["lat"], query["lon"], query["units"], query["appid"]), ("47.6100", "-122.3300", "imperial", KEY))

	async def test_no_location_is_for_the_user_to_fix(self):
		with self.assertRaises(PermanentError) as caught:
			await WeatherAsync("weather", "Weather").open_async(make_context(location=None), {})
		self.assertIn("System settings", str(caught.exception))
		self.assertEqual(self.fake.requests, [])

	async def test_no_key_is_for_the_user_to_fix(self):
		for settings in ({ "apiKey": None }, { "apiKey": "  " }):
			with self.assertRaises(PermanentError):
				await WeatherAsync("weather", "Weather").open_async(make_context(settings), {})
		self.assertEqual(self.fake.requests, [])

	async def test_a_refused_key_is_permanent_and_says_nothing_of_the_key(self):
		with self.assertRaises(PermanentError) as caught:
			await WeatherAsync("weather", "Weather").open_async(make_context({ "apiKey": "wrong-secret-key" }), {})
		self.assertNotIn("wrong-secret-key", str(caught.exception))
		self.assertNotIn("openweathermap.org", str(caught.exception))
		self.assertIn("hours", str(caught.exception))

	async def test_too_many_requests_is_tried_again(self):
		with self.assertRaises(RuntimeError) as caught:
			await WeatherAsync("weather", "Weather").open_async(make_context({ "apiKey": "busy-key" }), {})
		self.assertNotIsInstance(caught.exception, PermanentError)

	async def test_a_network_failure_says_its_kind_and_not_the_address(self):
		def refuse(request: httpx.Request) -> httpx.Response:
			raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)
		client_var.set(httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
		with self.assertRaises(RuntimeError) as caught:
			await WeatherAsync("weather", "Weather").open_async(make_context(), {})
		self.assertIn("ConnectError", str(caught.exception))
		self.assertNotIn("appid", str(caught.exception))
		self.assertNotIn(KEY, str(caught.exception))

	def test_statuses(self):
		self.assertIsInstance(api_error(401), PermanentError)
		self.assertNotIsInstance(api_error(500), PermanentError)

class TestKeyIsNotLogged(unittest.IsolatedAsyncioTestCase):
	async def test_the_clients_own_log_line_hides_the_key(self):
		self.assertTrue(any(isinstance(f, HideKey) for f in logging.getLogger("httpx").filters))
		client = httpx.AsyncClient(transport=FakeInternet())
		with self.assertLogs("httpx", level="INFO") as logged:
			# any other key is refused (a 401), which is also logged
			with self.assertRaises(PermanentError):
				await weather_module.fetch(client, "weather", 47.61, -122.33, Units("metric"), "super-secret-key")
		text = "\n".join(logged.output)
		self.assertIn("appid=***", text)
		self.assertNotIn("super-secret-key", text)

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		client_var.set(httpx.AsyncClient(transport=FakeInternet()))

	async def test_each_page_is_rendered_at_the_target_size(self):
		ds = WeatherAsync("weather", "Weather")
		pages = await ds.open_async(make_context(), { "views": ["current", "hours", "days"] })
		with patch.object(weather_module, "RenderSession", FakeRenderSession):
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				for page in pages:
					result = await ds.render_async(make_context(orientation=orientation), { "fontSize": "large" }, page)
					assert result is not None and FakeRenderSession.last is not None
					self.assertEqual(result.image.size, size)
					self.assertEqual(FakeRenderSession.last.params["view"], page.view)
					self.assertEqual(FakeRenderSession.last.params["font_scale"], 1.2)

	async def test_anything_but_a_page_is_nothing_to_show(self):
		self.assertIsNone(await WeatherAsync("weather", "Weather").render_async(make_context(), {}, None))

CHROME = WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The pages as Chromium draws them. The images are in .test-output/weather for a look."""
	def setUp(self):
		client_var.set(httpx.AsyncClient(transport=FakeInternet()))

	async def test_pages_are_drawn_at_the_display_size(self):
		folder = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.joinpath(".test-output", "weather")
		folder.mkdir(parents=True, exist_ok=True)
		ds = WeatherAsync("weather", "Weather")
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
			params = { "views": ["current", "hours", "days"], "fontSize": "normal" }
			pages = await ds.open_async(make_context(orientation=orientation), params)
			for page in pages:
				with self.subTest(orientation=orientation, view=page.view):
					result = await ds.render_async(make_context(orientation=orientation), params, page)
					assert result is not None
					self.assertEqual(result.image.size, size)
					result.image.save(folder.joinpath(f"{orientation}-{page.view}.png"))
					self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")
					self.assertIsInstance(result.image, Image.Image)

if __name__ == "__main__":
	unittest.main()
