"""
The layers, as the readme's "Display Architecture" lays them out: the overlays show only in "lock screen" mode (a background page and nothing above
it); a playlist page in blend or override mode, a timer blend and a priority image each take them off until that holds again. A blend washes over
the background (or the theme's color when there is none); an override covers everything but a priority image.
"""
import asyncio
import datetime
import unittest
from typing import Any, cast
from unittest.mock import MagicMock

from PIL import Image

from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PluginExecutionContext
from ..plugins.slide_show.slide_show import page_layer
from ..task.display import Display
from ..task.display_messages import BlendImage, DisplayImage, PriorityImage
from ..task.message_router import MessageRouter
from ..utils.image_compositor import ImageCompositor, ImageOverlay

NOW = datetime.datetime(2026, 10, 11, 12, 0)
SIZE = (8, 6)
RED, GREEN, BLUE, WHITE, THEME = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (20, 40, 60)

def solid(color, size=SIZE, alpha: int|None = None) -> Image.Image:
	return Image.new("RGBA", size, (*color, alpha)) if alpha is not None else Image.new("RGB", size, color)

def page(color, layer="background", alpha: int|None = None) -> DisplayImage:
	return DisplayImage(NOW, f"{layer} page", solid(color, alpha=alpha), layer=layer)

def blend(color, alpha: int|None = None) -> BlendImage:
	return BlendImage(NOW, "timer blend", solid(color, alpha=alpha), datetime.timedelta(minutes=1))

def priority(color) -> PriorityImage:
	return PriorityImage(NOW, "priority", solid(color), datetime.timedelta(minutes=1))

# a red square in the top-left corner: where it shows, the overlays are drawn
OVERLAY = ImageOverlay(solid(RED, (2, 2)), (0, 0))

