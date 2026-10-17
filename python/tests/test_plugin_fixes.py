"""Offline tests for the slide show and priority update plugins, with fake datasources, router and timer."""
import threading
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from PIL import Image

from ..datasources.data_source import DataSourceManager, MediaItemAsync, MediaListAsync, MediaRenderAsync, MediaRenderResult
from ..model.service_container import ServiceContainer
from ..plugins.priority_update.priority_update import PriorityUpdateAsync
from ..plugins.slide_show.slide_show import SlideShowAsync
from ..task.display import DisplayImage, PriorityImage
from ..task.message_router import MessageRouter
from ..task.timer import IProvideTimer
from .test_web_api import WebApiTestBase

class FakeRouter:
	def __init__(self):
		self.sent = []
	def send(self, route, msg):
		self.sent.append((route, msg))

class FakeTimer:
	def __init__(self):
		self.slept = []
	async def sleep(self, delta: timedelta):
		self.slept.append(delta)

class FakeList:
	"""A MediaList datasource whose items named 'bad*' fail to render."""
	def __init__(self, items, name="fake"):
		self.items = list(items)
		self.name = name
		self.id = name
		self.rendered = []
	async def open_async(self, dsec, params):
		return list(self.items)
	async def render_async(self, dsec, params, state):
		self.rendered.append(state)
		if str(state).startswith("bad"):
			raise RuntimeError(f"dead url for {state}")
		return MediaRenderResult(image=Image.new("RGB", (4, 4)), title=f"title {state}")

class FakeItem:
	def __init__(self, fail=False, state="x"):
		self.fail = fail
		self.state = state
		self.name = self.id = "item"
	async def open_async(self, dsec, params):
		return self.state
	async def render_async(self, dsec, params, state):
		if self.fail:
			raise RuntimeError("dead url")
		return MediaRenderResult(image=Image.new("RGB", (4, 4)), title=None)

class FakeDsm:
	def __init__(self, ds):
		self.ds = ds
	def get_source(self, name):
		return self.ds

def make_context(ds, router, timer):
	root = ServiceContainer()
	root.add_service(DataSourceManager, cast(Any, FakeDsm(ds)))
	root.add_service(MessageRouter, cast(Any, router))
	root.add_service(IProvideTimer, cast(Any, timer))
	return SimpleNamespace(provider=root, timestamp=datetime(2026, 10, 7, 12, 0), slot=None, resumed=False, create_datasource_context=lambda d: SimpleNamespace(timestamp=datetime(2026, 10, 7, 12, 0)))

