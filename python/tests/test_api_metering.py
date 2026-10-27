"""
API metering (#440, `datasources/metering.py`): the calls an API data source sends (by status, with the bytes), the cache outcomes that spared a call, the days they are kept by,
what survives a restart, and that every API data source's client is a counted one.
"""
import asyncio
import json
import os
import ssl
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx

from ..datasources import keeping
from ..datasources.content_cache import fetch_cached
from ..datasources.metering import METER, STATE_NAME, USAGE_VERSION, MeteredClient, Quota, QuotaUsedUp, UsageMeter, failure_kind
from ..datasources.response_cache import cached
from ..utils import url_guard
from .test_content_cache import Origin, public
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

def only(meter: UsageMeter, source: str = "svc") -> dict[str, Any]:
	return next(entry for entry in meter.report() if entry["id"] == source)

class TestCounting(unittest.TestCase):
	def setUp(self):
		self.now = NOW
		self.meter = UsageMeter(lambda: self.now)

	def test_calls_are_counted_by_status_and_by_why_there_was_none_with_their_bytes(self):
		self.meter.call("svc", 200, None, 10, 500)
		self.meter.call("svc", 200, None, 0, 300)
		self.meter.call("svc", 429, None, 0, 20)
		self.meter.call("svc", None, "timeout", 5, 0)
		today = only(self.meter)["today"]
		self.assertEqual((today["calls"], today["sent"], today["received"]), (4, 15, 820))
		self.assertEqual(today["status"], { "200": 2, "429": 1, "timeout": 1 })

	def test_the_service_saying_too_many_requests_is_remembered_with_its_time(self):
		self.meter.call("svc", 200, None, 0, 0)
		self.assertIsNone(only(self.meter)["lastLimited"])
		self.meter.call("svc", 429, None, 0, 0)
		self.assertEqual(only(self.meter)["lastLimited"], NOW.isoformat())

	def test_the_periods_are_the_device_days(self):
		for days_ago in (40, 20, 6, 1, 0):
			self.now = NOW - timedelta(days=days_ago)
			self.meter.call("svc", 200, None, 0, 0)
		self.now = NOW
		entry = only(self.meter)
		self.assertEqual((entry["today"]["calls"], entry["week"]["calls"]), (1, 3))
		# 40 days ago is September; October so far is the 21st back to the 1st
		self.assertEqual(entry["month"]["calls"], 4)

	def test_the_cache_hit_rate_and_the_bytes_it_saved(self):
		self.meter.cache("svc", "miss", 1000)
		for outcome, size in (("hit", 1000), ("hit", 1000), ("coalesced", 1000), ("revalidated", 400), ("stale", 1000), ("bypass", 5)):
			self.meter.cache("svc", outcome, size)
		today = only(self.meter)["today"]
		# 4 of the 6 lookups were answered without a download (a bypass is a cache that was off, and is no lookup)
		self.assertEqual(today["hitRate"], round(4 / 6, 3))
		self.assertEqual(today["bytesSaved"], 3400)
		self.assertEqual(today["cache"]["hit"], 2)

	def test_a_source_that_asked_nothing_has_no_rate(self):
		self.meter.call("svc", 200, None, 0, 0)
		self.assertIsNone(only(self.meter)["today"]["hitRate"])

