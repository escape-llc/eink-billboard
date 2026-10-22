"""
Open-Meteo as a weather provider (#513 phase 5): no key, one call for the weather now and the forecast, the same SI `Report` as OpenWeatherMap's, and its
credit on the pages (CC BY 4.0). Against the fake internet's Open-Meteo, which answers a forecast for the tests' day.
"""
import json
import unittest
from datetime import date, datetime, timedelta
from typing import Any, cast

import httpx

from ..datasources.contracts.weather import IMPERIAL, METRIC, Report, WeatherApi
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.open_meteo.open_meteo import CREDIT, OpenMeteoApi, condition, parse
from ..datasources.openweathermap.openweathermap import OpenWeatherMapApi
from ..datasources.weather.weather import Page, WeatherAsync, page_params
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from .fake_internet import FakeInternet, fixture_text
from .test_datasource_fixes import STATIC
from .test_weather import KEY, NOW, ZONE, FakeSettings, weather_settings
from .utils import save_datasource_settings, use_transport

def answer() -> dict:
	return json.loads(fixture_text("open-meteo-forecast.json"))

def report(needs=("current", "forecast")) -> Report:
	r = Report("", False, NOW)
	parse(answer(), r, ZONE, set(needs))
	return r

def context(cm: ConfigurationManager, sources: dict[str, Any]|None = None, own: str = "weather", **system: Any) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager(own))
	root.add_service(DataSourceManager, DataSourceManager({ "open-meteo": OpenMeteoApi("open-meteo", "Open-Meteo") } if sources is None else sources))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings("landscape", **system)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, (800, 480), NOW)

def storage(**settings: Any) -> ConfigurationManager:
	"""A private storage; Open-Meteo's answers are kept as the test asks (none by default: most tests count calls)."""
	cm = weather_settings({ "apiKey": None })
	save_datasource_settings(cm, "open-meteo", { "cacheHours": 0, "staleDays": 30, **settings })
	return cm

class TestCodes(unittest.TestCase):
	def test_a_wmo_code_is_an_icon_group_and_words_by_day_or_night(self):
		self.assertEqual(condition(0, 1), ("01d", "Clear sky"))
		self.assertEqual(condition(0, 0), ("01n", "Clear sky"))
		self.assertEqual(condition(63), ("10d", "Rain"))
		self.assertEqual(condition(95, 0), ("11n", "Thunderstorm"))
		self.assertEqual(condition(73), ("13d", "Snow"))
		self.assertEqual(condition(45), ("50d", "Fog"))
		# a code this list does not know reads as cloud: nothing wrong is said
		self.assertEqual(condition(42), ("03d", "Cloudy"))
		self.assertEqual(condition(None), ("03d", "Cloudy"))

class TestParsing(unittest.TestCase):
	def test_the_weather_now_is_si(self):
		r = report(["current"])
		assert r.current is not None
		self.assertEqual((r.current.temp, r.current.feels, r.current.humidity, r.current.wind, r.current.icon, r.current.text), (14.2, 13.1, 71, 3.6, "03d", "Partly cloudy"))
		self.assertEqual(r.current.when, NOW)
		self.assertEqual((r.sunrise, r.sunset), (datetime(2026, 10, 7, 7, 2, tzinfo=ZONE), datetime(2026, 10, 7, 18, 9, tzinfo=ZONE)))
		self.assertEqual((r.hours, r.days), ([], []), "only what was asked")

	def test_the_hours_are_three_hour_steps_from_the_one_that_covers_now(self):
		r = report(["forecast"])
		self.assertEqual(len(r.hours), 8)
		self.assertEqual(r.hours[0].when, NOW)
		self.assertEqual({ b.when - a.when for a, b in zip(r.hours, r.hours[1:], strict=False) }, { timedelta(hours=3) })
		# the chance of rain is 0 to 1, as the contract says (Open-Meteo gives percent)
		self.assertTrue(all(h.rain is not None and 0 <= h.rain <= 1 for h in r.hours))
		self.assertIsNone(r.current)

	def test_the_days_start_today_with_a_range_a_chance_of_rain_and_the_days_humidity(self):
		r = report(["forecast"])
		self.assertEqual([d.day for d in r.days], [date(2026, 10, 7) + timedelta(days=n) for n in range(5)])
		today = r.days[0]
		self.assertLess(today.low, today.high)
		self.assertEqual((today.icon, today.text), ("03d", "Partly cloudy"))
		self.assertAlmostEqual(cast(float, today.rain), 0.07)
		self.assertEqual(r.days[2].text, "Light rain")
		self.assertIsNotNone(today.humidity)
		self.assertEqual(today.wind, 4.5)

	def test_an_answer_without_what_is_asked_is_not_one(self):
		with self.assertRaises(RuntimeError):
			parse({ "current": {} }, Report("", False, NOW), ZONE, { "current" })
		with self.assertRaises(RuntimeError):
			parse({ "hourly": { "time": [] }, "daily": {} }, Report("", False, NOW), ZONE, { "forecast" })

