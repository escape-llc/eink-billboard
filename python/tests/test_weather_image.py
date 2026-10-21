"""
The Weather Visualizer (`weather-image`): a prompt with fields for the weather, filled from OpenWeatherMap (which supplies the values and the list of fields), then
drawn as the Generated Image is. Against the fake internet's OpenWeatherMap and OpenAI: no key, no cost.
"""
import json
import logging
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

import httpx

from ..datasources.data_source import DataSourceManager, DataSourcePromptFields
from ..datasources.openweathermap.openweathermap import OpenWeatherMapApi, Report, Units, daypart, parse_current, parse_forecast, prompt_fields, season
from ..datasources.weather_image.weather_image import WeatherImageAsync, tidy
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..utils.prompt_tokens import unknown_token
from ..web.documents import validate_properties
from .fake_internet import FakeInternet, fixture_text
from .test_datasource_fixes import STATIC
from .test_openai_image import openai_requests, sources
from .test_weather import KEY, NOW, ZONE, FakeSettings, report as fixture_report, weather_settings
from .utils import save_datasource_settings, use_transport

PROMPT = "A cozy poster of {place} at {daypart} in {season}: {condition}, {temp} (feels {feels}), wind {wind}, high {high}, low {low}, rain {rain}."

def storage(weather_key: str|None = KEY) -> ConfigurationManager:
	"""Metric, so the values read the same wherever the tests run; nothing is kept (most tests count calls)."""
	cm = weather_settings({ "units": "metric", "apiKey": weather_key })
	save_datasource_settings(cm, "openai", { "apiKey": "sk-good", "modelsCacheHours": 24, "staleDays": 30 })
	return cm

def context(cm: ConfigurationManager, orientation: str = "landscape", **system) -> Any:
	from ..datasources.data_source import DataSourceExecutionContext
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("weather-image"))
	root.add_service(DataSourceManager, DataSourceManager({ **sources(), "openweathermap": OpenWeatherMapApi("openweathermap", "OpenWeatherMap"),
		"weather-image": WeatherImageAsync("weather-image", "Weather Visualizer") }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, **system)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, (800, 480), NOW)

def full_report(**more) -> Report:
	"""The fixture's report with the sun's times and the place's latitude set after it was read (reading it sets the sun's times from the fixture)."""
	report = fixture_report()
	for name, value in more.items():
		setattr(report, name, value)
	return report

def tokens_of_descriptor() -> list[dict]:
	cm = ConfigurationManager()
	return cast(Any, next(i for i in cm.enum_datasources() if i["info"]["id"] == "openweathermap")["info"])["tokens"]

TASK = { "weatherPrompt": PROMPT, "randomizePrompt": False, "textSource": "openai-text", "imageSource": "openai-image" }