class TestQuota(unittest.TestCase):
	"""The plan the user says they have (#586): this period's calls against it, the period starting on the reset day."""
	def setUp(self):
		self.now = NOW
		self.meter = UsageMeter(lambda: self.now)

	def test_a_period_starts_on_the_reset_day_of_this_month_or_last(self):
		q = Quota(100, 15)
		self.assertEqual(q.period(date(2026, 10, 21)), (date(2026, 10, 15), date(2026, 11, 15)))
		self.assertEqual(q.period(date(2026, 10, 15)), (date(2026, 10, 15), date(2026, 11, 15)))
		self.assertEqual(q.period(date(2026, 10, 14)), (date(2026, 9, 15), date(2026, 10, 15)))
		# across a year, and the first of the month
		self.assertEqual(Quota(100, 28).period(date(2027, 1, 3)), (date(2026, 12, 28), date(2027, 1, 28)))
		self.assertEqual(Quota(100).period(date(2026, 12, 31)), (date(2026, 12, 1), date(2027, 1, 1)))

	def test_the_calls_since_the_reset_day_are_counted_against_the_limit(self):
		for days_ago in (30, 10, 7, 6, 0, 0):
			self.now = NOW - timedelta(days=days_ago)
			self.meter.call("svc", 200, None, 0, 0)
		self.now = NOW
		# the 21st with the plan resetting on the 15th: the period began on the 15th, six days back, so the 6, 0 and 0 count
		entry = next(e for e in self.meter.report({ "svc": Quota(10, 15) }))
		self.assertEqual(entry["quota"], { "limit": 10, "resetDay": 15, "used": 3, "percent": 30.0, "since": "2026-10-15", "resets": "2026-11-15" })

	def test_failed_calls_count_too_and_a_source_with_no_quota_has_none(self):
		self.meter.call("svc", 429, None, 0, 0)
		self.meter.call("svc", None, "timeout", 0, 0)
		self.meter.call("other", 200, None, 0, 0)
		report = { e["id"]: e for e in self.meter.report({ "svc": Quota(4) }) }
		self.assertEqual(report["svc"]["quota"]["used"], 2)
		self.assertIsNone(report["other"]["quota"])

	def test_a_source_with_a_quota_is_reported_before_its_first_call(self):
		entry = self.meter.report({ "new": Quota(500) })[0]
		self.assertEqual((entry["id"], entry["month"]["calls"], entry["quota"]["used"], entry["quota"]["percent"]), ("new", 0, 0, 0.0))

	def test_a_period_is_never_longer_than_the_days_kept(self):
		for reset_day in range(1, 29):
			for month in range(1, 13):
				start, nxt = Quota(1, reset_day).period(date(2026, month, 28))
				self.assertLessEqual((nxt - start).days, 31)

class TestBudgetGuard(unittest.TestCase):
	"""Once a source has used the plan the user set, its calls are not sent (#586): what it kept is used, and with nothing kept the failure says so."""
	def setUp(self):
		self.now = NOW
		self.plans = { "svc": Quota(3) }
		self.meter = UsageMeter(lambda: self.now, lambda: self.plans)
		self.told: list[tuple[str, int, int]] = []
		self.meter.on_quota = lambda source, quota, used: self.told.append((source, quota.limit, used))

	def send(self, n: int = 1):
		"""`n` calls through a metered client that answers 200; returns how many reached the transport."""
		sent = []
		def handler(request):
			sent.append(1)
			return httpx.Response(200, content=b"ok")
		async def go():
			async with MeteredClient("svc", self.meter, transport=httpx.MockTransport(handler)) as client:
				for _ in range(n):
					await client.get("https://svc.example/x")
		asyncio.run(go())
		return len(sent)

	def test_calls_go_until_the_plan_is_used_and_then_are_not_sent(self):
		self.assertEqual(self.send(3), 3)
		with self.assertRaises(QuotaUsedUp) as caught:
			self.send(1)
		# in our words: the source, the limit and when it asks again; never an address
		self.assertIn("'svc' has used its quota of 3 calls", str(caught.exception))
		self.assertIn("Nov 1", str(caught.exception))
		self.assertNotIn("svc.example", str(caught.exception))
		# the refused call is not counted: the meter says 3
		self.assertEqual(only(self.meter)["today"]["calls"], 3)

	def test_a_source_with_no_plan_is_never_stopped(self):
		self.plans = {}
		self.meter._quotas_at = None
		self.assertEqual(self.send(10), 10)

	def test_the_period_resetting_lets_calls_through_again(self):
		self.assertEqual(self.send(3), 3)
		with self.assertRaises(QuotaUsedUp):
			self.send(1)
		self.now = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
		self.assertEqual(self.send(1), 1)

	def test_raising_the_plan_lets_calls_through_after_the_settings_are_read_again(self):
		self.assertEqual(self.send(3), 3)
		with self.assertRaises(QuotaUsedUp):
			self.send(1)
		self.plans = { "svc": Quota(10) }
		# the plans are read at most every QUOTA_REFRESH_SECONDS
		self.meter._quotas_at = None
		self.assertEqual(self.send(1), 1)

	def test_reaching_the_plan_is_told_once_for_the_period(self):
		self.send(3)
		self.assertEqual(self.told, [("svc", 3, 3)])
		for _ in range(3):
			with self.assertRaises(QuotaUsedUp):
				self.send(1)
		self.assertEqual(len(self.told), 1)
		# the next period is told again
		self.now = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
		self.meter._quotas_at = None
		self.send(3)
		self.assertEqual(len(self.told), 2)

	def test_a_plan_that_cannot_be_read_keeps_the_last_one(self):
		self.send(1)
		def broken():
			raise OSError("disk")
		self.meter._quota_source = broken
		self.meter._quotas_at = None
		self.assertEqual(self.send(1), 1)
		self.assertEqual(self.meter._quotas, { "svc": Quota(3) })

