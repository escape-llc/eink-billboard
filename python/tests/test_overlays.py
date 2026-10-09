import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from unittest import mock

from PIL import Image

from ..datasources.data_source import DataSourceManager, MediaRenderResult
from ..model.configuration_manager import ConfigurationManager
from ..model.schedule import TimerTaskItem, TimerTaskTask, TriggerDict
from ..model.service_container import ServiceContainer
from ..plugins.overlay.overlay import OverlayAsync
from ..plugins.plugin_base import PermanentError, PluginExecutionContext
from ..task.async_worker_pool import AsyncWorkerPool
from ..task.display import Display
from ..task.display_messages import OverlayImage, OverlayRevoke, OverlayZones, PriorityImage
from ..task.message_router import MessageRouter
from ..task.overlay_zones import ZONE_NAMES, zones_for
from ..utils.image_compositor import ImageCompositor
from .test_timer_layer import FakeClock, at, make_item, make_tasks, new_layer

NOW = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)

def solid(size, color=(255, 0, 0, 255)):
	return Image.new("RGBA", size, color)

class TestZones(unittest.TestCase):
	def _check(self, zones, width, height):
		self.assertEqual([z.name for z in zones], list(ZONE_NAMES))
		boxes = [z.viewer_box for z in zones]
		for z in zones:
			x0, y0, x1, y1 = z.viewer_box
			self.assertTrue(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height, z)
			self.assertEqual(z.size, (x1 - x0, y1 - y0))
		for i, a in enumerate(boxes):
			for b in boxes[i + 1:]:
				self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b))

	def test_landscape(self):
		zones = zones_for((800, 480), "landscape")
		self._check(zones, 800, 480)
		self.assertEqual(zones[2].size, (246, 96))
		self.assertTrue(all(z.panel_box == z.viewer_box and not z.portrait for z in zones))
		self.assertEqual([d.name for d in (z.definition() for z in zones)], list(ZONE_NAMES))

	def test_portrait_zones_are_laid_out_as_the_viewer_sees_the_screen(self):
		zones = zones_for((800, 480), "portrait")
		self._check(zones, 480, 800)
		for z in zones:
			x0, y0, x1, y1 = z.panel_box
			self.assertTrue(0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 480, z)

	def test_portrait_panel_box_is_where_the_turned_page_puts_the_zone(self):
		from ..utils.image_utils import change_orientation
		for z in zones_for((800, 480), "portrait"):
			with self.subTest(zone=z.name):
				page = Image.new("L", (480, 800), 0)
				page.paste(255, z.viewer_box)
				self.assertEqual(change_orientation(page, "portrait").getbbox(), z.panel_box)

class DisplayHarness:
	"""A Display with its zones and a real compositor; the overlay tasks run on a private loop."""
	def __init__(self, orientation="landscape"):
		self.display = Display("d", MessageRouter())
		self.display.zones = { z.name: z for z in zones_for((800, 480), orientation) }
		self.compositor = ImageCompositor()
		self.commits = 0
	def run(self, *msgs):
		async def go():
			q: asyncio.Queue = asyncio.Queue()
			for msg in msgs:
				if isinstance(msg, OverlayImage):
					await self.display._task_overlay_layer(q, self.compositor, msg)
				else:
					await self.display._task_overlay_revoke(q, self.compositor, msg)
			return q.qsize()
		self.commits += asyncio.run(go())
	def overlays(self):
		return self.compositor._current_stack.overlays