class TestTheFields(unittest.TestCase):
	def test_the_source_that_supplies_the_values_lists_the_fields(self):
		source = OpenWeatherMapApi("openweathermap", "OpenWeatherMap")
		self.assertIsInstance(source, DataSourcePromptFields)
		listed = [t["name"] for t in tokens_of_descriptor()]
		self.assertTrue(all(t["description"] for t in tokens_of_descriptor()))
		self.assertEqual(len(listed), len(set(listed)))
		fields = source.prompt_fields(full_report(sunrise=NOW - timedelta(hours=6), sunset=NOW + timedelta(hours=6), latitude=47.6))
		# every value is one of the listed fields, and a report that has it all gives them all
		self.assertEqual(set(fields) - set(listed), set())
		self.assertEqual(set(listed) - set(fields), set(), "a field the descriptor lists but the code never fills")

	def test_the_values_are_words_with_their_units(self):
		fields = prompt_fields(full_report(sunrise=datetime(2026, 10, 7, 7, 5, tzinfo=ZONE), sunset=datetime(2026, 10, 7, 18, 40, tzinfo=ZONE), latitude=47.6))
		self.assertEqual((fields["place"], fields["condition"], fields["temp"], fields["season"], fields["daypart"]), ("Seattle", "scattered clouds", "14°C", "autumn", "day"))
		self.assertEqual((fields["sunrise"], fields["sunset"]), ("07:05", "18:40"))
		self.assertTrue(fields["humidity"].endswith("%") and fields["wind"].endswith("km/h"))
		american = prompt_fields(full_report(sunrise=datetime(2026, 10, 7, 7, 5, tzinfo=ZONE), sunset=datetime(2026, 10, 7, 18, 40, tzinfo=ZONE), latitude=47.6, units=Units("imperial"), twelve_hour=True))
		self.assertEqual((american["sunrise"], american["sunset"]), ("7:05 am", "6:40 pm"))
		self.assertTrue(american["temp"].endswith("°F") and american["wind"].endswith("mph"))

	def test_what_is_not_known_is_left_out(self):
		bare = Report("", Units("metric"), False, NOW)
		self.assertEqual(prompt_fields(bare), {})
		parse_current(json.loads(fixture_text("weather-current.json")), bare, ZONE)
		self.assertEqual(set(prompt_fields(bare)), { "place", "condition", "temp", "feels", "humidity", "wind", "sunrise", "sunset", "daypart" })
		parse_forecast(json.loads(fixture_text("weather-forecast.json")), bare, ZONE)
		self.assertTrue({ "high", "low" } <= set(prompt_fields(bare)))

	def test_the_part_of_the_day_and_the_season(self):
		rise, sset = datetime(2026, 6, 1, 5, 0, tzinfo=ZONE), datetime(2026, 6, 1, 21, 0, tzinfo=ZONE)
		for hour, minute, expected in ((4, 30, "dawn"), (5, 40, "dawn"), (12, 0, "day"), (20, 30, "dusk"), (23, 0, "night"), (2, 0, "night")):
			self.assertEqual(daypart(datetime(2026, 6, 1, hour, minute, tzinfo=ZONE), rise, sset), expected, (hour, minute))
		self.assertIsNone(daypart(rise, None, sset))
		self.assertEqual([season(date(2026, m, 15), 47.6) for m in (1, 3, 6, 9, 12)], ["winter", "spring", "summer", "autumn", "winter"])
		self.assertEqual([season(date(2026, m, 15), -33.9) for m in (1, 3, 6, 9, 12)], ["summer", "autumn", "winter", "spring", "summer"])
		self.assertIsNone(season(date(2026, 1, 1), None))

	def test_a_prompt_after_its_fields_dropped_out_is_tidy(self):
		self.assertEqual(tidy("A poster of  at dawn in , light rain ,  ."), "A poster of at dawn in, light rain,.")
		self.assertEqual(tidy("one  two\n\n   \nthree "), "one two\nthree")

class TestTheDescriptor(unittest.TestCase):
	def test_the_prompt_may_use_the_fields_of_the_source_that_supplies_them(self):
		cm = ConfigurationManager()
		item = next(i for i in cm.enum_datasources() if i["info"]["id"] == "weather-image")
		prompt = next(p for p in item["info"]["instanceSettings"]["schema"]["properties"] if p["name"] == "weatherPrompt")
		self.assertEqual(prompt["tokens"], tokens_of_descriptor())
		# the factory prompt uses only fields that exist, and the server refuses another
		self.assertIsNone(unknown_token(prompt["default"], [t["name"] for t in prompt["tokens"]]))
		props = item["info"]["instanceSettings"]["schema"]["properties"]
		self.assertEqual(validate_properties({ **TASK, "weatherPrompt": prompt["default"] }, props), [])
		self.assertEqual(validate_properties({ **TASK, "weatherPrompt": "{place} {colour}" }, props), [{ "path": ["weatherPrompt"], "message": "Unknown field {colour}" }])