class TestLockScreen(unittest.TestCase):
	def compositor(self) -> ImageCompositor:
		comp = ImageCompositor()
		comp.fill = THEME
		comp.set_layer_overlays([OVERLAY])
		return comp

	def shown(self, comp: ImageCompositor) -> tuple[Any, Any, str]:
		"""(the corner, where an overlay would be; the middle; the title)."""
		package = comp.commit()
		assert package is not None
		image, title = package.render()
		return image.convert("RGB").getpixel((0, 0)), image.convert("RGB").getpixel((5, 4)), title

	def test_a_background_page_alone_is_the_lock_screen_and_shows_the_overlays(self):
		comp = self.compositor()
		comp.set_layer_background(page(WHITE))
		self.assertEqual(self.shown(comp)[:2], (RED, WHITE))

	def test_every_other_layer_takes_the_overlays_off_and_they_come_back_after(self):
		for name, put, take in (
			("playlist blend", lambda c: c.set_layer_forground(page(GREEN, "blend")), lambda c: c.set_layer_forground(None)),
			("playlist override", lambda c: c.set_layer_forground(page(GREEN, "override")), lambda c: c.set_layer_forground(None)),
			("timer blend", lambda c: c.set_layer_blend(blend(GREEN)), lambda c: c.set_layer_blend(None)),
			("priority", lambda c: c.set_layer_priority(priority(GREEN)), lambda c: c.set_layer_priority(None)),
		):
			with self.subTest(name):
				comp = self.compositor()
				comp.set_layer_background(page(WHITE))
				put(comp)
				corner, middle, _ = self.shown(comp)
				self.assertEqual((corner, middle), (GREEN, GREEN), "no overlay is drawn while the layer is up")
				take(comp)
				self.assertEqual(self.shown(comp)[:2], (RED, WHITE), "the overlays are kept, and back in lock screen mode")

	def test_overlays_never_stand_alone(self):
		comp = self.compositor()
		self.assertIsNone(comp.commit())

	def test_a_blend_washes_over_the_background(self):
		comp = self.compositor()
		comp.set_layer_background(page(WHITE))
		comp.set_layer_forground(page(BLUE, "blend", alpha=0))
		corner, middle, title = self.shown(comp)
		# fully transparent: the background shows through, and still no overlay
		self.assertEqual((corner, middle, title), (WHITE, WHITE, "blend page"))
		comp.set_layer_forground(page(BLUE, "blend", alpha=128))
		_, middle, _ = self.shown(comp)
		self.assertTrue(middle[2] > 100 and middle[0] > 100, f"half blue over white is a light blue: {middle}")

	def test_a_playlist_blend_and_a_timer_blend_stack_in_that_order(self):
		comp = self.compositor()
		comp.set_layer_background(page(WHITE))
		comp.set_layer_forground(page(BLUE, "blend", alpha=255))
		comp.set_layer_blend(blend(GREEN, alpha=255))
		self.assertEqual(self.shown(comp), (GREEN, GREEN, "timer blend"))

	def test_an_override_covers_a_timer_blend_and_only_priority_is_drawn_over_it(self):
		comp = self.compositor()
		comp.set_layer_background(page(WHITE))
		comp.set_layer_blend(blend(GREEN))
		comp.set_layer_forground(page(BLUE, "override"))
		self.assertEqual(self.shown(comp), (BLUE, BLUE, "override page"))
		comp.set_layer_priority(priority(RED))
		self.assertEqual(self.shown(comp)[:2], (RED, RED))

	def test_with_no_background_the_theme_color_is_under_the_page(self):
		for name, put in (("playlist blend", lambda c: c.set_layer_forground(page(BLUE, "blend", alpha=0))),
				("timer blend", lambda c: c.set_layer_blend(blend(BLUE, alpha=0))),
				("override", lambda c: c.set_layer_forground(page(BLUE, "override", alpha=0)))):
			with self.subTest(name):
				comp = self.compositor()
				put(comp)
				self.assertEqual(self.shown(comp)[:2], (THEME, THEME))

	def test_an_override_with_transparency_shows_the_theme_color_not_the_background(self):
		comp = self.compositor()
		comp.set_layer_background(page(WHITE))
		comp.set_layer_forground(page(BLUE, "override", alpha=0))
		self.assertEqual(self.shown(comp)[:2], (THEME, THEME))