class TestSlideShow(unittest.IsolatedAsyncioTestCase):
	def _track(self, **settings):
		return SimpleNamespace(title="My Show", content=SimpleNamespace(data={"dataSource": "fake", "slideMinutes": 5, "slideMax": 0, **settings}))
	async def test_one_dead_item_does_not_abort_the_show(self):
		ds = FakeList(["a", "bad1", "b"])
		router, timer = FakeRouter(), FakeTimer()
		show = SlideShowAsync("slide-show", "slide-show")
		with self.assertLogs(show.logger, level="ERROR") as logs:
			await show._run_slideshow(cast(Any, make_context(ds, router, timer)), cast(Any, self._track()))
		self.assertEqual(ds.rendered, ["a", "bad1", "b"])
		self.assertEqual([m.title for _, m in router.sent], ["title a", "title b"])
		self.assertTrue(all(isinstance(m, DisplayImage) for _, m in router.sent))
		self.assertEqual(len(timer.slept), 2, "a failed item must not wait a slide interval")
		self.assertIn("My Show", "\n".join(logs.output))
	async def test_all_items_failing_fails_the_show(self):
		ds = FakeList(["bad1", "bad2"])
		router, timer = FakeRouter(), FakeTimer()
		show = SlideShowAsync("slide-show", "slide-show")
		with self.assertLogs(show.logger, level="ERROR"), self.assertRaisesRegex(RuntimeError, "All 2"):
			await show._run_slideshow(cast(Any, make_context(ds, router, timer)), cast(Any, self._track()))
		self.assertEqual(router.sent, [])
	async def test_slide_max_counts_shown_slides_not_failures(self):
		ds = FakeList(["bad1", "a", "b", "c"])
		router, timer = FakeRouter(), FakeTimer()
		show = SlideShowAsync("slide-show", "slide-show")
		with self.assertLogs(show.logger, level="ERROR"):
			await show._run_slideshow(cast(Any, make_context(ds, router, timer)), cast(Any, self._track(slideMax=2)))
		self.assertEqual([m.title for _, m in router.sent], ["title a", "title b"])
	async def test_a_source_of_one_picture_is_one_slide_whatever_the_count(self):
		# media-image without media-list: a count left in the task (it is hidden in the form) is ignored
		from ..model.configuration_manager import ConfigurationManager
		for features, shown in ((["media-image"], ["title a"]), (["media-image", "media-list"], ["title a", "title b", "title c"])):
			ds = FakeList(["a", "b", "c"])
			router, timer = FakeRouter(), FakeTimer()
			context = make_context(ds, router, timer)
			context.provider.add_service(ConfigurationManager, cast(Any, SimpleNamespace(enum_datasources=lambda features=features: [{ "info": { "id": "fake", "features": features } }])))
			await SlideShowAsync("slide-show", "slide-show")._run_slideshow(cast(Any, context), cast(Any, self._track(slideMax=3)))
			self.assertEqual([m.title for _, m in router.sent], shown, features)
	async def test_task_async_sets_done_even_when_all_fail(self):
		from ..model.schedule import PlaylistSchedule, PlaylistScheduleData
		ds = FakeList(["bad1"])
		track = PlaylistSchedule("slide-show", "id", "My Show", PlaylistScheduleData({"dataSource": "fake", "slideMinutes": 1, "slideMax": 0}))
		done = threading.Event()
		show = SlideShowAsync("slide-show", "slide-show")
		with self.assertLogs(show.logger, level="ERROR"), self.assertRaises(RuntimeError):
			await show.task_async(cast(Any, make_context(ds, FakeRouter(), FakeTimer())), track, done)
		self.assertTrue(done.is_set())

class TestPriorityUpdate(unittest.IsolatedAsyncioTestCase):
	def _track(self):
		return SimpleNamespace(title="My Priority Update", task=SimpleNamespace(content={"dataSource": "item", "slideMinutes": 2}))
	async def test_success_sends_priority_image(self):
		router = FakeRouter()
		await PriorityUpdateAsync("i", "i")._do_task_async(cast(Any, make_context(FakeItem(), router, FakeTimer())), cast(Any, self._track()))
		self.assertEqual(len(router.sent), 1)
		self.assertIsInstance(router.sent[0][1], PriorityImage)
		self.assertEqual(router.sent[0][1].title, "My Priority Update")
	async def test_failure_is_logged_with_the_items_title_and_raised(self):
		router = FakeRouter()
		plugin = PriorityUpdateAsync("i", "i")
		with self.assertLogs(plugin.logger, level="ERROR") as logs, self.assertRaises(RuntimeError):
			await plugin._do_task_async(cast(Any, make_context(FakeItem(fail=True), router, FakeTimer())), cast(Any, self._track()))
		self.assertIn("My Priority Update", "\n".join(logs.output))
		self.assertEqual(router.sent, [])

if __name__ == "__main__":
	unittest.main()

class TestDataSourceSettingsFolder(WebApiTestBase):
	"""A slot reads its data source's settings from the folder the settings page writes: the descriptor's id, not its display name."""
	def test_the_settings_a_slot_reads_are_the_ones_saved(self):
		from ..datasources.data_source import DataSource
		from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager
		from ..model.service_container import ServiceContainer
		from ..plugins.plugin_base import PluginExecutionContext
		self.write_datasource_settings("rss", { "feeds": [{ "name": "News", "url": "https://news.example.test/feed.xml" }] })
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		dsec = PluginExecutionContext(root, (800, 480), datetime(2026, 10, 11, 12, 0)).create_datasource_context(DataSource("rss", "RSS Feed"))
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		self.assertEqual([f["name"] for f in (settings or {}).get("feeds", [])], ["News"])