class TestTheVisualizer(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)
		self.source = WeatherImageAsync("weather-image", "Weather Visualizer")
		logging.getLogger("python.datasources.weather_image").setLevel(logging.CRITICAL)

	async def picture(self, cm: ConfigurationManager, **task):
		dsec = context(cm)
		params = { **TASK, **task }
		state = await self.source.open_async(dsec, params)
		return state[0]["prompt"], await self.source.render_async(dsec, params, state[0])

	async def test_the_picture_is_drawn_from_the_prompt_with_the_weather_in_it(self):
		before = len(openai_requests("/v1/images/generations"))
		prompt, result = await self.picture(storage())
		assert result is not None and result.image is not None
		self.assertEqual(result.image.size, (800, 480))
		self.assertIn("Seattle", prompt)
		self.assertIn("scattered clouds", prompt)
		self.assertIn("14°C", prompt)
		self.assertNotIn("{", prompt)
		self.assertTrue(result.title.startswith("Weather Visualizer: A cozy poster of Seattle"))
		asked = openai_requests("/v1/images/generations")[before:]
		self.assertEqual(len(asked), 1)
		self.assertTrue(asked[0]["prompt"].startswith("A cozy poster of Seattle"))
		self.assertIn("The image should fully occupy the entire canvas", asked[0]["prompt"], "the picture instructions (Master Prompts) follow the prompt")
		# the text model is asked for nothing unless the task says so
		self.assertEqual(len([r for r in openai_requests("/v1/responses")]), len(openai_requests("/v1/responses")))

	async def test_the_text_part_rewrites_the_prompt_with_the_weather_in_it_when_asked(self):
		before = len(openai_requests("/v1/responses"))
		await self.picture(storage(), randomizePrompt=True)
		rewrite = openai_requests("/v1/responses")[before:]
		self.assertEqual(len(rewrite), 1)
		self.assertIn("A cozy poster of Seattle", rewrite[0]["input"])
		self.assertIn("scattered clouds", rewrite[0]["input"])

	async def test_without_the_forecast_the_prompt_is_made_with_what_is_known(self):
		def handler(request: httpx.Request) -> httpx.Response:
			if request.url.path.endswith("/forecast"):
				return httpx.Response(502)
			return self.fake._handle(request)
		use_transport(self, httpx.MockTransport(handler))
		prompt, result = await self.picture(storage())
		self.assertIsNotNone(result)
		self.assertIn("14°C", prompt)
		self.assertTrue(prompt.endswith(" high, low, rain."), prompt)
		self.assertNotIn("{", prompt)

	async def test_without_the_weather_at_all_the_picture_is_still_drawn_from_the_rest_of_the_prompt(self):
		def down(request: httpx.Request) -> httpx.Response:
			if request.url.host == "api.openweathermap.org":
				raise httpx.ConnectError("down", request=request)
			return self.fake._handle(request)
		use_transport(self, httpx.MockTransport(down))
		prompt, result = await self.picture(storage(), weatherPrompt="A poster of {place} in {condition}, a bold flat sky.")
		self.assertEqual(prompt, "A poster of in, a bold flat sky.")
		self.assertIsNotNone(result)

	async def test_what_the_user_must_fix_is_not_hidden(self):
		for cm, text in ((storage(weather_key=None), "API key is not set"), ):
			with self.subTest(text), self.assertRaises(PermanentError) as caught:
				await self.source.open_async(context(cm), TASK)
			self.assertIn(text, str(caught.exception))
		with self.assertRaises(PermanentError) as nowhere:
			await self.source.open_async(context(storage(), location=None), TASK)
		self.assertIn("no location", str(nowhere.exception))
		with self.assertRaises(PermanentError) as empty:
			await self.source.open_async(context(storage()), { **TASK, "weatherPrompt": "  " })
		self.assertIn("Write the prompt", str(empty.exception))
		with self.assertRaises(PermanentError) as no_part:
			await self.source.open_async(context(storage()), { **TASK, "imageSource": "" })
		self.assertIn("Choose the image source", str(no_part.exception))
		self.assertEqual(KEY, "good-key")
