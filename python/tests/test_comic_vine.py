"""
The Comic Vine API data source (`comicvine-api`, the key, the search and the kept answers) and the Comic Vine Covers page source (`comicvine-covers`), against the fake
internet's Comic Vine (python/tests/fake_internet.py): no key, no cost, no real cover (they are copyrighted).
"""
import atexit
import logging
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import patch

import httpx

from ..datasources.comicvine_covers import comicvine_covers as comic_vine
from ..datasources.comicvine_covers.comicvine_covers import ComicVineCoversAsync
from ..datasources.comicvine_api.comicvine_api import ComicVineApi, HideKey, api_error, parse_issues, parse_volume
from ..datasources.data_source import DataSourceApi, DataSourceExecutionContext, DataSourceManager
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool, client_var
from .fake_internet import COMICVINE_ISSUES, COMICVINE_VOLUME, FakeInternet
from .test_datasource_fixes import FakeSettings
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
API_ID = "comicvine-api"

def fake() -> FakeInternet:
	transport = AsyncHttpWorkerPool.default_transport
	assert isinstance(transport, FakeInternet), "the tests' Comic Vine is the fake internet's"
	return transport

def comicvine_requests(path: str) -> list[httpx.Request]:
	return [r for r in fake().requests if r.url.host == "comicvine.gamespot.com" and r.url.path == path]

def storage(api_key: str|None = "cv-good", **settings) -> ConfigurationManager:
	folder = tempfile.mkdtemp(prefix="eink-comicvine-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	if api_key is not None:
		# nothing is kept unless a test asks (most tests count calls)
		save_datasource_settings(cm, API_ID, { "apiKey": api_key, "volumeCacheHours": 0, "issuesCacheHours": 0, "staleDays": 30, **settings })
	return cm

def context(cm: ConfigurationManager, own: str = API_ID, loaded: dict|None = None, orientation: str = "landscape") -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager(own))
	root.add_service(DataSourceManager, DataSourceManager({ API_ID: ComicVineApi(API_ID, "Comic Vine") } if loaded is None else loaded))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({ "orientation": orientation })))
	return DataSourceExecutionContext(root, (800, 480), NOW)

