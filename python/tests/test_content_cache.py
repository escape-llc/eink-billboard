"""
A data source's kept downloads (#400, `datasources/content_cache.py`): fresh bytes are read from disk with nothing sent, an expired download is asked for again with the origin's
validators, the headers decide how long, the pool is bounded and tidied, and a refused address is never hidden by an old copy.
"""
import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx

from ..datasources import content_cache, keeping
from ..datasources.content_cache import BLOB_PREFIX, blob_name, download_for, fetch_cached, freshness, retain
from ..datasources.data_source import DataSourceExecutionContext
from ..model.configuration_manager import DatasourceConfigurationManager
from ..model.service_container import ServiceContainer
from ..task.async_http_worker_pool import client_var
from ..task.message_router import MessageRouter
from ..task.messages import Telemetry
from ..utils import url_guard
from ..utils.url_guard import UrlRefused
from .utils import temp_configuration_manager

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
URL = "https://pics.example/today.jpg?key=SECRET"

async def public(host: str, port: int) -> list[str]:
	return ["93.184.216.34"]

class Origin:
	"""A fake origin that counts what it was asked and answers with the headers it is given."""
	def __init__(self, body: bytes = b"picture", headers: dict[str, str]|None = None):
		self.body, self.headers = body, headers or {}
		self.requests: list[httpx.Request] = []
		self.fail: Exception|None = None
	def __call__(self, request: httpx.Request) -> httpx.Response:
		self.requests.append(request)
		if self.fail is not None:
			raise self.fail
		etag = self.headers.get("ETag")
		if etag and request.headers.get("If-None-Match") == etag:
			return httpx.Response(304, headers=self.headers)
		return httpx.Response(200, content=self.body, headers={ "Content-Type": "image/jpeg", **self.headers })

class TestFreshness(unittest.TestCase):
	ceiling = timedelta(hours=24)
	def test_the_origins_headers_decide_never_beyond_the_ceiling(self):
		for headers, keep, life in (
			({ "Cache-Control": "max-age=3600" }, True, timedelta(hours=1)),
			({ "Cache-Control": "public, max-age=3600", "Age": "600" }, True, timedelta(minutes=50)),
			({ "Cache-Control": "max-age=999999999" }, True, self.ceiling),
			({ "Cache-Control": "no-cache" }, True, timedelta(0)),
			({ "Cache-Control": "no-store, max-age=60" }, False, timedelta(0)),
			({ "Cache-Control": "max-age=-5" }, True, timedelta(0)),
			({ "Cache-Control": "max-age=soon" }, True, self.ceiling),
			({ "Expires": "Tue, 20 Oct 2026 14:00:00 GMT", "Date": "Tue, 20 Oct 2026 12:00:00 GMT" }, True, timedelta(hours=2)),
			({ "Expires": "0" }, True, timedelta(0)),
			({ "Cache-Control": "max-age=60", "Expires": "Wed, 21 Oct 2026 12:00:00 GMT" }, True, timedelta(minutes=1)),
			({}, True, self.ceiling),
		):
			with self.subTest(**{ "headers": str(headers) }):
				got = freshness(headers, NOW, self.ceiling)
				self.assertEqual((got.keep, got.lifetime), (keep, life))