class TestKeeping(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.meter = UsageMeter(lambda: NOW)
		self.addCleanup(self.meter.close)

	def stored(self) -> dict[str, Any]:
		return self.cm.state_file(STATE_NAME).get()[1]

	def test_the_counts_survive_a_restart_and_the_new_run_adds_to_them(self):
		self.meter.attach(self.cm)
		self.meter.call("svc", 200, None, 1, 2)
		self.meter.cache("svc", "hit", 7)
		self.meter.close()
		self.assertEqual(self.stored()["_version"], USAGE_VERSION)
		again = UsageMeter(lambda: NOW)
		self.addCleanup(again.close)
		again.attach(self.cm)
		again.call("svc", 404, None, 0, 0)
		today = only(again)["today"]
		self.assertEqual((today["calls"], today["received"], today["cache"]), (2, 2, { "hit": 1 }))
		self.assertEqual(today["status"], { "200": 1, "404": 1 })

	def test_what_was_counted_before_the_storage_was_known_is_kept_too(self):
		self.meter.call("svc", 200, None, 0, 0)
		self.meter.attach(self.cm)
		self.meter.close()
		self.assertEqual(self.stored()["sources"]["svc"]["days"]["2026-10-21"]["calls"], 1)

	def test_nothing_is_written_when_nothing_changed(self):
		self.meter.attach(self.cm)
		with patch.object(self.cm, "state_file", side_effect=AssertionError("written")):
			self.meter.flush()
		self.meter.call("svc", 200, None, 0, 0)
		self.meter.flush()
		with patch.object(self.cm, "state_file", side_effect=AssertionError("written")):
			self.meter.flush()

	def test_only_the_last_31_days_are_kept(self):
		meter = UsageMeter(lambda: NOW - timedelta(days=45))
		meter.attach(self.cm)
		meter.call("svc", 200, None, 0, 0)
		meter.close()
		self.meter.attach(self.cm)
		self.meter.call("svc", 200, None, 0, 0)
		self.meter.close()
		self.assertEqual(sorted(self.stored()["sources"]["svc"]["days"]), ["2026-10-21"])

	def test_a_file_from_a_newer_version_is_not_trusted_or_changed(self):
		cob = self.cm.state_file(STATE_NAME)
		rev, _ = cob.get()
		cob.save(rev, { "_version": USAGE_VERSION + 1, "sources": { "svc": { "days": { "2026-10-21": { "calls": 99 } } } } })
		self.meter.attach(self.cm)
		self.assertEqual(self.meter.report(), [])

	def test_a_damaged_file_is_no_history_and_stops_nothing(self):
		cob = self.cm.state_file(STATE_NAME)
		rev, _ = cob.get()
		cob.save(rev, { "_version": USAGE_VERSION, "sources": { "svc": { "days": { "2026-10-21": { "calls": "many", "status": [1] }, "nonsense": 4 } }, "other": 5 } })
		self.meter.attach(self.cm)
		self.meter.call("svc", 200, None, 0, 0)
		self.assertEqual(only(self.meter)["today"]["calls"], 1)

	def test_a_file_that_cannot_be_written_does_not_stop_a_call(self):
		self.meter.attach(self.cm)
		self.meter.call("svc", 200, None, 0, 0)
		with patch.object(self.cm, "state_file", side_effect=OSError("disk full")):
			self.meter.flush()
		self.assertEqual(only(self.meter)["today"]["calls"], 1)

class TestClient(unittest.TestCase):
	def setUp(self):
		self.meter = UsageMeter(lambda: NOW)

	def run_client(self, handler, request, **kw):
		async def go():
			async with MeteredClient("svc", self.meter, transport=httpx.MockTransport(handler), **kw) as client:
				return await request(client)
		return asyncio.run(go())

	def test_a_call_is_counted_with_its_status_and_the_bytes_of_the_bodies(self):
		self.run_client(lambda r: httpx.Response(200, content=b"hello"), lambda c: c.post("https://svc.example/x?key=SECRET", content=b"abcd"))
		today = only(self.meter)["today"]
		self.assertEqual((today["calls"], today["sent"], today["received"], today["status"]), (1, 4, 5, { "200": 1 }))

	def test_a_refusal_is_a_call_and_a_429_is_remembered(self):
		self.run_client(lambda r: httpx.Response(429, content=b"slow down"), lambda c: c.get("https://svc.example/x"))
		entry = only(self.meter)
		self.assertEqual(entry["today"]["status"], { "429": 1 })
		self.assertEqual(entry["lastLimited"], NOW.isoformat())

	def test_a_call_that_got_no_answer_says_why_and_still_raises(self):
		def timeout(request):
			raise httpx.ReadTimeout("slow", request=request)
		with self.assertRaises(httpx.ReadTimeout):
			self.run_client(timeout, lambda c: c.get("https://svc.example/x"))
		self.assertEqual(only(self.meter)["today"]["status"], { "timeout": 1 })

	def test_why_a_connection_failed(self):
		bad = httpx.ConnectError("no")
		self.assertEqual(failure_kind(bad), "connect")
		secure = httpx.ConnectError("no")
		secure.__cause__ = ssl.SSLError("certificate")
		self.assertEqual(failure_kind(secure), "tls")
		self.assertEqual(failure_kind(httpx.ReadTimeout("slow")), "timeout")
		self.assertEqual(failure_kind(httpx.DecodingError("x")), "error")

	def test_every_hop_of_a_redirect_is_a_call_the_service_sees(self):
		def handler(request):
			if request.url.path == "/a":
				return httpx.Response(302, headers={ "Location": "https://svc.example/b" })
			return httpx.Response(200, content=b"there")
		self.run_client(handler, lambda c: c.get("https://svc.example/a"), follow_redirects=True)
		today = only(self.meter)["today"]
		self.assertEqual((today["calls"], today["status"], today["received"]), (2, { "302": 1, "200": 1 }, 5))

	def test_a_streamed_body_is_counted_when_it_is_closed(self):
		async def request(client):
			async with client.stream("GET", "https://svc.example/x") as response:
				self.assertEqual(only(self.meter)["today"]["received"], 0)
				await response.aread()
		self.run_client(lambda r: httpx.Response(200, content=b"x" * 50), request)
		today = only(self.meter)["today"]
		self.assertEqual((today["calls"], today["received"]), (1, 50))

	def test_the_address_and_the_key_are_nowhere_in_what_is_kept(self):
		self.run_client(lambda r: httpx.Response(200, content=b"ok"), lambda c: c.get("https://svc.example/x?appid=SECRET"))
		self.assertNotIn("SECRET", json.dumps(self.meter.report()))
		self.assertNotIn("svc.example", json.dumps(self.meter.report()))

class TestCacheOutcomes(unittest.TestCase):
	"""`cached` and `fetch_cached` tell the meter what they did, under the data source's declared id."""
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.dscm = self.cm.datasource_manager("wikipedia-potd")
		METER.reset()
		self.addCleanup(METER.reset)
		patcher = patch.object(url_guard, "_resolve", public)
		patcher.start()
		self.addCleanup(patcher.stop)
		keeping._last_prune.clear()

	def outcomes(self) -> dict[str, int]:
		entry = next((e for e in METER.report() if e["id"] == "wikipedia-potd"), None)
		return entry["today"]["cache"] if entry else {}

	def test_a_kept_answer_is_a_hit_a_new_one_a_miss_and_an_old_one_used_for_want_of_a_new_is_stale(self):
		async def run():
			async def fetch():
				return { "n": 1 }
			async def broken():
				raise RuntimeError("down")
			settings = { "cacheHours": 1 }
			await cached(self.dscm, settings, "k", NOW, fetch)
			await cached(self.dscm, settings, "k", NOW + timedelta(minutes=10), fetch)
			await cached(self.dscm, settings, "k", NOW + timedelta(hours=2), broken)
		asyncio.run(run())
		self.assertEqual(self.outcomes(), { "miss": 1, "hit": 1, "stale": 1 })
		today = next(e for e in METER.report() if e["id"] == "wikipedia-potd")["today"]
		self.assertEqual(today["cacheBytes"]["hit"], len(json.dumps({ "n": 1 })))

	def test_an_answer_another_task_fetched_while_we_waited_is_coalesced(self):
		async def run():
			async def slow():
				await asyncio.sleep(0.3)
				return { "n": 1 }
			async def never():
				raise AssertionError("asked the origin twice")
			settings = { "cacheHours": 1 }
			first = asyncio.create_task(cached(self.dscm, settings, "k", NOW, slow))
			await asyncio.sleep(0.05)
			await cached(self.dscm, settings, "k", NOW, never)
			await first
		asyncio.run(run())
		self.assertEqual(self.outcomes(), { "miss": 1, "coalesced": 1 })

	def test_a_cache_that_is_off_is_a_bypass(self):
		async def fetch():
			return { "n": 1 }
		asyncio.run(cached(self.dscm, { "cacheHours": 0 }, "k", NOW, fetch))
		self.assertEqual(self.outcomes(), { "bypass": 1 })

	def test_a_download_is_a_miss_then_a_hit_then_a_revalidation(self):
		origin = Origin(headers={ "ETag": '"v1"', "Cache-Control": "max-age=3600" })
		async def get(now):
			async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
				await fetch_cached(self.dscm, { "contentCacheHours": 24 }, client, "https://pics.example/a.jpg", now)
		for later in (timedelta(0), timedelta(minutes=30), timedelta(hours=2)):
			asyncio.run(get(NOW + later))
		self.assertEqual(self.outcomes(), { "miss": 1, "hit": 1, "revalidated": 1 })

class TestQuotaWithTheCaches(unittest.TestCase):
	"""A used-up quota serves what the caches kept, however old, and is the failure only when nothing is kept."""
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.dscm = self.cm.datasource_manager("wikipedia-potd")
		METER.reset()
		self.addCleanup(METER.reset)
		patcher = patch.object(url_guard, "_resolve", public)
		patcher.start()
		self.addCleanup(patcher.stop)
		keeping._last_prune.clear()

	def test_an_answer_kept_is_used_when_the_quota_is_used_up_and_with_none_kept_it_is_the_failure(self):
		async def run():
			async def fetch():
				return { "n": 1 }
			async def used_up():
				raise QuotaUsedUp("quota")
			settings = { "cacheHours": 1 }
			await cached(self.dscm, settings, "k", NOW, fetch)
			# long after it expired: the quota stops the call, and the kept answer serves
			self.assertEqual(await cached(self.dscm, settings, "k", NOW + timedelta(days=3), used_up), { "n": 1 })
			with self.assertRaises(QuotaUsedUp):
				await cached(self.dscm, settings, "other", NOW, used_up)
		asyncio.run(run())

	def test_a_download_kept_is_used_when_the_quota_is_used_up_and_with_none_kept_it_is_the_failure(self):
		origin = Origin(headers={ "ETag": '"v1"', "Cache-Control": "max-age=3600" })
		def used_up(request):
			raise QuotaUsedUp("quota")
		async def get(handler, url, now):
			async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
				return (await fetch_cached(self.dscm, { "contentCacheHours": 24 }, client, url, now)).getvalue()
		async def run():
			first = await get(origin, "https://pics.example/a.jpg", NOW)
			self.assertEqual(await get(used_up, "https://pics.example/a.jpg", NOW + timedelta(days=3)), first)
			with self.assertRaises(QuotaUsedUp):
				await get(used_up, "https://pics.example/never-kept.jpg", NOW)
		asyncio.run(run())

class TestThePoolsDownloads(unittest.TestCase):
	"""
	The download pool's client belongs to no data source; `download_for` names the one it downloads for, so a picture of the day counts as that source's call
	(the System page said 0 calls beside "'nasa-apod' downloaded and kept 2363 KB").
	"""
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		METER.reset()
		self.addCleanup(METER.reset)
		patcher = patch.object(url_guard, "_resolve", public)
		patcher.start()
		self.addCleanup(patcher.stop)
		keeping._last_prune.clear()

	def context(self, source: str):
		from ..datasources.data_source import DataSourceExecutionContext
		from ..model.configuration_manager import DatasourceConfigurationManager
		from ..model.service_container import ServiceContainer
		services = ServiceContainer()
		services.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(source))
		return DataSourceExecutionContext(services, (800, 480), NOW)

	def test_a_download_through_the_pool_is_a_call_of_the_data_source_it_is_for(self):
		from ..datasources.content_cache import download_for
		from ..task.async_http_worker_pool import client_var
		async def run():
			client_var.set(MeteredClient(None, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2048))))
			for _ in range(2):
				await download_for(self.context("nasa-apod"), "https://pics.example/today.jpg", default_hours=24)
		asyncio.run(run())
		today = only(METER, "nasa-apod")["today"]
		# the second look is read from disk: one call, and a hit
		self.assertEqual((today["calls"], today["status"], today["received"]), (1, { "200": 1 }, 2048))
		self.assertEqual(today["cache"], { "miss": 1, "hit": 1 })

	def test_a_shared_client_counts_nothing_unless_a_data_source_is_named(self):
		async def run():
			async with MeteredClient(None, transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
				await client.get("https://a.example/")
		asyncio.run(run())
		self.assertEqual(METER.report(), [])

	def test_a_clients_own_source_wins_over_the_one_named_for_the_pool(self):
		from ..datasources.metering import metered_as
		async def run():
			async with MeteredClient("thunderforest-api", transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
				with metered_as("thunderforest-map"):
					await client.get("https://a.example/")
		asyncio.run(run())
		self.assertEqual([e["id"] for e in METER.report()], ["thunderforest-api"])

	def test_the_pools_client_is_a_metered_one(self):
		from ..task.async_http_worker_pool import AsyncHttpWorkerPool
		pool = AsyncHttpWorkerPool()
		pool.start(timeout=5)
		self.addCleanup(pool.shutdown)
		self.assertIsInstance(pool.client, MeteredClient)

class TestEveryApiSourceIsMetered(WebApiTestBase):
	def test_an_api_data_source_makes_its_client_with_metered_client(self):
		"""A client made any other way, or the pool's, is a service whose calls nobody counts (OpenWeatherMap's forecasts and Thunderforest's maps once went through the pool)."""
		ids = [item["info"]["id"] for item in self.cm.enum_datasources() if "api" in (item["info"].get("features") or []) and "internet" in (item["info"].get("features") or [])]
		self.assertGreaterEqual(len(ids), 5, "the API data sources the metering was written for")
		found = []
		for item in self.cm.enum_datasources():
			if item["info"]["id"] not in ids:
				continue
			for name in os.listdir(item["path"]):
				if name.endswith(".py"):
					with open(os.path.join(item["path"], name), encoding="utf-8") as f:
						for line in f:
							# its own client, made any other way; the pool's (`client_var`, which `download_for` takes when it is given none): calls nobody counts
							if "httpx.AsyncClient(" in line or "client_var" in line or ("download_for(" in line and "client=" not in line and "def download_for" not in line):
								found.append((item["info"]["id"], name, line.strip()[:80]))
		self.assertEqual(found, [], "make the client with metered_client(<the descriptor's id>, ...), and pass it to download_for(..., client=)")

	def test_the_system_page_names_each_source_from_its_descriptor(self):
		METER.reset()
		self.addCleanup(METER.reset)
		METER.call("openweathermap-api", 200, None, 0, 10)
		METER.call("gone", 500, None, 0, 0)
		usage = {entry["id"]: entry for entry in self.client.get("/api/system").json()["usage"]}
		self.assertEqual(usage["openweathermap-api"]["name"], next(i["info"]["name"] for i in self.cm.enum_datasources() if i["info"]["id"] == "openweathermap-api"))
		self.assertEqual(usage["gone"]["name"], "gone")
		self.assertEqual(usage["openweathermap-api"]["today"]["calls"], 1)

if __name__ == "__main__":
	unittest.main()