class TestDisplayRouting(unittest.TestCase):
	"""How the display puts a playlist page on its layer (the pool's tasks, run on a private loop)."""
	def setUp(self):
		self.display = Display("d", MessageRouter())
		self.comp = ImageCompositor()

	def send(self, di: DisplayImage):
		async def go():
			q: asyncio.Queue = asyncio.Queue()
			task = self.display._task_background_layer if di.layer == "background" else self.display._task_foreground_layer
			await task(q, self.comp, di)
		asyncio.run(go())

	def stack(self):
		return self.comp._current_stack

	def test_a_blend_or_override_page_keeps_the_background_and_a_background_page_ends_it(self):
		self.send(page(WHITE))
		for layer in ("blend", "override"):
			with self.subTest(layer):
				self.send(page(GREEN, layer))
				self.assertEqual((self.stack().background.img.getpixel((0, 0)), self.stack().forground.layer), (WHITE, layer))
		self.send(page(BLUE))
		self.assertIsNone(self.stack().forground, "the next background page (a track, an error page) is never hidden")
		self.assertEqual(self.stack().background.img.getpixel((0, 0)), BLUE)

	def test_a_timer_blend_is_not_ended_by_a_playlist_page(self):
		self.comp.set_layer_blend(blend(GREEN))
		self.send(page(WHITE))
		self.assertIsNotNone(self.stack().blend)

	def test_timed_layers_show_for_their_duration_then_clear(self):
		seen: list = []
		async def go():
			taskq: asyncio.Queue = asyncio.Queue()
			commitq: asyncio.Queue = asyncio.Queue()
			import threading
			done = threading.Event()
			image = BlendImage(NOW, "timer blend", solid(GREEN, (800, 480)), datetime.timedelta(seconds=0.05))
			await taskq.put(image)
			runner = asyncio.create_task(self.display._task_timed_layer(taskq, commitq, (800, 480), None, done, lambda di: seen.append(di), "blend"))
			await asyncio.sleep(0.2)
			runner.cancel()
			try:
				await runner
			except asyncio.CancelledError:
				pass
		asyncio.run(go())
		self.assertEqual([di is None for di in seen], [False, True], "set for the duration, then cleared")

	def test_a_timed_layers_time_starts_when_the_panel_has_it_not_when_it_was_queued(self):
		"""The refresh of an e-ink panel takes tens of seconds: a short priority page was shown for its time less the refresh."""
		seen: list = []
		async def go():
			import threading
			taskq: asyncio.Queue = asyncio.Queue()
			commitq: asyncio.Queue = asyncio.Queue()
			done = threading.Event()
			image = PriorityImage(NOW, "setup", solid(GREEN, (800, 480)), datetime.timedelta(seconds=0.1))
			await taskq.put(image)
			control = self.display.priority_control
			runner = asyncio.create_task(self.display._task_timed_layer(taskq, commitq, (800, 480), None, done, lambda di: (seen.append(di), self.display.compositor.set_layer_priority(di)), "priority", control))
			# the panel is still drawing it: the time (0.1 s) has not started, however long it takes
			await asyncio.sleep(0.4)
			self.assertEqual([di is None for di in seen], [False], "still shown while the panel draws it")
			self.display._note_drawn(self.display.compositor.current_version)
			await asyncio.sleep(0.4)
			runner.cancel()
			try:
				await runner
			except asyncio.CancelledError:
				pass
		asyncio.run(go())
		self.assertEqual([di is None for di in seen], [False, True], "cleared after its time, counted from the draw")

	def test_a_revoke_ends_a_timed_layer_that_is_still_waiting_for_the_panel(self):
		seen: list = []
		async def go():
			import threading
			taskq: asyncio.Queue = asyncio.Queue()
			commitq: asyncio.Queue = asyncio.Queue()
			done = threading.Event()
			await taskq.put(PriorityImage(NOW, "setup", solid(GREEN, (800, 480)), datetime.timedelta(minutes=1)))
			control = self.display.priority_control
			runner = asyncio.create_task(self.display._task_timed_layer(taskq, commitq, (800, 480), None, done, lambda di: (seen.append(di), self.display.compositor.set_layer_priority(di)), "priority", control))
			await asyncio.sleep(0.2)
			await self.display._task_priority_revoke(taskq, "setup")
			await asyncio.sleep(0.2)
			runner.cancel()
			try:
				await runner
			except asyncio.CancelledError:
				pass
		asyncio.run(go())
		self.assertEqual([di is None for di in seen], [False, True])

class TestShowAs(unittest.TestCase):
	def context(self, features: list[str]|None) -> PluginExecutionContext:
		root = ServiceContainer()
		if features is not None:
			cm = MagicMock()
			cm.enum_datasources.return_value = [{ "info": { "id": "ds", "features": features } }]
			from ..model.configuration_manager import ConfigurationManager
			root.add_service(ConfigurationManager, cast(Any, cm))
		return PluginExecutionContext(root, (800, 480), NOW)

	def test_the_tasks_choice_wins(self):
		for choice in ("background", "blend", "override"):
			self.assertEqual(page_layer(self.context(["layer-foreground"]), "ds", choice), choice)

	def test_auto_follows_the_data_source(self):
		self.assertEqual(page_layer(self.context(["layer-foreground", "media-list"]), "ds", "auto"), "override")
		self.assertEqual(page_layer(self.context(["layer-background", "media-image"]), "ds", "auto"), "background")
		self.assertEqual(page_layer(self.context(["layer-foreground"]), "other", None), "background")
		self.assertEqual(page_layer(self.context(None), "ds", "auto"), "background")

