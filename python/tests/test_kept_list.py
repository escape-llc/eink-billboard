"""A list that outlasts a visit (#222): a slot keeps what is left of its list, and fetches it again only when it is used up or too old."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, PluginConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.slide_show.slide_show import SlideShowAsync
from ..task.message_router import MessageRouter
from ..task.timer import IProvideTimer
from .test_plugin_fixes import FakeDsm, FakeItem, FakeList, FakeRouter, FakeTimer
from ..plugins.kept_list import LIST_PREFIX, MAX_LIST_BYTES, NO_ITEM, fingerprint_of, list_file_name, open_list
from ..datasources.keeping import prune_stale
from .utils import temp_configuration_manager

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
PLUGIN_ID = "slide-show"

class Origin:
	"""A data source whose list is the numbers of its fetch: [11, ..., 18] the first time, [21, ...] the second."""
	def __init__(self, size=8):
		self.fetches = 0
		self.size = size
		self.fail = False
	async def __call__(self) -> list:
		self.fetches += 1
		if self.fail:
			raise ConnectionError("down")
		return [self.fetches * 10 + i for i in range(1, self.size + 1)] if self.size else []

class KeptCase(unittest.TestCase):
	def setUp(self):
		self.cm: ConfigurationManager = temp_configuration_manager(self)
		self.pcm: PluginConfigurationManager = self.cm.plugin_manager(PLUGIN_ID)

	def visit(self, origin: Any, count: int, now: datetime = T0, slot="pl/t1", fp="a", keep=True, refresh=0, stale=30, pcm=None) -> list:
		"""One visit of a slot that shows `count` slides, the way the slide show does: the head, shown, dropped."""
		async def go():
			kept = await open_list(pcm or self.pcm, slot, fingerprint_of(fp), now, origin, keep, refresh, stale)
			got = []
			while len(got) < count:
				item = kept.head()
				if item is NO_ITEM:
					break
				got.append(item)
				kept.drop()
			return got
		return asyncio.run(go())

class TestKeptList(KeptCase):
	def test_visits_go_on_where_the_last_one_stopped_and_the_list_is_fetched_again_when_used_up(self):
		origin = Origin(8)
		self.assertEqual(self.visit(origin, 4), [11, 12, 13, 14])
		self.assertEqual(self.visit(origin, 4), [15, 16, 17, 18])
		self.assertEqual(origin.fetches, 1)
		self.assertEqual(self.visit(origin, 4), [21, 22, 23, 24], "used up: open again")
		self.assertEqual(origin.fetches, 2)

	def test_restart_is_what_it_always_was(self):
		origin = Origin(8)
		self.assertEqual(self.visit(origin, 4, keep=False), [11, 12, 13, 14])
		self.assertEqual(self.visit(origin, 4, keep=False), [21, 22, 23, 24])
		self.assertEqual(self.pcm.list_files(LIST_PREFIX), [], "nothing is written")

	def test_slots_have_a_list_each_and_the_same_track_id_in_two_playlists_is_two_slots(self):
		origin = Origin(8)
		self.assertEqual(self.visit(origin, 3, slot="playlist-a/t1"), [11, 12, 13])
		self.assertEqual(self.visit(origin, 3, slot="playlist-b/t1"), [21, 22, 23])
		self.assertEqual(self.visit(origin, 3, slot="playlist-a/t1"), [14, 15, 16])
		names = self.pcm.list_files(LIST_PREFIX)
		self.assertEqual(len(names), 2)
		self.assertNotIn("playlist", "".join(names), "the file name is only a hash")

	def test_a_slot_pointed_at_another_list_starts_a_new_one(self):
		origin = Origin(8)
		self.assertEqual(self.visit(origin, 2, fp="feed-a"), [11, 12])
		self.assertEqual(self.visit(origin, 2, fp="feed-b"), [21, 22])
		self.assertEqual(self.visit(origin, 2, fp="feed-b"), [23, 24])

	def test_an_old_list_is_fetched_again_after_refresh_hours(self):
		origin = Origin(8)
		self.assertEqual(self.visit(origin, 2, refresh=6), [11, 12])
		self.assertEqual(self.visit(origin, 2, now=T0 + timedelta(hours=5), refresh=6), [13, 14])
		self.assertEqual(self.visit(origin, 2, now=T0 + timedelta(hours=7), refresh=6), [21, 22])

	def test_zero_refresh_hours_means_only_when_it_is_used_up(self):
		origin = Origin(8)
		self.visit(origin, 2)
		self.assertEqual(self.visit(origin, 2, now=T0 + timedelta(days=10)), [13, 14])
		self.assertEqual(origin.fetches, 1)

	def test_an_old_list_is_used_when_the_origin_does_not_answer(self):
		origin = Origin(8)
		self.visit(origin, 2, refresh=6)
		origin.fail = True
		self.assertEqual(self.visit(origin, 2, now=T0 + timedelta(hours=7), refresh=6), [13, 14])

	def test_the_origin_failing_with_nothing_kept_is_the_error_it_always_was(self):
		origin = Origin(8)
		origin.fail = True
		with self.assertRaises(ConnectionError):
			self.visit(origin, 2)

	def test_an_empty_answer_is_an_empty_visit_and_keeps_nothing(self):
		origin = Origin(0)
		self.assertEqual(self.visit(origin, 4), [])
		self.assertEqual(self.pcm.list_files(LIST_PREFIX), [])

	def test_a_visit_that_stops_early_loses_only_what_it_showed(self):
		origin = Origin(8)
		async def go():
			kept = await open_list(self.pcm, "pl/t1", fingerprint_of("a"), T0, origin, True, 0, 30)
			self.assertEqual(kept.head(), 11)
			# cancelled while 11 is on the panel: it was dropped when shown, so the next visit starts at 12
			kept.drop()
			self.assertEqual(kept.head(), 12)
		asyncio.run(go())
		self.assertEqual(self.visit(origin, 2), [12, 13])

class TestWhenThingsGoWrong(KeptCase):
	def path(self) -> str:
		return os.path.join(self.pcm.ROOT_PATH, list_file_name("pl/t1") + ".json")

	def test_a_damaged_file_is_a_new_list(self):
		origin = Origin(4)
		self.visit(origin, 1)
		with open(self.path(), "w") as f:
			f.write("{ not json")
		self.assertEqual(self.visit(origin, 2), [21, 22])

	def test_a_file_that_is_not_what_we_wrote_is_a_new_list(self):
		origin = Origin(4)
		self.visit(origin, 1)
		with open(self.path(), "w") as f:
			f.write('{"items": "nope"}')
		self.assertEqual(self.visit(origin, 1), [21])

	def test_a_disk_that_cannot_be_written_never_loses_a_slide(self):
		origin = Origin(4)
		with patch("python.model.configuration_manager._internal_save", side_effect=OSError("disk full")):
			self.assertEqual(self.visit(origin, 4), [11, 12, 13, 14])

	def test_a_disk_that_fails_in_the_middle_goes_on_from_memory(self):
		origin = Origin(4)
		async def go():
			kept = await open_list(self.pcm, "pl/t1", fingerprint_of("a"), T0, origin, True, 0, 30)
			got = [kept.head()]
			kept.drop()
			with patch("python.model.configuration_manager._internal_save", side_effect=OSError("disk full")):
				while kept.head() is not NO_ITEM:
					got.append(kept.head())
					kept.drop()
			return got
		self.assertEqual(asyncio.run(go()), [11, 12, 13, 14])

	def test_a_clock_set_back_does_not_keep_an_old_list_for_ever(self):
		origin = Origin(8)
		self.visit(origin, 2, now=T0, refresh=6)
		self.assertEqual(self.visit(origin, 2, now=T0 - timedelta(days=2), refresh=6), [21, 22])

	def test_a_list_that_is_not_json_is_used_for_the_visit_only(self):
		async def odd() -> list:
			return [object(), object()]
		async def go():
			kept = await open_list(self.pcm, "pl/t1", fingerprint_of("a"), T0, odd, True, 0, 30)
			return kept.head() is not NO_ITEM
		self.assertTrue(asyncio.run(go()))
		self.assertEqual(self.pcm.list_files(LIST_PREFIX), [])

	def test_a_list_too_big_to_rewrite_at_every_slide_is_used_for_the_visit_only(self):
		async def big() -> list:
			return ["x" * (MAX_LIST_BYTES + 1), "y"]
		async def go():
			kept = await open_list(self.pcm, "pl/t1", fingerprint_of("a"), T0, big, True, 0, 30)
			kept.drop()
			return kept.head()
		self.assertEqual(asyncio.run(go()), "y")
		self.assertEqual(self.pcm.list_files(LIST_PREFIX), [])

	def test_a_file_edited_by_hand_between_slides_does_not_end_the_visit(self):
		origin = Origin(4)
		async def go():
			kept = await open_list(self.pcm, "pl/t1", fingerprint_of("a"), T0, origin, True, 0, 30)
			with open(self.path(), "w") as f:
				f.write('{"items": [], "fingerprint": "x"}')
			got = []
			while kept.head() is not NO_ITEM:
				got.append(kept.head())
				kept.drop()
			return got
		self.assertEqual(asyncio.run(go()), [11, 12, 13, 14])

class TestCleanUp(KeptCase):
	def test_unused_lists_are_removed_after_stale_days_and_the_settings_stay(self):
		origin = Origin(8)
		self.visit(origin, 1, slot="old")
		self.visit(origin, 1, slot="new", now=T0 + timedelta(days=29))
		self.assertEqual(prune_stale(self.pcm, (LIST_PREFIX,), 30, T0 + timedelta(days=31)), [list_file_name("old")])
		self.assertEqual(self.pcm.list_files(LIST_PREFIX), [list_file_name("new")])

	def test_zero_stale_days_removes_nothing(self):
		self.visit(Origin(8), 1)
		self.assertEqual(prune_stale(self.pcm, (LIST_PREFIX,), 0, T0 + timedelta(days=900)), [])

	def test_the_clean_up_never_removes_the_settings_or_the_state(self):
		with self.assertRaises(ValueError):
			self.pcm.delete_file("settings")
		with self.assertRaises(ValueError):
			self.pcm.delete_file("state")

class TestSlideShowKeepsItsList(unittest.IsolatedAsyncioTestCase):
	"""The slide show over real storage: `rss` says in its descriptor that its list is a real one."""
	def setUp(self):
		self.cm = temp_configuration_manager(self)

	def context(self, ds, slot: str|None, resumed: bool = False):
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(DataSourceManager, cast(Any, FakeDsm(ds)))
		root.add_service(MessageRouter, cast(Any, self.router))
		root.add_service(IProvideTimer, cast(Any, FakeTimer()))
		def dsec(source):
			local = ServiceContainer(root)
			local.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(source.id))
			return SimpleNamespace(provider=local, timestamp=T0)
		return SimpleNamespace(provider=root, timestamp=T0, slot=slot, resumed=resumed, create_datasource_context=dsec)

	def track(self, source: str = "rss", **settings):
		return SimpleNamespace(id="t1", title="Show", content=SimpleNamespace(data={ "dataSource": source, "slideMinutes": 5, "slideMax": 2, **settings }))

	async def show(self, ds, slot: str|None = "pl-a/t1", resumed: bool = False, **settings) -> list[str]:
		self.router = FakeRouter()
		await SlideShowAsync("slide-show", "Slide Show")._run_slideshow(cast(Any, self.context(ds, slot, resumed)), cast(Any, self.track(ds.id, **settings)))
		return [m.title for _, m in self.router.sent]

	async def test_each_visit_shows_the_next_items_of_a_feed(self):
		ds = FakeList(["a", "b", "c", "d", "e"], "rss")
		self.assertEqual(await self.show(ds), ["title a", "title b"])
		self.assertEqual(await self.show(ds), ["title c", "title d"])

	async def test_the_same_track_in_another_playlist_has_a_list_of_its_own(self):
		ds = FakeList(["a", "b", "c", "d"], "rss")
		self.assertEqual(await self.show(ds, "pl-a/t1"), ["title a", "title b"])
		self.assertEqual(await self.show(ds, "pl-b/t1"), ["title a", "title b"])
		self.assertEqual(await self.show(ds, "pl-a/t1"), ["title c", "title d"])

	async def test_restart_shows_the_top_every_time(self):
		ds = FakeList(["a", "b", "c", "d"], "rss")
		await self.show(ds, listMode="restart")
		self.assertEqual(await self.show(ds, listMode="restart"), ["title a", "title b"])

	async def test_a_source_that_is_a_view_of_now_is_never_kept(self):
		ds = FakeList(["a", "b", "c", "d"], "calendar")
		await self.show(ds)
		self.assertEqual(await self.show(ds), ["title a", "title b"])

	async def test_a_resumed_visit_carries_on_with_the_kept_list(self):
		ds = FakeList(["a", "b", "c", "d", "e"], "rss")
		self.assertEqual(await self.show(ds), ["title a", "title b"])
		self.assertEqual(await self.show(ds, resumed=True), ["title c", "title d"])

	async def test_a_resumed_visit_with_nothing_kept_yet_is_a_visit_like_any_other(self):
		ds = FakeList(["a", "b", "c"], "rss")
		self.assertEqual(await self.show(ds, resumed=True), ["title a", "title b"])

	async def test_a_resumed_visit_passes_on_when_the_list_was_used_up(self):
		ds = FakeList(["a", "b"], "rss")
		self.assertEqual(await self.show(ds), ["title a", "title b"])
		ds.items = ["x", "y"]
		# no new list, no pictures, and no "no media items" error
		self.assertEqual(await self.show(ds, resumed=True), [])
		# the next visit that is not a resume opens the new list, as it always did
		self.assertEqual(await self.show(ds), ["title x", "title y"])

	async def test_a_resumed_visit_passes_on_for_a_list_that_is_not_kept(self):
		ds = FakeList(["a", "b", "c", "d"], "calendar")
		self.assertEqual(await self.show(ds, resumed=True), [])
		self.assertEqual(ds.rendered, [])

	async def test_a_resumed_visit_passes_on_when_the_task_restarts_its_list_every_visit(self):
		ds = FakeList(["a", "b", "c", "d"], "rss")
		self.assertEqual(await self.show(ds, resumed=True, listMode="restart"), [])

	async def test_a_resumed_visit_passes_on_for_a_single_picture(self):
		ds = FakeItem(state="x")
		ds.id = ds.name = "apod"
		self.assertEqual(await self.show(ds, resumed=True), [])
		# and a visit that is not a resume shows it
		self.assertEqual(len(await self.show(ds)), 1)

if __name__ == "__main__":
	unittest.main()
