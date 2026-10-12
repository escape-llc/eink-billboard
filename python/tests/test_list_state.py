"""A list that outlasts a visit (#222): the slots of one data source pull from one list, which is fetched again only when it is used up or too old."""
import asyncio
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from unittest.mock import patch

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.list_state import MAX_STATE_BYTES, NO_ITEM, STATE_PREFIX, open_cursor, prune_stale, state_file_name
from ..plugins.plugin_base import PermanentError
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager
from ..model.service_container import ServiceContainer
from .utils import save_datasource_settings, temp_configuration_manager

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = "rss"

class Source:
	"""A data source whose list is the numbers of its fetch: [1, 2, 3, 4, 5, 6, 7, 8] the first time, [11, ...] the second."""
	def __init__(self, size=8, key: str|None = "feed-a"):
		self.fetches = 0
		self.size = size
		self.key = key
	def list_state_key(self, dsec, params) -> str|None:
		return self.key
	async def open_async(self, dsec, params) -> list:
		self.fetches += 1
		return [self.fetches * 10 + i for i in range(1, self.size + 1)] if self.size else []

class Stateless:
	"""No `list_state_key`: a list made fresh every time (the calendar's pages)."""
	def __init__(self):
		self.fetches = 0
	async def open_async(self, dsec, params) -> list:
		self.fetches += 1
		return [1, 2, 3]

class ListStateCase(unittest.TestCase):
	"""A private storage, and a way to run one visit of a slot."""
	def setUp(self):
		self.cm: ConfigurationManager = temp_configuration_manager(self)
		self.dscm: DatasourceConfigurationManager = self.cm.datasource_manager(SOURCE_ID)

	def settings(self, **values: Any) -> None:
		save_datasource_settings(self.cm, SOURCE_ID, { "feeds": [], **values })

	def dsec(self, now: datetime = T0) -> DataSourceExecutionContext:
		root = ServiceContainer()
		root.add_service(DatasourceConfigurationManager, self.dscm)
		return DataSourceExecutionContext(root, (800, 480), now)

	def visit(self, source: Any, count: int, now: datetime = T0, params: Mapping[str, Any]|None = None) -> list:
		"""One visit of a slot that shows `count` slides."""
		async def go():
			cursor = await open_cursor(self.dsec(now), source, params or {})
			got = []
			while len(got) < count:
				item = await cursor.next()
				if item is NO_ITEM:
					break
				got.append(item)
			return got
		return asyncio.run(go())