class TestPriorityUpdateShowAs(unittest.TestCase):
	"""The timer layer's two ways to show an image: over everything (priority), or washing over what the playlist shows (blend)."""
	def run_task(self, show_as: str|None) -> list:
		from ..datasources.data_source import DataSourceManager
		from ..model.configuration_manager import ConfigurationManager
		from ..model.schedule import TimerTaskItem, TimerTaskTask, TriggerDict
		from ..plugins.priority_update.priority_update import PriorityUpdateAsync
		from .test_overlays import FakeDataSource
		from .test_timer_layer import at
		import threading
		ds = FakeDataSource("poem")
		sent: list = []
		provider = ServiceContainer()
		provider.add_service(ConfigurationManager, cast(Any, type("CM", (), { "datasource_manager": lambda self, name: object() })()))
		provider.add_service(DataSourceManager, cast(Any, type("DSM", (), { "get_source": lambda self, name: ds if name == ds.name else None })()))
		router = MessageRouter()
		router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		provider.add_service(MessageRouter, router)
		content: dict = { "dataSource": "poem", "slideMinutes": 3 }
		if show_as is not None:
			content["showAs"] = show_as
		item = TimerTaskItem("t1", "Poem", True, TimerTaskTask("priority-update", content), cast(TriggerDict, at(9, 0)))
		asyncio.run(PriorityUpdateAsync("priority-update", "Priority Update").task_async(PluginExecutionContext(provider, (800, 480), NOW), item, threading.Event()))
		return [m for route, m in sent if route == "display"]

	def test_priority_is_the_default(self):
		for show_as in (None, "priority"):
			[msg] = self.run_task(show_as)
			self.assertIs(type(msg), PriorityImage)
			self.assertEqual(msg.duration, datetime.timedelta(minutes=3))

	def test_blend_washes_over_for_the_same_time(self):
		[msg] = self.run_task("blend")
		self.assertIs(type(msg), BlendImage)
		self.assertEqual(msg.duration, datetime.timedelta(minutes=3))

class TestPriorityRevoke(unittest.TestCase):
	"""A priority image can be taken down before its time is up (the setup page, once the device is claimed)."""
	def run_layer(self, body):
		display = Display("d", MessageRouter())
		comp = ImageCompositor()
		async def go():
			priorityq: asyncio.Queue = asyncio.Queue()
			commitq: asyncio.Queue = asyncio.Queue()
			layer = asyncio.create_task(display._task_timed_layer(priorityq, commitq, SIZE, None, MagicMock(), comp.set_layer_priority, "priority", display.priority_control))
			try:
				await body(display, priorityq, comp)
			finally:
				layer.cancel()
		asyncio.run(go())

	def test_a_showing_image_is_taken_down_at_once(self):
		async def body(display, q, comp):
			await q.put(priority(RED))
			await asyncio.sleep(0.05)
			self.assertIsNotNone(comp._current_stack.priority)
			await display._task_priority_revoke(q, "priority")
			await asyncio.sleep(0.05)
			self.assertIsNone(comp._current_stack.priority)
		self.run_layer(body)

	def test_a_queued_image_is_never_shown(self):
		async def body(display, q, comp):
			await q.put(priority(RED))
			await asyncio.sleep(0.05)
			await q.put(PriorityImage(NOW, "later", solid(GREEN), datetime.timedelta(minutes=1)))
			await display._task_priority_revoke(q, "later")
			await display._task_priority_revoke(q, "priority")
			await asyncio.sleep(0.05)
			self.assertIsNone(comp._current_stack.priority)
		self.run_layer(body)

	def test_revoking_what_is_not_there_does_nothing(self):
		async def body(display, q, comp):
			await display._task_priority_revoke(q, "nothing")
			self.assertEqual(display.priority_control.revoked, set())
		self.run_layer(body)