class TestTheProvider(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)

	async def test_one_call_in_si_with_unix_times_and_no_key(self):
		cm = storage()
		provider = OpenMeteoApi("open-meteo", "Open-Meteo")
		dsec = context(cm)
		r = await provider.open_async(dsec.context_for(provider), { "needs": ["current", "forecast"] })
		self.assertEqual(len(self.fake.requests), 1)
		query = self.fake.requests[0].url.params
		self.assertEqual((query["latitude"], query["longitude"], query["timeformat"], query["wind_speed_unit"], query["temperature_unit"]), ("47.6100", "-122.3300", "unixtime", "ms", "celsius"))
		self.assertNotIn("appid", query)
		self.assertEqual((r.credit, r.place), (CREDIT, ""))
		self.assertTrue(r.current and r.hours and r.days)

	async def test_it_is_set_up_as_it_is_installed(self):
		provider = OpenMeteoApi("open-meteo", "Open-Meteo")
		self.assertTrue(provider.configured(context(storage()).context_for(provider)))

	async def test_an_answer_is_kept_for_its_hours_and_shared(self):
		cm = storage(cacheHours=0.5)
		provider = OpenMeteoApi("open-meteo", "Open-Meteo")
		await provider.open_async(context(cm).context_for(provider), { "needs": ["current"] })
		await provider.open_async(context(cm).context_for(provider), { "needs": ["forecast"] })
		self.assertEqual(len(self.fake.requests), 1, "one answer holds the weather now and the forecast")

	async def test_no_location_is_for_the_user_to_fix(self):
		provider = OpenMeteoApi("open-meteo", "Open-Meteo")
		with self.assertRaisesRegex(PermanentError, "no location"):
			await provider.open_async(context(storage(), location=None).context_for(provider), { "needs": ["current"] })

	async def test_a_refusal_is_our_words(self):
		use_transport(self, httpx.MockTransport(lambda r: httpx.Response(429, json={ "error": True, "reason": "Daily API request limit exceeded" })))
		provider = OpenMeteoApi("open-meteo", "Open-Meteo")
		with self.assertRaisesRegex(RuntimeError, "^Open-Meteo says too many requests") as caught:
			await provider.open_async(context(storage()).context_for(provider), { "needs": ["current"] })
		self.assertNotIn("Daily API", str(caught.exception))

class TestAWeatherProvider(unittest.IsolatedAsyncioTestCase):
	"""With no OpenWeatherMap key, a new device's weather works: Open-Meteo is the only provider set up (#513 rule 5)."""
	def setUp(self):
		use_transport(self, FakeInternet())

	def both(self) -> dict[str, Any]:
		return { "open-meteo": OpenMeteoApi("open-meteo", "Open-Meteo"), "openweathermap": OpenWeatherMapApi("openweathermap", "OpenWeatherMap") }

	async def test_without_a_key_the_weather_is_open_meteos(self):
		pages = await WeatherAsync("weather", "Weather").open_async(context(storage(), self.both()), { "views": ["current", "days"] })
		self.assertEqual(pages[0].report.credit, CREDIT)
		self.assertEqual(len(pages[1].report.days), 5)

	async def test_with_a_key_too_the_device_chooses(self):
		cm = storage()
		save_datasource_settings(cm, "openweathermap", { "apiKey": KEY, "currentCacheHours": 0, "forecastCacheHours": 0 })
		with self.assertRaisesRegex(PermanentError, "Several weather providers are set up"):
			await WeatherAsync("weather", "Weather").open_async(context(cm, self.both()), { "views": ["current"] })
		for chosen, credit in (("openweathermap", "Weather data: OpenWeatherMap"), ("open-meteo", CREDIT)):
			pages = await WeatherAsync("weather", "Weather").open_async(context(cm, self.both(), weatherProvider=chosen), { "views": ["current"] })
			self.assertEqual(pages[0].report.credit, credit)

	def test_a_provider_supplies_the_contract(self):
		self.assertTrue(issubclass(OpenMeteoApi, WeatherApi))

class TestTheCredit(unittest.TestCase):
	"""Its data is CC BY 4.0: the Weather pages show the provider's credit, whichever provider it is."""
	def test_the_page_shows_the_providers_credit(self):
		r = report()
		r.credit = CREDIT
		self.assertEqual(page_params(Page("current", r, METRIC), {})["credit"], "Weather data by Open-Meteo.com")
		self.assertEqual(page_params(Page("days", r, IMPERIAL), {})["credit"], "Weather data by Open-Meteo.com")
		self.assertEqual(page_params(Page("current", Report("", False, NOW), METRIC), {})["credit"], "", "no credit, no footer")