class TestListState(ListStateCase):
	def test_two_slots_of_four_take_one_list_and_then_it_is_fetched_again(self):
		self.settings(listMode="continue")
		source = Source(8)
		self.assertEqual(self.visit(source, 4), [11, 12, 13, 14])
		self.assertEqual(self.visit(source, 4), [15, 16, 17, 18])
		self.assertEqual(source.fetches, 1, "one fetch for both slots")
		self.assertEqual(self.visit(source, 4), [21, 22, 23, 24], "used up: back to the origin")
		self.assertEqual(source.fetches, 2)

	def test_restart_is_what_it_always_was(self):
		self.settings(listMode="restart")
		source = Source(8)
		self.assertEqual(self.visit(source, 4), [11, 12, 13, 14])
		self.assertEqual(self.visit(source, 4), [21, 22, 23, 24])
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [], "nothing is kept")

	def test_a_list_made_fresh_every_time_is_never_kept(self):
		self.settings(listMode="continue")
		source = Stateless()
		self.assertEqual(self.visit(source, 2), [1, 2])
		self.assertEqual(self.visit(source, 2), [1, 2])
		self.assertEqual(source.fetches, 2)

	def test_the_default_is_to_continue(self):
		self.settings()
		source = Source(8)
		self.visit(source, 4)
		self.assertEqual(self.visit(source, 4), [15, 16, 17, 18])

	def test_the_rest_of_a_visit_that_stopped_early_is_kept(self):
		"""A restart, a cancel: every slide was saved as it was taken."""
		self.settings()
		source = Source(8)
		self.assertEqual(self.visit(source, 3), [11, 12, 13])
		self.assertEqual(self.visit(source, 8), [14, 15, 16, 17, 18], "the rest, and no fetch inside a visit")
		self.assertEqual(source.fetches, 1)

	def test_an_old_list_is_fetched_again_after_refresh_hours(self):
		self.settings(refreshHours=6)
		source = Source(8)
		self.visit(source, 2)
		self.assertEqual(self.visit(source, 2, T0 + timedelta(hours=5)), [13, 14])
		self.assertEqual(self.visit(source, 2, T0 + timedelta(hours=7)), [21, 22], "older than 6 hours")

	def test_zero_refresh_hours_means_only_when_it_is_used_up(self):
		self.settings(refreshHours=0)
		source = Source(8)
		self.visit(source, 2)
		self.assertEqual(self.visit(source, 2, T0 + timedelta(days=30)), [13, 14])

	def test_an_old_list_is_used_when_the_origin_does_not_answer(self):
		self.settings(refreshHours=1)
		source = Source(8)
		self.visit(source, 2)
		async def broken(dsec, params):
			raise ConnectionError("down")
		source.open_async = broken  # type: ignore[method-assign]
		self.assertEqual(self.visit(source, 2, T0 + timedelta(hours=3)), [13, 14])

	def test_an_empty_answer_is_an_empty_visit_and_keeps_nothing(self):
		self.settings()
		source = Source(0)
		self.assertEqual(self.visit(source, 3), [])
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [])

	def test_two_lists_do_not_mix_and_the_file_name_is_only_a_hash(self):
		self.settings()
		a, b = Source(8, "https://example.com/feed?key=secret"), Source(8, "folder|Photos|/home/me/photos")
		self.visit(a, 2)
		self.visit(b, 3)
		names = self.dscm.list_files(STATE_PREFIX)
		self.assertEqual(sorted(names), sorted([state_file_name(a.key or ""), state_file_name(b.key or "")]))
		for name in names:
			self.assertRegex(name, r"^state-[0-9a-f]{16}$")
		self.assertEqual(self.visit(a, 2), [13, 14])
		self.assertEqual(self.visit(b, 2), [14, 15])

	def test_slots_that_run_together_never_get_the_same_item(self):
		self.settings()
		source = Source(40)
		async def go():
			cursors = [await open_cursor(self.dsec(), source, {}) for _ in range(4)]
			got: list = []
			async def pull(cursor):
				for _ in range(10):
					got.append(await cursor.next())
					await asyncio.sleep(0)
			await asyncio.gather(*(pull(c) for c in cursors))
			return got
		got = asyncio.run(go())
		self.assertEqual(sorted(got), list(range(11, 51)))

	def test_unused_lists_are_removed_after_stale_days(self):
		self.settings(staleDays=30)
		source = Source(8, "old")
		self.visit(source, 1, T0)
		self.visit(Source(8, "recent"), 1, T0 + timedelta(days=29))
		removed = prune_stale(self.dscm, (STATE_PREFIX,), 30, T0 + timedelta(days=31))
		self.assertEqual(removed, [state_file_name("old")])
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [state_file_name("recent")])

	def test_zero_stale_days_removes_nothing(self):
		self.settings(staleDays=0)
		self.visit(Source(8), 1, T0)
		self.assertEqual(prune_stale(self.dscm, (STATE_PREFIX,), 0, T0 + timedelta(days=3650)), [])

	def test_the_clean_up_never_removes_the_settings(self):
		self.settings()
		with self.assertRaises(ValueError):
			self.dscm.delete_file("settings")
		self.assertTrue(os.path.isfile(self.dscm.settings_path()))
		with self.assertRaises(ValueError):
			self.dscm.list_files("../")

	def test_a_file_that_cannot_say_when_it_was_used_is_removed(self):
		self.settings()
		cob = self.dscm.file("state-0000000000000000")
		cob.save(None, { "items": [1] })
		self.assertEqual(prune_stale(self.dscm, (STATE_PREFIX,), 30, T0), ["state-0000000000000000"])

