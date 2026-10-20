"""
The Thunderforest Map data source (#428): one map of a place (one of its settings' places, or the device's location) from the Static Maps API at the panel's size, the key only in the
address and never in a message or a log line, the failures in our words, and the attribution on the page. The Test button of the key asks the same service.
"""
import atexit
import logging
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx

from ..datasources.thunderforest.thunderforest import HideKey, ThunderforestApi, map_address, refusal
from ..datasources.thunderforest_map import thunderforest_map
from ..datasources.thunderforest_map.thunderforest_map import ThunderforestMapAsync, place_of
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import client_var
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from .fake_internet import FakeInternet
from .test_datasource_fixes import STATIC, FakeDatasourceSettings, FakeRenderSession, _Cob
from .test_rss import CHROME
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings

PLACES = [{ "name": "Home", "latitude": 42.33143, "longitude": -83.04575 }, { "name": "Odd", "latitude": None, "longitude": 3 }]
WHERE = { "latitude": 51.5, "longitude": -0.12 }

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: the display, the system and a theme document."""
	def __init__(self, orientation: str, location: Any):
		self.documents = { "display": { "orientation": orientation }, "system": { "location": location }, "theme": { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 } }
	def open(self, name: str):
		return _Cob(self.documents.get(name))

def context(orientation: str = "landscape", key: str|None = "tf-good", places: list|None = None, location: Any = WHERE) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, cast(Any, FakeDatasourceSettings({ "apiKey": key, "places": PLACES if places is None else places })))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, location)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	root.add_service(ConfigurationManager, ConfigurationManager())
	return DataSourceExecutionContext(root, (800, 480), datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))

def storage(key: str|None = "tf-good", hours: float = 0, location: Any = WHERE, orientation: str = "landscape") -> DataSourceExecutionContext:
	"""A context of the map page source with a storage of its own: the API source's settings (nothing kept unless a test asks, most count calls) and the places."""
	folder = tempfile.mkdtemp(prefix="eink-thunderforest-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	save_datasource_settings(cm, "thunderforest", { "apiKey": key, "contentCacheHours": hours, "contentCacheMB": 64, "staleDays": 30 })
	save_datasource_settings(cm, "thunderforest-map", { "places": PLACES })
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("thunderforest-map"))
	root.add_service(DataSourceManager, DataSourceManager({ "thunderforest": ThunderforestApi("thunderforest", "Thunderforest") }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, location)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, (800, 480), datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))

class TestAddress(unittest.TestCase):
	def test_the_address_has_the_style_the_position_the_zoom_the_size_and_the_key(self):
		self.assertEqual(map_address("transport", 42.33143, -83.04575, 12, (800, 480), "k1"), "https://api.thunderforest.com/static/transport/-83.04575,42.33143,12/800x480.png?apikey=k1")

	def test_a_key_is_encoded_and_the_size_and_zoom_are_kept_in_range(self):
		address = map_address("cycle", 0, 0, 99, (5000, 0), "a&b c=d")
		self.assertIn("apikey=a%26b%20c%3Dd", address)
		self.assertIn("/0.00000,0.00000,22/2560x1.png", address)

	def test_only_a_known_style_reaches_the_address(self):
		for style in ("../x", "transport/0,0,1/9x9.png?apikey=x#", "", "satellite"):
			with self.subTest(style), self.assertRaisesRegex(PermanentError, "map style"):
				map_address(style, 0, 0, 1, (10, 10), "k")

	def test_a_status_is_said_in_our_words_and_a_refused_key_is_permanent(self):
		self.assertIsInstance(refusal(401), PermanentError)
		self.assertIsInstance(refusal(403), PermanentError)
		self.assertNotIsInstance(refusal(429), PermanentError)
		self.assertIn("quota", str(refusal(429)))
		self.assertEqual(str(refusal(500)), "Thunderforest answered 500.")