class TestTheApi(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()
		self.api = ComicVineApi(API_ID, "Comic Vine")

	def test_it_is_data_only(self):
		self.assertIsInstance(self.api, DataSourceApi)
		self.assertFalse(hasattr(self.api, "render_async"))

	async def test_a_search_answers_the_series_and_how_many_issues_it_has(self):
		volume = await self.api.open_async(context(storage()), { "request": "volume", "query": "  test   tales " })
		self.assertEqual(volume, { "id": COMICVINE_VOLUME, "name": "Test Tales", "year": "1951", "issues": COMICVINE_ISSUES, "publisher": "Fixture Press" })
		request = comicvine_requests("/api/search/")[0]
		# the key is a parameter of the address, and the User-Agent is ours (the site refuses the HTTP library's)
		self.assertEqual(request.url.params["api_key"], "cv-good")
		self.assertEqual(request.url.params["query"], "test tales")
		self.assertNotIn("python-httpx", request.headers["user-agent"])

	async def test_a_page_of_issues_has_their_covers(self):
		answer = await self.api.open_async(context(storage()), { "request": "issues", "volume": COMICVINE_VOLUME, "offset": 200 })
		self.assertEqual(answer["total"], COMICVINE_ISSUES)
		self.assertEqual([i["number"] for i in answer["issues"]][:2] + [answer["issues"][-1]["number"]], ["201", "202", "250"])
		first = answer["issues"][0]
		self.assertTrue(first["cover"].startswith("https://comicvine.gamespot.com/a/uploads/scale_large/"), "the size that fits a panel")
		self.assertEqual(comicvine_requests("/api/issues/")[0].url.params["filter"], f"volume:{COMICVINE_VOLUME}")

	async def test_answers_are_kept_and_shared(self):
		cm = storage(volumeCacheHours=168, issuesCacheHours=24)
		for _ in range(3):
			await self.api.open_async(context(cm), { "request": "volume", "query": "Test Tales" })
			await self.api.open_async(context(cm), { "request": "issues", "volume": COMICVINE_VOLUME, "offset": 0 })
		self.assertEqual((len(comicvine_requests("/api/search/")), len(comicvine_requests("/api/issues/"))), (1, 1))
		# another page is another answer
		await self.api.open_async(context(cm), { "request": "issues", "volume": COMICVINE_VOLUME, "offset": 100 })
		self.assertEqual(len(comicvine_requests("/api/issues/")), 2)

	async def test_the_failures_are_in_our_words_and_never_hold_the_key(self):
		cases = [
			(storage(None), PermanentError, "The Comic Vine API key is not set"),
			(storage("cv-wrongKEY123"), PermanentError, "Comic Vine refused the API key"),
			(storage("cv-busy"), RuntimeError, "too many requests"),
		]
		for cm, kind, text in cases:
			with self.subTest(text):
				with self.assertRaises(kind) as caught:
					await self.api.open_async(context(cm), { "request": "volume", "query": "Test Tales" })
				self.assertIn(text, str(caught.exception))
				self.assertNotIn("KEY123", str(caught.exception))

	async def test_a_search_that_matches_nothing_is_a_settings_problem(self):
		with self.assertRaises(PermanentError) as caught:
			await self.api.open_async(context(storage()), { "request": "volume", "query": "nothing-here" })
		self.assertIn("no series that matches", str(caught.exception))
		with self.assertRaises(PermanentError):
			await self.api.open_async(context(storage()), { "request": "volume", "query": "   " })

	async def test_what_is_asked_is_checked(self):
		for params in ({ "request": "issues", "volume": "4050; drop", "offset": 0 }, { "request": "issues", "volume": COMICVINE_VOLUME, "offset": -1 },
				{ "request": "issues", "volume": True, "offset": 0 }, { "request": "cover" }):
			with self.subTest(params), self.assertRaises(PermanentError):
				await self.api.open_async(context(storage()), params)
		self.assertEqual(comicvine_requests("/api/issues/"), [])

class TestParsing(unittest.TestCase):
	def test_the_search_takes_the_first_match(self):
		self.assertEqual(parse_volume({ "results": [{ "id": 7, "name": "A", "count_of_issues": 3 }, { "id": 8, "name": "B" }] })["id"], 7)
		self.assertEqual(parse_volume({ "results": [{ "id": 7, "name": "A", "publisher": None, "start_year": None }] })["publisher"], "")
		with self.assertRaises(PermanentError):
			parse_volume({ "results": [{ "name": "no id" }] })

	def test_an_issue_without_a_cover_or_with_a_cover_we_would_not_fetch_is_left_out(self):
		body = { "number_of_total_results": 4, "results": [
			{ "issue_number": "1", "image": { "original_url": "https://x.test/1.jpg" } },
			{ "issue_number": "2", "image": None },
			{ "issue_number": "3", "image": { "super_url": "http://x.test/3.jpg" } },
			"not an issue",
			{ "issue_number": "5", "name": "Five", "cover_date": "1960-05-01", "image": { "super_url": "https://x.test/5s.jpg", "original_url": "https://x.test/5.jpg" } }] }
		parsed = parse_issues(body)
		self.assertEqual(parsed["total"], 4)
		self.assertEqual([(i["number"], i["cover"]) for i in parsed["issues"]], [("1", "https://x.test/1.jpg"), ("5", "https://x.test/5s.jpg")])

	def test_the_statuses_mean(self):
		self.assertIsInstance(api_error(401, 100), PermanentError)
		self.assertIsInstance(api_error(200, 100), PermanentError)
		self.assertNotIsInstance(api_error(420, 107), PermanentError)
		self.assertEqual(str(api_error(500)), "Comic Vine answered 500.")

	def test_the_key_is_hidden_in_what_the_http_client_logs(self):
		record = logging.LogRecord("httpx", logging.INFO, "", 0, 'HTTP Request: %s %s "%s"', ("GET", "https://comicvine.gamespot.com/api/search/?api_key=SECRET123&format=json", "HTTP/1.1 200 OK"), None)
		HideKey().filter(record)
		self.assertNotIn("SECRET123", record.getMessage())
		self.assertIn("api_key=***", record.getMessage())

class TestTheCovers(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()
		client_var.set(httpx.AsyncClient(transport=fake()))
		self.source = ComicVineCoversAsync("comicvine-covers", "Comic Vine Covers")
		self.cm = storage()
		self.dsec = context(self.cm, own="comicvine-covers")

	async def test_a_page_of_covers_in_a_random_order_titled_by_issue(self):
		with patch.object(comic_vine.random, "randrange", return_value=1):
			covers = await self.source.open_async(self.dsec, { "series": "Test Tales" })
		self.assertEqual(len(covers), 100)
		self.assertEqual(comicvine_requests("/api/issues/")[0].url.params["offset"], "100")
		titles = [c["title"] for c in covers]
		self.assertEqual(sorted(titles)[0][:10], "Test Tales")
		self.assertIn("Test Tales #150 (1963)", titles)
		self.assertNotEqual(titles, sorted(titles, key=lambda t: int(t.split("#")[1].split()[0])), "shuffled")

	async def test_the_last_page_is_shorter(self):
		with patch.object(comic_vine.random, "randrange", return_value=2):
			covers = await self.source.open_async(self.dsec, { "series": "Test Tales" })
		self.assertEqual(len(covers), COMICVINE_ISSUES - 200)

	async def test_a_series_that_has_shrunk_falls_back_to_the_first_page(self):
		with patch.object(comic_vine.random, "randrange", return_value=2), patch.object(comic_vine, "PAGE", 100):
			async def shrunk(self_, dsec, params):
				if params["request"] == "issues" and params["offset"] > 0:
					return { "total": 50, "issues": [] }
				return await original(self_, dsec, params)
			original = ComicVineApi.open_async
			with patch.object(ComicVineApi, "open_async", shrunk):
				covers = await self.source.open_async(self.dsec, { "series": "Test Tales" })
		self.assertEqual(len(covers), 100)

	async def test_a_cover_is_fitted_with_a_blurred_margin(self):
		with patch.object(comic_vine.random, "randrange", return_value=0):
			covers = await self.source.open_async(self.dsec, { "series": "Test Tales" })
		result = await self.source.render_async(self.dsec, { "series": "Test Tales" }, covers[0])
		assert result is not None and result.image is not None
		# a portrait cover on a landscape panel: the panel's size, with the margin and not white bars
		self.assertEqual(result.image.size, (800, 480))
		self.assertNotEqual(result.image.getpixel((5, 240)), (255, 255, 255))
		self.assertTrue(result.title.startswith("Test Tales #"))
		portrait = context(self.cm, own="comicvine-covers", orientation="portrait")
		turned = await self.source.render_async(portrait, { "series": "Test Tales" }, covers[0])
		assert turned is not None and turned.image is not None
		self.assertEqual(turned.image.size, (480, 800))

	async def test_the_problems_are_the_settings_to_fix(self):
		for params, loaded, text in (({ "series": "  " }, None, "Enter the series"), ({ "series": "nothing-here" }, None, "no series that matches"),
				({ "series": "Test Tales" }, {}, "The Comic Vine data source is not available")):
			with self.subTest(text), self.assertRaises(PermanentError) as caught:
				await self.source.open_async(context(self.cm, own="comicvine-covers", loaded=loaded), params)
			self.assertIn(text, str(caught.exception))
		with self.assertRaises(PermanentError) as keyless:
			await self.source.open_async(context(storage(None), own="comicvine-covers"), { "series": "Test Tales" })
		self.assertIn("API key is not set", str(keyless.exception))

	async def test_a_state_that_is_not_ours_draws_nothing(self):
		self.assertIsNone(await self.source.render_async(self.dsec, {}, None))
		self.assertIsNone(await self.source.render_async(self.dsec, {}, { "url": "" }))

class TestTheRoute(WebApiTestBase):
	BASE = "/api/datasource/comicvine-api"

	def setUp(self):
		super().setUp()
		logging.getLogger("python.datasources.comicvine_api").setLevel(logging.CRITICAL)

	def test_the_test_button_says_which_series_the_search_matches(self):
		answer = lambda value: self.client.post(f"{self.BASE}/test", json={ "value": value })
		self.assertEqual(answer("Test Tales").json()["message"], "The Comic Vine API key is not set. Add it in the Comic Vine settings.")
		self.write_datasource_settings(API_ID, { "apiKey": "cv-good", "volumeCacheHours": 0 })
		found = answer("Test Tales")
		self.assertEqual(found.status_code, 200)
		self.assertEqual(found.json(), { "ok": True, "message": f"Test Tales (Fixture Press, 1951), {COMICVINE_ISSUES} issues" })
		self.assertEqual(answer("nothing-here").json()["ok"], False)
		self.assertEqual(answer("").json(), { "ok": False, "message": "Enter a series to search for." })
		self.write_datasource_settings(API_ID, { "apiKey": "cv-wrongKEY123" })
		wrong = answer("Test Tales")
		self.assertEqual(wrong.status_code, 200)
		self.assertIn("refused the API key", wrong.json()["message"])
		self.assertNotIn("wrongKEY123", wrong.text)

	def test_the_key_is_never_served(self):
		self.write_datasource_settings(API_ID, { "apiKey": "cv-good", "volumeCacheHours": 0 })
		served = self.client.get("/api/datasources/comicvine-api/settings")
		self.assertEqual(served.status_code, 200)
		self.assertNotIn("cv-good", served.text)