class TestDisplayOverlays(unittest.TestCase):
	def test_an_overlay_goes_in_its_zone_and_commits(self):
		h = DisplayHarness()
		h.run(OverlayImage(NOW, "task-a", "top-right", "A", solid((246, 96)), 0.4))
		self.assertEqual(h.commits, 1)
		[overlay] = h.overlays()
		self.assertEqual((overlay.position, overlay.wash, overlay.image.size), ((542, 10), 0.4, (246, 96)))

	def test_a_new_overlay_replaces_the_zone_and_a_key_owns_one_zone(self):
		h = DisplayHarness()
		h.run(OverlayImage(NOW, "a", "top-right", "A", solid((246, 96))),
			OverlayImage(NOW, "b", "top-right", "B", solid((246, 96), (0, 255, 0, 255))))
		self.assertEqual([o.image.getpixel((0, 0)) for o in h.overlays()], [(0, 255, 0, 255)])
		# b moves: nothing of it stays in top-right
		h.run(OverlayImage(NOW, "b", "bottom-left", "B", solid((246, 96))))
		self.assertEqual([o.position for o in h.overlays()], [(10, 374)])
		self.assertEqual(set(h.display.overlays), { "bottom-left" })

	def test_revoke_takes_down_only_the_owners_overlay(self):
		h = DisplayHarness()
		h.run(OverlayImage(NOW, "a", "top-left", "A", solid((246, 96))), OverlayImage(NOW, "b", "bottom-right", "B", solid((246, 96))))
		h.run(OverlayRevoke(NOW, "nobody"))
		self.assertEqual((len(h.overlays()), h.commits), (2, 2))
		h.run(OverlayRevoke(NOW, "a"))
		self.assertEqual((set(h.display.overlays), h.commits), ({ "bottom-right" }, 3))

	def test_an_unknown_zone_is_dropped(self):
		h = DisplayHarness()
		with self.assertLogs("python.task.display", level="WARNING"):
			h.run(OverlayImage(NOW, "a", "middle", "A", solid((10, 10))))
		self.assertEqual((h.overlays(), h.commits), ([], 0))

	def test_an_image_of_the_wrong_size_is_fitted_to_the_zone(self):
		h = DisplayHarness()
		h.run(OverlayImage(NOW, "a", "bottom-center", "A", solid((50, 20))))
		self.assertEqual(h.overlays()[0].image.size, (246, 96))

	def test_portrait_overlays_are_turned_and_placed_on_the_panel(self):
		h = DisplayHarness("portrait")
		zone = h.display.zones["top-left"]
		h.run(OverlayImage(NOW, "a", "top-left", "A", solid(zone.size)))
		[overlay] = h.overlays()
		self.assertEqual(overlay.image.size, (zone.size[1], zone.size[0]))
		self.assertEqual(overlay.position, zone.panel_box[:2])

	def test_the_handlers_run_on_the_display_pool(self):
		d = Display("d", MessageRouter())
		d.zones = { z.name: z for z in zones_for((800, 480), "landscape") }
		pool = AsyncWorkerPool()
		pool.start()
		try:
			d.task_pool = pool
			async def queue():
				return asyncio.Queue()
			d.commitq = pool.submit(queue(), None).result(timeout=5)
			d._overlay_image(OverlayImage(NOW, "a", "top-center", "A", solid((246, 96))))
			self.assertEqual(len(d.compsitor._current_stack.overlays), 1)
			d._overlay_revoke(OverlayRevoke(NOW, "a"))
			self.assertEqual(d.compsitor._current_stack.overlays, [])
		finally:
			pool.shutdown()

def overlay_item(zone="top-right", plugin="overlay", ident="t1") -> TimerTaskItem:
	return TimerTaskItem(ident, "Today", True, TimerTaskTask(plugin, { "dataSource": "today", "zone": zone, "wash": 0.4 }), cast(TriggerDict, at(9, 0)))

class TestTimerLayerOverlays(unittest.TestCase):
	def _layer(self):
		layer = new_layer()
		layer.plugin_info = cast(Any, [{ "info": { "id": "overlay", "features": ["layer-overlay"] } }, { "info": { "id": "interstitial", "features": ["layer-priority"] } }])
		layer.overlay_zones = OverlayZones([z.definition() for z in zones_for((800, 480), "landscape")])
		sent: list = []
		layer.router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		return layer, sent

	def _fail(self, item):
		layer, sent = self._layer()
		class Boom:
			async def task_async(self, context, track, donev):
				raise RuntimeError("https://x/?key=SECRET")
		layer._evaluate_plugin = lambda t: { "plugin": Boom(), "track": t }  # type: ignore
		clock = FakeClock(NOW)
		isp = ServiceContainer()
		with mock.patch("python.task.timer_layer.render_error_image", side_effect=lambda stm, dims, title, lines, theme=None, compact=False: Image.new("RGB", dims)) as render:
			asyncio.run(layer._run_task_item(isp, clock, item, "scheduled", 0, None, None))
		return [m for route, m in sent if route == "display"], render

	def test_a_failing_overlay_task_shows_its_error_in_its_zone(self):
		displays, render = self._fail(overlay_item("top-right"))
		self.assertEqual(len(displays), 1)
		msg = displays[0]
		self.assertIsInstance(msg, OverlayImage)
		self.assertEqual((msg.key, msg.zone, msg.title, msg.img.size, msg.wash), ("t1", "top-right", "Error: Today", (246, 96), 0.0))
		self.assertEqual(render.call_args.args[1], (246, 96))
		self.assertTrue(render.call_args.args[5])
		self.assertEqual(render.call_args.args[3], ["RuntimeError"])

	def test_a_failing_overlay_task_with_an_unknown_zone_shows_the_full_page(self):
		displays, _ = self._fail(overlay_item("middle"))
		self.assertEqual([type(m) for m in displays], [PriorityImage])

	def test_a_failing_task_of_another_plugin_is_unchanged(self):
		displays, render = self._fail(overlay_item("top-right", plugin="interstitial"))
		self.assertEqual([type(m) for m in displays], [PriorityImage])
		self.assertEqual(render.call_args.args[1], (800, 480))

	def test_a_reload_revokes_the_overlays_of_tasks_that_are_gone_or_disabled(self):
		layer, sent = self._layer()
		layer.tasks = make_tasks([make_item("keep", at(9, 0)), make_item("gone", at(9, 0)), make_item("off", at(9, 0)), make_item("was-off", at(9, 0), enabled=False)])
		new = make_tasks([make_item("keep", at(9, 0)), make_item("off", at(9, 0), enabled=False), make_item("new", at(9, 0))])
		class Schedules:
			def load(self):
				return { "tasks": new }
			def validate(self, info):
				pass
		layer.cm = cast(Any, type("CM", (), { "schedule_manager": lambda self: Schedules() })())
		layer.timebase = FakeClock(NOW)
		layer.state = "playing"
		layer._layer_stop = lambda: None  # type: ignore
		layer.accept = lambda msg: None  # type: ignore
		from ..task.messages import ReloadSchedules
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual(sorted(m.key for route, m in sent if isinstance(m, OverlayRevoke)), ["gone", "off"])