class TestPlace(unittest.TestCase):
	def test_a_named_place_comes_from_the_settings(self):
		self.assertEqual(place_of(context(), "Home"), ("Home", 42.33143, -83.04575))

	def test_no_name_is_the_devices_own_location(self):
		for name in (None, ""):
			self.assertEqual(place_of(context(), name), ("the device's location", 51.5, -0.12))

	def test_a_missing_place_or_position_or_location_is_a_settings_problem_that_says_where(self):
		with self.assertRaisesRegex(PermanentError, "'Gone' is not in the Thunderforest Map settings"):
			place_of(context(), "Gone")
		with self.assertRaisesRegex(PermanentError, "'Odd' has no position"):
			place_of(context(), "Odd")
		for location in (None, {}, { "latitude": 1 }, "here"):
			with self.subTest(location), self.assertRaisesRegex(PermanentError, "no location"):
				place_of(context(location=location), None)

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	async def render(self, params: dict, dsec: DataSourceExecutionContext|None = None):
		dsec = dsec or storage()
		ds = ThunderforestMapAsync("thunderforest-map", "Thunderforest Map")
		state = (await ds.open_async(dsec, params))[0]
		with patch.object(thunderforest_map, "RenderSession", FakeRenderSession):
			return await ds.render_async(dsec, params, state)

	def test_the_api_is_data_only(self):
		from ..datasources.data_source import DataSourceApi
		self.assertIsInstance(ThunderforestApi("thunderforest", "Thunderforest"), DataSourceApi)
		self.assertFalse(hasattr(ThunderforestApi("thunderforest", "Thunderforest"), "render_async"))

	async def test_the_map_is_asked_for_at_the_panels_size_and_drawn_with_its_attribution(self):
		result = await self.render({ "place": "Home", "style": "transport", "zoom": 14 })
		assert result is not None and FakeRenderSession.last is not None
		self.assertEqual([str(r.url) for r in self.fake.requests], ["https://api.thunderforest.com/static/transport/-83.04575,42.33143,14/800x480.png?apikey=tf-good"])
		self.assertIn("eink-billboard", self.fake.requests[0].headers["User-Agent"])
		page = FakeRenderSession.last.params
		self.assertTrue(page["map"].startswith("data:image/png;base64,"))
		self.assertIn("thunderforest", page["attribution"].lower())
		self.assertIn("osm.org/copyright", page["attribution"])
		self.assertNotIn("tf-good", str(page))
		self.assertEqual((result.title, result.image.size), ("Map of Home", (800, 480)))

	async def test_a_portrait_panel_asks_for_a_portrait_map(self):
		result = await self.render({ "style": "atlas", "zoom": 10 }, storage(orientation="portrait"))
		assert result is not None
		self.assertIn("/480x800.png", str(self.fake.requests[0].url))
		self.assertEqual((result.title, result.image.size), ("Map of the device's location", (480, 800)))

	async def test_a_map_is_kept_and_shared_so_the_quota_is_for_new_places(self):
		dsec = storage(hours=168)
		for _ in range(3):
			await self.render({ "place": "Home", "style": "cycle", "zoom": 12 }, dsec)
		self.assertEqual(len(self.fake.requests), 1)
		await self.render({ "place": "Home", "style": "cycle", "zoom": 13 }, dsec)
		self.assertEqual(len(self.fake.requests), 2, "another zoom is another map")

	async def test_a_busy_service_a_refused_key_and_no_key_are_said_in_our_words_without_the_key(self):
		with self.assertRaisesRegex(RuntimeError, "quota") as busy:
			await self.render({ "place": "Home" }, storage(key="tf-busy"))
		self.assertNotIsInstance(busy.exception, PermanentError)
		with self.assertRaisesRegex(PermanentError, "refused the API key") as refused:
			await self.render({ "place": "Home" }, storage(key="sk-secret-wrong"))
		for raised in (busy.exception, refused.exception):
			self.assertNotIn("tf-busy", str(raised))
			self.assertNotIn("sk-secret-wrong", str(raised))
			self.assertIsNone(raised.__cause__, "the service's own error text (which quotes the key) is not chained")
		before = len(self.fake.requests)
		for key in (None, "", "   "):
			with self.subTest(key), self.assertRaisesRegex(PermanentError, "key is not set"):
				await self.render({ "place": "Home" }, storage(key=key))
		self.assertEqual(len(self.fake.requests), before, "nothing is asked without a key")

	async def test_nothing_to_show_is_none(self):
		self.assertIsNone(await ThunderforestMapAsync("thunderforest-map", "Thunderforest Map").render_async(storage(), {}, None))

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The page as Chromium draws it on both orientations, at the display size, with the attribution on it; the images are in .test-output/thunderforest for a look."""
	def setUp(self):
		client_var.set(httpx.AsyncClient(transport=FakeInternet()))

	async def test_pages_are_drawn_at_the_display_size(self):
		folder = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.joinpath(".test-output", "thunderforest")
		folder.mkdir(parents=True, exist_ok=True)
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
			with self.subTest(orientation=orientation):
				dsec = storage(orientation=orientation)
				ds = ThunderforestMapAsync("thunderforest-map", "Thunderforest Map")
				state = (await ds.open_async(dsec, { "place": "Home" }))[0]
				result = await ds.render_async(dsec, { "place": "Home", "style": "transport", "zoom": 12 }, state)
				assert result is not None
				self.assertEqual(result.image.size, size)
				result.image.save(folder.joinpath(f"{orientation}.png"))
				self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")

class TestKeyInLogs(unittest.TestCase):
	def test_the_key_is_hidden_in_a_log_line_of_the_http_client(self):
		record = logging.LogRecord("httpx", logging.INFO, "", 0, 'HTTP Request: GET https://api.thunderforest.com/static/a/1,2,3/4x5.png?apikey=sk-abc123&x=1 "HTTP/1.1 200 OK"', None, None)
		self.assertTrue(HideKey().filter(record))
		self.assertNotIn("sk-abc123", record.getMessage())
		self.assertIn("apikey=***&x=1", record.getMessage())

class TestKeyRoute(WebApiTestBase):
	URL = "/api/datasource/thunderforest/test"

	def ask(self, value) -> dict:
		resp = self.client.post(self.URL, json={ "value": value })
		self.assertEqual(resp.status_code, 200, resp.text)
		return resp.json()

	def test_a_good_key_a_refused_key_and_a_busy_service(self):
		self.assertEqual(self.ask("tf-good"), { "ok": True, "message": "Thunderforest accepts this key." })
		self.assertIn("refused the API key", self.ask("wrong")["message"])
		self.assertIn("quota", self.ask("tf-busy")["message"])

	def test_the_saved_key_is_used_when_the_field_shows_the_mask_or_nothing(self):
		self.write_datasource_settings("thunderforest", { "apiKey": "tf-good" })
		self.assertTrue(self.ask("********")["ok"])
		self.assertTrue(self.ask(None)["ok"])

	def test_nothing_typed_and_nothing_saved_is_a_no_and_the_key_is_not_in_the_answer(self):
		self.assertEqual(self.ask(""), { "ok": False, "message": "Enter an API key first." })
		for key in ("tf-good", "wrong", "tf-busy"):
			self.assertNotIn(key, str(self.ask(key)))

	def test_the_settings_need_the_key(self):
		self.write_datasource_settings("thunderforest", { "apiKey": "tf-good", "contentCacheHours": 168, "contentCacheMB": 64, "staleDays": 30 })
		doc = self.client.get("/api/datasources/thunderforest/settings").json()
		resp = self.client.put("/api/datasources/thunderforest/settings", json={ **doc, "apiKey": None })
		self.assertEqual(resp.status_code, 422)

class TestPlacesSettings(WebApiTestBase):
	def test_a_place_needs_a_position_in_range_and_a_task_picks_one_by_name(self):
		doc = self.client.get("/api/datasources/thunderforest-map/settings").json()
		for place in ({ "name": "Pole", "latitude": 91, "longitude": 0 }, { "name": "Date line", "latitude": 0, "longitude": 181 }, { "name": "", "latitude": 0, "longitude": 0 }, { "name": "Nowhere", "latitude": 0 }):
			with self.subTest(place):
				self.assertEqual(self.client.put("/api/datasources/thunderforest-map/settings", json={ **doc, "places": [place] }).status_code, 422)
		resp = self.client.put("/api/datasources/thunderforest-map/settings", json={ **doc, "places": [{ "name": "Home", "latitude": 42.3, "longitude": -83.0 }] })
		self.assertEqual(resp.status_code, 200, resp.text)
		lookup = self.client.get("/api/datasources/thunderforest-map/lookups/place")
		self.assertEqual(lookup.status_code, 200, lookup.text)
		self.assertEqual([o["value"] for o in lookup.json()], ["Home"])

if __name__ == "__main__":
	unittest.main()