class CacheTestBase(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.dscm = self.cm.datasource_manager("wpotd")
		patcher = patch.object(url_guard, "_resolve", public)
		patcher.start()
		self.addCleanup(patcher.stop)
		keeping._last_prune.clear()
	def get(self, origin: Origin, now: datetime = NOW, url: str = URL, settings: dict[str, Any]|None = None, **kw: Any) -> bytes:
		async def run() -> bytes:
			async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
				got = await fetch_cached(self.dscm, { "contentCacheHours": 24, **(settings or {}) }, client, url, now, **kw)
				return got.getvalue()
		return asyncio.run(run())
	def folder(self) -> list[str]:
		# the data source's own settings are seeded beside what it keeps
		return sorted(f for f in os.listdir(self.dscm.ROOT_PATH) if f != "settings.json") if os.path.isdir(self.dscm.ROOT_PATH) else []

class TestKeeping(CacheTestBase):
	def test_a_fresh_download_is_read_from_disk_and_nothing_is_sent(self):
		origin = Origin()
		self.assertEqual(self.get(origin), b"picture")
		self.assertEqual(self.get(origin, NOW + timedelta(hours=23)), b"picture")
		self.assertEqual(len(origin.requests), 1)

	def test_the_address_is_in_no_file_name_or_file(self):
		self.get(Origin())
		self.assertEqual([f for f in self.folder() if "SECRET" in f or "pics" in f], [])
		for f in self.folder():
			with open(os.path.join(self.dscm.ROOT_PATH, f), "rb") as fx:
				self.assertNotIn(b"SECRET", fx.read())

	def test_an_expired_download_is_asked_for_again_with_its_validators_and_a_304_keeps_the_bytes(self):
		origin = Origin(headers={ "ETag": '"v1"', "Cache-Control": "max-age=3600" })
		self.get(origin)
		self.assertEqual(self.get(origin, NOW + timedelta(minutes=30)), b"picture")
		self.assertEqual(len(origin.requests), 1)
		self.assertEqual(self.get(origin, NOW + timedelta(hours=2)), b"picture")
		self.assertEqual(len(origin.requests), 2)
		self.assertEqual(origin.requests[1].headers["If-None-Match"], '"v1"')
		# the 304 started a new fresh period from its own time
		self.assertEqual(self.get(origin, NOW + timedelta(hours=2, minutes=30)), b"picture")
		self.assertEqual(len(origin.requests), 2)

	def test_a_changed_download_replaces_the_old_one(self):
		origin = Origin(b"one", { "ETag": '"v1"', "Cache-Control": "max-age=60" })
		self.get(origin)
		origin.body, origin.headers = b"two!", { "ETag": '"v2"', "Cache-Control": "max-age=60" }
		self.assertEqual(self.get(origin, NOW + timedelta(minutes=5)), b"two!")
		self.assertEqual(self.get(origin, NOW + timedelta(minutes=5, seconds=30)), b"two!")
		self.assertEqual(len(origin.requests), 2)

	def test_no_store_and_a_ceiling_of_zero_keep_nothing(self):
		origin = Origin(headers={ "Cache-Control": "no-store" })
		self.get(origin)
		self.get(origin)
		self.assertEqual(len(origin.requests), 2)
		self.assertEqual(self.folder(), [])
		plain = Origin()
		self.get(plain, settings={ "contentCacheHours": 0 })
		self.get(plain, settings={ "contentCacheHours": 0 })
		self.assertEqual((len(plain.requests), self.folder()), (2, []))

	def test_an_origin_that_says_nothing_is_trusted_for_the_ceiling(self):
		origin = Origin()
		self.get(origin)
		self.get(origin, NOW + timedelta(hours=25))
		self.assertEqual(len(origin.requests), 2)
		# no validators were ever given: the second ask was a plain one
		self.assertNotIn("If-None-Match", origin.requests[1].headers)

	def test_an_origin_that_does_not_answer_gives_the_old_bytes_and_raises_when_there_are_none(self):
		origin = Origin(headers={ "Cache-Control": "max-age=60" })
		self.get(origin)
		origin.fail = httpx.ConnectError("down")
		with self.assertLogs(content_cache.__name__, level="WARNING"):
			self.assertEqual(self.get(origin, NOW + timedelta(hours=1)), b"picture")
		with self.assertRaises(httpx.ConnectError):
			self.get(origin, url="https://pics.example/other.jpg")

	def test_a_refused_address_is_never_hidden_by_an_old_copy(self):
		origin = Origin(headers={ "Cache-Control": "max-age=60" })
		self.get(origin)
		async def loopback(host: str, port: int) -> list[str]:
			return ["127.0.0.1"]
		with patch.object(url_guard, "_resolve", loopback), self.assertRaises(UrlRefused):
			self.get(origin, NOW + timedelta(hours=1))

	def test_a_description_without_its_bytes_is_a_miss(self):
		origin = Origin()
		self.get(origin)
		os.remove(os.path.join(self.dscm.ROOT_PATH, blob_name(URL) + ".bin"))
		self.assertEqual(self.get(origin, NOW + timedelta(minutes=1)), b"picture")
		self.assertEqual(len(origin.requests), 2)

	def test_the_content_type_check_applies_to_what_is_downloaded(self):
		with self.assertRaisesRegex(RuntimeError, "Unexpected content type"):
			self.get(Origin(), ctok=lambda ct: ct.startswith("text/"))
		self.assertEqual(self.folder(), [])

class TestTelemetry(CacheTestBase):
	"""What a download tells the web app: the outcome, the data source and the size, never the address."""
	def outcomes(self, steps: list[tuple[Origin, timedelta]], settings: dict[str, Any]|None = None, url: str = URL) -> list[str]:
		told: list[str] = []
		for origin, later in steps:
			self.get(origin, NOW + later, url=url, settings=settings, report=lambda outcome, size: told.append(outcome))
		return told

	def test_hit_miss_revalidated_stale_and_bypass(self):
		origin = Origin(headers={ "ETag": '"v1"', "Cache-Control": "max-age=60" })
		self.assertEqual(self.outcomes([(origin, timedelta(0)), (origin, timedelta(seconds=30)), (origin, timedelta(minutes=5))]), ["miss", "hit", "revalidated"])
		origin.fail = httpx.ConnectError("down")
		self.assertEqual(self.outcomes([(origin, timedelta(hours=2))]), ["stale"])
		self.assertEqual(self.outcomes([(Origin(headers={ "Cache-Control": "no-store" }), timedelta(0))], url="https://pics.example/b.jpg"), ["bypass"])
		self.assertEqual(self.outcomes([(Origin(), timedelta(0))], { "contentCacheHours": 0 }, url="https://pics.example/c.jpg"), ["bypass"])

	def test_the_data_source_sends_an_event_without_the_address(self):
		sent: list[Telemetry] = []
		class Router(MessageRouter):
			def send(self, route, msg):  # type: ignore[override]
				if route == "telemetry":
					sent.append(msg)  # type: ignore[arg-type]
		services = ServiceContainer()
		services.add_service(DatasourceConfigurationManager, self.dscm)
		services.add_service(MessageRouter, Router())
		dsec = DataSourceExecutionContext(services, (800, 480), NOW)
		origin = Origin()
		async def run() -> None:
			client_var.set(httpx.AsyncClient(transport=httpx.MockTransport(origin)))
			for _ in range(2):
				await download_for(dsec, URL, default_hours=24)
		asyncio.run(run())
		self.assertEqual([m.values["kind"] for m in sent], ["cache-miss", "cache-hit"])
		self.assertEqual(sent[1].name, "data-source")
		self.assertEqual((sent[1].values["datasource"], sent[1].values["bytes"]), ("wpotd", len(b"picture")))
		self.assertNotIn("SECRET", str([m.values for m in sent]))

class TestThePool(CacheTestBase):
	def test_the_pool_is_bounded_and_the_oldest_use_goes_first(self):
		body = b"x" * 400_000
		for i in range(3):
			self.get(Origin(body), NOW + timedelta(minutes=i), url=f"https://pics.example/{i}.jpg", settings={ "contentCacheMB": 1 })
		kept = set(self.dscm.list_blobs(BLOB_PREFIX))
		self.assertEqual(kept, { blob_name("https://pics.example/1.jpg"), blob_name("https://pics.example/2.jpg") })
		# its description went with it
		self.assertEqual(set(self.dscm.list_files(BLOB_PREFIX)), kept)

	def test_a_download_bigger_than_the_pool_is_used_and_not_kept(self):
		origin = Origin(b"x" * 600_000)
		self.assertEqual(len(self.get(origin, settings={ "contentCacheMB": 0.5 })), 600_000)
		self.assertEqual(self.folder(), [])

	def test_what_the_list_no_longer_holds_is_removed_for_that_scope_only(self):
		urls = [f"https://pics.example/{i}.jpg" for i in range(3)]
		for u in urls:
			self.get(Origin(), url=u, scope="feed-a")
		self.get(Origin(), url="https://pics.example/b.jpg", scope="feed-b")
		self.assertEqual(retain(self.dscm, "feed-a", urls[:1]), 2)
		self.assertEqual(set(self.dscm.list_blobs(BLOB_PREFIX)), { blob_name(urls[0]), blob_name("https://pics.example/b.jpg") })

	def test_files_unused_for_stale_days_are_removed(self):
		self.get(Origin(), url="https://pics.example/old.jpg")
		keeping._last_prune.clear()
		self.get(Origin(), NOW + timedelta(days=40), url="https://pics.example/new.jpg", settings={ "staleDays": 30 })
		self.assertEqual(self.dscm.list_blobs(BLOB_PREFIX), [blob_name("https://pics.example/new.jpg")])
		self.assertEqual(self.dscm.list_files(BLOB_PREFIX), [blob_name("https://pics.example/new.jpg")])

class TestBackupAndFolders(CacheTestBase):
	def test_a_backup_holds_no_kept_download(self):
		self.get(Origin())
		self.assertEqual(self.dscm.list_blobs(BLOB_PREFIX), [blob_name(URL)])
		self.assertEqual([f for f in self.cm.backup_files() if BLOB_PREFIX in f or f.endswith(".bin")], [])

	def test_a_data_source_without_downloads_has_no_folder(self):
		self.assertEqual(self.dscm.list_blobs(BLOB_PREFIX), [])
		self.assertEqual(self.dscm.read_blob("blob-nothing"), None)

if __name__ == "__main__":
	unittest.main()