class FakeDataSource:
	def __init__(self, name="today", result="image"):
		self.name = name
		self.result = result
		self.dimensions = None
	async def open_async(self, dsec, params):
		return None if self.result == "nothing-open" else {}
	async def render_async(self, dsec, params, state):
		self.dimensions = dsec.dimensions
		if self.result == "boom":
			raise RuntimeError("down")
		if self.result == "nothing":
			return None
		return MediaRenderResult(image=solid(dsec.dimensions), title="Thursday")

class TestOverlayPlugin(unittest.TestCase):
	def _run(self, ds, zone="top-right", data_source="today"):
		sent: list = []
		provider = ServiceContainer()
		provider.add_service(ConfigurationManager, cast(Any, type("CM", (), { "datasource_manager": lambda self, name: object() })()))
		provider.add_service(DataSourceManager, cast(Any, type("DSM", (), { "get_source": lambda self, name: ds if name == ds.name else None })()))
		router = MessageRouter()
		router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		provider.add_service(MessageRouter, router)
		provider.add_service(OverlayZones, OverlayZones([z.definition() for z in zones_for((800, 480), "landscape")]))
		item = TimerTaskItem("t1", "Today", True, TimerTaskTask("overlay", { "dataSource": data_source, "zone": zone, "wash": 0.25 }), cast(TriggerDict, at(9, 0)))
		import threading
		done = threading.Event()
		try:
			asyncio.run(OverlayAsync("overlay", "Overlay").task_async(PluginExecutionContext(provider, (800, 480), NOW), item, done))
		finally:
			self.assertTrue(done.is_set())
		return [m for route, m in sent if route == "display"]

	def test_an_image_becomes_an_overlay_for_the_zone_rendered_at_its_size(self):
		ds = FakeDataSource()
		[msg] = self._run(ds)
		self.assertIsInstance(msg, OverlayImage)
		self.assertEqual((msg.key, msg.zone, msg.title, msg.wash, msg.img.size), ("t1", "top-right", "Thursday", 0.25, (246, 96)))
		self.assertEqual(ds.dimensions, (246, 96))

	def test_nothing_to_show_revokes(self):
		for result in ("nothing", "nothing-open"):
			with self.subTest(result=result):
				msgs = self._run(FakeDataSource(result=result))
				self.assertEqual([(type(m), m.key) for m in msgs], [(OverlayRevoke, "t1")])

	def test_an_unknown_zone_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			self._run(FakeDataSource(), zone="middle")

	def test_a_missing_data_source_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			self._run(FakeDataSource(), data_source="weather")

	def test_a_failing_data_source_raises_for_the_layer(self):
		with self.assertLogs("python.plugins.overlay.overlay", level="ERROR"), self.assertRaises(RuntimeError):
			self._run(FakeDataSource(result="boom"))

if __name__ == "__main__":
	unittest.main()