class TestWhenThingsGoWrong(ListStateCase):
	"""Every way the kept list can be damaged, unwritable, raced or too big: a slide is never lost to it, and a bad file is only a list that is used up."""
	def state_path(self, source) -> str:
		return os.path.join(self.dscm.ROOT_PATH, state_file_name(source.key) + ".json")

	def test_a_damaged_file_is_a_new_list(self):
		for damage in ("{not json", "[1, 2, 3]", "{\"items\": \"not a list\"}", "", "null"):
			with self.subTest(damage):
				self.settings()
				source = Source(8, f"damaged-{damage}")
				self.visit(source, 2)
				with open(self.state_path(source), "w") as f:
					f.write(damage)
				self.dscm.file(state_file_name(source.key)).evict()
				fetched = source.fetches
				got = self.visit(source, 2)
				self.assertEqual(len(got), 2)
				self.assertEqual(source.fetches, fetched + 1, "a new list was fetched")

	def test_a_disk_that_cannot_be_written_never_loses_a_slide(self):
		self.settings()
		source = Source(8)
		with patch("python.model.configuration_manager._internal_save", side_effect=OSError("disk full")):
			self.assertEqual(self.visit(source, 8), [11, 12, 13, 14, 15, 16, 17, 18], "the whole list, from memory")
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [])

	def test_a_disk_that_fails_in_the_middle_goes_on_from_memory(self):
		self.settings()
		source = Source(8)
		async def go():
			cursor = await open_cursor(self.dsec(), source, {})
			got = [await cursor.next(), await cursor.next()]
			with patch("python.model.configuration_manager._internal_save", side_effect=OSError("disk full")):
				got += [await cursor.next(), await cursor.next(), await cursor.next()]
			return got
		self.assertEqual(asyncio.run(go()), [11, 12, 13, 14, 15])

	def test_a_clock_set_back_does_not_keep_an_old_list_for_ever(self):
		self.settings(refreshHours=6)
		source = Source(8)
		self.visit(source, 2, T0 + timedelta(days=400))
		self.assertEqual(self.visit(source, 2, T0), [21, 22], "fetched 'in the future': fetched again")

	def test_a_list_that_is_not_json_is_used_for_the_visit_only(self):
		self.settings()
		class Odd(Source):
			async def open_async(self, dsec, params) -> list:
				self.fetches += 1
				return [object(), object()]
		got = self.visit(Odd(8), 5)
		self.assertEqual(len(got), 2)
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [])

	def test_a_list_too_big_to_rewrite_at_every_slide_is_used_for_the_visit_only(self):
		self.settings()
		class Big(Source):
			async def open_async(self, dsec, params) -> list:
				self.fetches += 1
				return ["x" * 1000 for _ in range(MAX_STATE_BYTES // 1000 + 10)]
		self.assertEqual(len(self.visit(Big(8), 3)), 3)
		self.assertEqual(self.dscm.list_files(STATE_PREFIX), [])

	def test_the_file_going_away_between_slides_ends_the_visit_quietly(self):
		"""The clean-up (or a person) removed it while the visit was on."""
		self.settings()
		source = Source(8)
		async def go():
			cursor = await open_cursor(self.dsec(), source, {})
			first = await cursor.next()
			self.dscm.delete_file(state_file_name(source.key))
			return [first, await cursor.next()]
		self.assertEqual(asyncio.run(go()), [11, NO_ITEM])
		self.assertEqual(self.visit(source, 2), [21, 22], "and the next visit makes a new list")

	def test_a_cancelled_visit_keeps_what_it_did_not_take(self):
		self.settings()
		source = Source(8)
		async def go():
			cursor = await open_cursor(self.dsec(), source, {})
			task = asyncio.create_task(self.slowly(cursor))
			await asyncio.sleep(0.05)
			task.cancel()
			with self.assertRaises(asyncio.CancelledError):
				await task
		asyncio.run(go())
		self.assertEqual(self.visit(source, 8), [12, 13, 14, 15, 16, 17, 18], "the first was shown, the rest are kept")

	@staticmethod
	async def slowly(cursor):
		await cursor.next()
		await asyncio.sleep(10)
		await cursor.next()

	def test_the_origin_failing_with_nothing_kept_is_the_error_it_always_was(self):
		self.settings()
		class Down(Source):
			async def open_async(self, dsec, params) -> list:
				raise ConnectionError("down")
		with self.assertRaises(ConnectionError):
			self.visit(Down(8), 2)

	def test_a_key_that_cannot_be_made_is_the_error_the_list_would_have_raised(self):
		"""The feed was renamed or removed: nothing to retry."""
		self.settings()
		class Gone(Source):
			def list_state_key(self, dsec, params):
				raise PermanentError("The feed is not in the settings.")
		with self.assertRaises(PermanentError):
			self.visit(Gone(8), 2)

	def test_another_slot_that_makes_the_new_list_first_wins_and_nothing_is_fetched_twice_for_it(self):
		"""Two visits both find the list used up; the second to save is refused and takes the first one's list."""
		self.settings()
		source = Source(8)
		original = source.open_async
		async def racing(dsec, params):
			result = await original(dsec, params)
			# while our fetch was away, the other slot made and saved its list
			cob = self.dscm.file(state_file_name(source.key or ""))
			rev, _ = cob.get()
			cob.save(rev, { "items": [61, 62, 63], "fetched_at": T0.isoformat(), "last_used": T0.isoformat() })
			return result
		source.open_async = racing  # type: ignore[method-assign]
		self.assertEqual(self.visit(source, 2), [61, 62], "the other slot's list, not ours")

	def test_slots_that_find_the_list_used_up_together_fetch_it_once(self):
		self.settings()
		class Slow(Source):
			async def open_async(self, dsec, params) -> list:
				await asyncio.sleep(0.3)
				return await super().open_async(dsec, params)
		source = Slow(8)
		got: list = []
		lock = threading.Lock()
		def worker():
			async def go():
				cursor = await open_cursor(self.dsec(), source, {})
				item = await cursor.next()
				with lock:
					got.append(item)
			asyncio.run(go())
		threads = [threading.Thread(target=worker) for _ in range(5)]
		for t in threads: t.start()
		for t in threads: t.join()
		self.assertEqual(source.fetches, 1, "one fetch for all five")
		self.assertEqual(sorted(got), [11, 12, 13, 14, 15])

	def test_a_fetch_that_failed_for_one_is_tried_by_the_next(self):
		self.settings()
		class Flaky(Source):
			async def open_async(self, dsec, params) -> list:
				await asyncio.sleep(0.1)
				if self.fetches == 0:
					self.fetches += 1
					raise ConnectionError("down")
				return await super().open_async(dsec, params)
		source = Flaky(8)
		results: list = []
		def worker():
			try:
				results.append(self.visit(source, 1))
			except ConnectionError:
				results.append("down")
		threads = [threading.Thread(target=worker) for _ in range(2)]
		for t in threads: t.start()
		for t in threads: t.join()
		self.assertEqual(sorted(results, key=str), [[21], "down"])

	def test_slots_on_different_threads_never_get_the_same_item_and_lose_none(self):
		self.settings()
		source = Source(60)
		got: list = []
		lock = threading.Lock()
		def worker():
			async def go():
				cursor = await open_cursor(self.dsec(), source, {})
				for _ in range(15):
					item = await cursor.next()
					with lock:
						got.append(item)
			asyncio.run(go())
		threads = [threading.Thread(target=worker) for _ in range(4)]
		for t in threads: t.start()
		for t in threads: t.join()
		self.assertNotIn(NO_ITEM, got, "nobody was turned away")
		taken = [g for g in got if g is not NO_ITEM]
		self.assertEqual(len(taken), len(set(taken)), "no item twice")
		self.assertEqual(sorted(taken), list(range(11, 71)), "and none skipped")
