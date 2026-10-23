"""
The rest after a panel refresh (`docs/architecture.md`'s "Blanking Period"): the gate itself, what is kept of it across a restart, the drivers that hold to it, and the Display task that waits it out
before it takes the next image. No image may be sent to the driver while the panel rests.
"""
import asyncio
import datetime
import os
import threading
import unittest
from typing import Any
from unittest.mock import MagicMock

from PIL import Image

from ..display.display_base import DisplayBase
from ..display.mock_display import MockDisplay
from ..display.refresh_gate import DEFAULT_REST_SECONDS, RefreshGate, RefreshState, TooSoon
from ..task.display import Display
from ..task.display_messages import DisplayImage
from ..task.message_router import MessageRouter
from ..utils.image_compositor import ImageCompositor
from .test_inky_display import FakeInky, display_with as inky_with
from .test_waveshare_display import FakePanel, display_with as waveshare_with
from .utils import temp_configuration_manager

NOW = datetime.datetime(2026, 10, 19, 12, 0)
RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)

class Clock:
	"""A clock the test moves (the gate takes a monotonic clock and a wall clock)."""
	def __init__(self, start: float = 1000.0):
		self.now = start
	def __call__(self) -> float:
		return self.now

class TestGate(unittest.TestCase):
	def gate(self, rest: float = 60.0, floor: float = 0.0) -> tuple[RefreshGate, Clock, Clock]:
		clock, wall = Clock(), Clock(1_800_000_000.0)
		return RefreshGate(rest, floor, clock=clock, wall=wall), clock, wall

	def test_a_new_gate_lets_the_first_refresh_through(self):
		gate, _, _ = self.gate()
		self.assertEqual(gate.ready_in(), 0)
		gate.begin()

	def test_the_rest_starts_when_the_refresh_ends_not_when_it_starts(self):
		gate, clock, _ = self.gate(60)
		gate.begin()
		clock.now += 25   # a slow refresh
		gate.finish()
		self.assertAlmostEqual(gate.ready_in(), 60)
		clock.now += 59
		with self.assertRaisesRegex(TooSoon, "resting"):
			gate.begin()
		clock.now += 1
		gate.begin()

	def test_while_a_send_is_on_its_way_nobody_else_gets_through(self):
		gate, _, _ = self.gate(60)
		gate.begin()
		self.assertGreater(gate.ready_in(), 0)
		with self.assertRaises(TooSoon):
			gate.begin()

	def test_the_refusal_says_how_long(self):
		gate, clock, _ = self.gate(60)
		gate.begin()
		gate.finish()
		clock.now += 20
		with self.assertRaisesRegex(TooSoon, "40 more seconds"):
			gate.begin()

	def test_a_models_floor_wins_over_a_shorter_setting(self):
		gate, _, _ = self.gate(rest=10, floor=30)
		self.assertEqual(gate.rest_seconds, 30)
		self.assertEqual(self.gate(rest=90, floor=30)[0].rest_seconds, 90)

	def test_no_rest_never_refuses(self):
		gate, _, _ = self.gate(0)
		for _ in range(3):
			gate.begin()
			self.assertIsNone(gate.finish())
		self.assertEqual(gate.ready_in(), 0)

	def test_a_restart_waits_out_what_was_left_of_the_rest(self):
		gate, _, wall = self.gate(60)
		gate.restore(wall.now - 20)
		self.assertAlmostEqual(gate.ready_in(), 40, delta=0.01)

	def test_a_restart_after_the_rest_is_over_is_not_held(self):
		gate, _, wall = self.gate(60)
		gate.restore(wall.now - 600)
		self.assertEqual(gate.ready_in(), 0)

	def test_a_stored_time_in_the_future_never_holds_the_panel_longer_than_one_rest(self):
		# a Pi with no clock set reads any date at boot: the stored end may be "tomorrow"
		gate, _, wall = self.gate(60)
		gate.restore(wall.now + 86_400)
		self.assertAlmostEqual(gate.ready_in(), 60, delta=0.01)

	def test_nothing_stored_is_no_rest(self):
		gate, _, _ = self.gate(60)
		gate.restore(None)
		self.assertEqual(gate.ready_in(), 0)

class TestState(unittest.TestCase):
	def test_what_was_kept_comes_back(self):
		cm = temp_configuration_manager(self)
		RefreshState(cm).save(1_800_000_000.5, "ab" * 32)
		again = RefreshState(cm)
		again.load()
		self.assertEqual((again.last_end, again.digest), (1_800_000_000.5, "ab" * 32))

	def test_the_file_is_in_the_state_folder_and_not_in_the_settings(self):
		cm = temp_configuration_manager(self)
		RefreshState(cm).save(1.0, None)
		self.assertTrue(os.path.isfile(os.path.join(cm.storage_state, "refresh.json")))
		self.assertEqual(cm.area_of(os.path.join(cm.storage_state, "refresh.json")), "state")

	def test_an_unknown_picture_is_kept_as_unknown(self):
		cm = temp_configuration_manager(self)
		state = RefreshState(cm)
		state.save(2.0, "cd" * 32)
		state.save(3.0, None)
		again = RefreshState(cm)
		again.load()
		self.assertEqual((again.last_end, again.digest), (3.0, None))

	def test_nothing_kept_is_no_state(self):
		state = RefreshState(temp_configuration_manager(self))
		state.load()
		self.assertEqual((state.last_end, state.digest), (None, None))

	def test_a_damaged_file_is_no_state_and_stops_nothing(self):
		cm = temp_configuration_manager(self)
		os.makedirs(cm.storage_state, exist_ok=True)
		with open(os.path.join(cm.storage_state, "refresh.json"), "w") as f:
			f.write("{ not json")
		state = RefreshState(cm)
		state.load()
		self.assertEqual((state.last_end, state.digest), (None, None))
		state.save(5.0, None)   # and it can be written over

	def test_values_of_the_wrong_kind_are_ignored(self):
		cm = temp_configuration_manager(self)
		cob = cm.state_file("refresh")
		cob.save(cob.get()[0], { "lastEnd": "yesterday", "digest": 7 })
		state = RefreshState(cm)
		state.load()
		self.assertEqual((state.last_end, state.digest), (None, None))

	def test_a_storage_that_fails_never_stops_the_panel(self):
		cm = MagicMock()
		cm.state_file.side_effect = OSError("disk")
		state = RefreshState(cm)
		state.load()
		state.save(1.0, "ef" * 32)
		RefreshState(None).save(1.0, None)

class TestDrivers(unittest.TestCase):
	"""Each display class holds to the rest: a second image is refused and nothing reaches the board."""
	def test_the_rest_comes_from_the_display_settings(self):
		self.assertEqual(inky_with(FakeInky()).gate.rest_seconds, DEFAULT_REST_SECONDS)
		self.assertEqual(inky_with(FakeInky(), { "refreshInterval": 90 }).gate.rest_seconds, 90)
		self.assertEqual(waveshare_with(FakePanel(), settings={ "refreshInterval": 0 }).gate.rest_seconds, 0)
		for unusable in (-5, "soon", None, True):
			with self.subTest(unusable):
				self.assertEqual(inky_with(FakeInky(), { "refreshInterval": unusable }).gate.rest_seconds, DEFAULT_REST_SECONDS)

	def test_an_inky_is_not_sent_a_second_image_during_the_rest(self):
		board = FakeInky()
		shown = inky_with(board)
		shown.render(Image.new("RGB", (800, 480), "red"), 1)
		calls = list(board.calls)
		with self.assertRaises(TooSoon):
			shown.render(Image.new("RGB", (800, 480), "blue"), 2)
		self.assertEqual(board.calls, calls, "nothing reached the board")

	def test_a_waveshare_is_not_sent_a_second_image_during_the_rest(self):
		panel = FakePanel()
		shown = waveshare_with(panel)
		shown.render(Image.new("RGB", (800, 480), "red"), 1)
		calls = list(panel.calls)
		with self.assertRaises(TooSoon):
			shown.render(Image.new("RGB", (800, 480), "blue"), 2)
		self.assertEqual(panel.calls, calls, "nothing reached the panel")

	def test_a_refresh_that_fails_still_starts_the_rest(self):
		# the panel may have been driven before it failed
		class Broken(FakeInky):
			def show(self):
				raise OSError("busy line")
		shown = inky_with(Broken())
		with self.assertRaises(OSError):
			shown.render(Image.new("RGB", (800, 480)), 1)
		with self.assertRaises(TooSoon):
			shown.render(Image.new("RGB", (800, 480)), 2)

	def test_a_refresh_that_times_out_still_starts_the_rest(self):
		release = threading.Event()
		self.addCleanup(release.set)
		class Stuck(FakeInky):
			def show(self):
				release.wait(5)
		shown = inky_with(Stuck())
		shown.refresh_seconds = 0.1
		shown._refresh_seconds = 0.1
		with self.assertRaisesRegex(RuntimeError, "did not finish refreshing"):
			shown.render(Image.new("RGB", (800, 480)), 1)
		with self.assertRaises(TooSoon):
			shown.render(Image.new("RGB", (800, 480)), 2)

	def test_the_mock_display_rests_like_a_panel(self):
		cm = temp_configuration_manager(self)
		display = MockDisplay("mock")
		display.initialize(cm)
		self.assertEqual(display.gate.rest_seconds, 60)

class RecordingDisplay(DisplayBase):
	"""A panel that records what it is given, behind a real gate."""
	def __init__(self, rest: float, fail: bool = False):
		super().__init__("recording")
		self.gate = RefreshGate(rest)
		self.fail = fail
		self.frames: list[tuple[str|None, Any]] = []
	def initialize(self, cm):
		return (8, 6)
	def shutdown(self) -> None:
		pass
	def render(self, img, id, title=None):
		self.gate.begin()
		try:
			if self.fail:
				raise OSError("busy line")
			self.frames.append((title, img.convert("RGB").getpixel((0, 0))))
		finally:
			self.gate.finish()

def page(color, title: str) -> DisplayImage:
	return DisplayImage(NOW, title, Image.new("RGB", (8, 6), color))

class TestDisplayTask(unittest.TestCase):
	"""The Display task waits out the rest before it takes the next image, so what arrives meanwhile is one net image."""
	REST = 0.6

	def run_display(self, display: Display, panel: RecordingDisplay, body):
		comp = display.compositor
		async def go():
			taskq: asyncio.Queue = asyncio.Queue()
			loop = asyncio.create_task(display._task_render_and_display(taskq, comp, panel, None, MagicMock()))
			try:
				await body(taskq, comp)
			finally:
				loop.cancel()
		asyncio.run(go())

	def new_display(self) -> tuple[Display, list]:
		sent: list = []
		router = MessageRouter()
		router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		return Display("d", router), sent

	@staticmethod
	def put(comp: ImageCompositor, color, title: str) -> None:
		comp.set_layer_background(page(color, title))

	def test_pages_that_arrive_during_the_rest_are_one_net_image_drawn_after_it(self):
		display, sent = self.new_display()
		panel = RecordingDisplay(self.REST)
		async def body(taskq, comp):
			self.put(comp, RED, "first")
			await taskq.put(1)
			await asyncio.sleep(0.2)
			self.assertEqual(panel.frames, [("first", RED)])
			# two more during the rest: nothing is sent to the panel now
			self.put(comp, GREEN, "second")
			await taskq.put(2)
			await asyncio.sleep(0.1)
			self.put(comp, BLUE, "third")
			await taskq.put(3)
			await asyncio.sleep(0.2)
			self.assertEqual(panel.frames, [("first", RED)], "nothing is sent to the panel while it rests")
			await asyncio.sleep(self.REST + 0.3)
			self.assertEqual(panel.frames, [("first", RED), ("third", BLUE)], "the net result, once, after the rest")
		self.run_display(display, panel, body)
		deferred = [m.values for route, m in sent if route == "telemetry" and m.values.get("kind") == "deferred"]
		self.assertTrue(deferred, "the wait is told")
		self.assertIn("resting", deferred[0]["message"])

	def test_a_failed_refresh_rests_too_and_the_next_page_is_drawn_after_it(self):
		display, _ = self.new_display()
		panel = RecordingDisplay(self.REST, fail=True)
		async def body(taskq, comp):
			self.put(comp, RED, "first")
			await taskq.put(1)
			await asyncio.sleep(0.3)
			panel.fail = False
			self.put(comp, GREEN, "second")
			await taskq.put(2)
			await asyncio.sleep(0.2)
			self.assertEqual(panel.frames, [], "the failed refresh started a rest: nothing is sent yet")
			await asyncio.sleep(self.REST + 0.3)
			self.assertEqual(panel.frames, [("second", GREEN)])
		self.run_display(display, panel, body)

	def test_a_restart_inside_the_rest_waits_it_out_and_does_not_redraw_what_is_shown(self):
		cm = temp_configuration_manager(self)
		# the first run draws red
		display, _ = self.new_display()
		display.refresh_state = RefreshState(cm)
		panel = RecordingDisplay(self.REST)
		async def first(taskq, comp):
			self.put(comp, RED, "red")
			await taskq.put(1)
			await asyncio.sleep(0.3)
		self.run_display(display, panel, first)
		self.assertEqual(panel.frames, [("red", RED)])
		state = RefreshState(cm)
		state.load()
		self.assertIsNotNone(state.last_end)
		self.assertIsNotNone(state.digest)

		# the second run starts at once: the same page is not drawn again, a different one waits for the rest to be over
		again, _ = self.new_display()
		again.refresh_state = state
		panel2 = RecordingDisplay(self.REST)
		panel2.gate.restore(state.last_end)
		self.assertGreater(panel2.ready_in(), 0)
		async def second(taskq, comp):
			self.put(comp, RED, "red")
			await taskq.put(1)
			await asyncio.sleep(self.REST + 0.3)
			self.assertEqual(panel2.frames, [], "an unchanged picture is not drawn after a restart")
			self.put(comp, GREEN, "green")
			await taskq.put(2)
			await asyncio.sleep(0.3)
			self.assertEqual([title for title, _ in panel2.frames], ["green"])
		self.run_display(again, panel2, second)

	def test_a_refresh_that_failed_leaves_the_picture_unknown_so_the_same_page_is_tried_again(self):
		cm = temp_configuration_manager(self)
		display, _ = self.new_display()
		display.refresh_state = RefreshState(cm)
		panel = RecordingDisplay(0.2, fail=True)
		async def body(taskq, comp):
			self.put(comp, RED, "red")
			await taskq.put(1)
			await asyncio.sleep(0.3)
		self.run_display(display, panel, body)
		state = RefreshState(cm)
		state.load()
		self.assertIsNotNone(state.last_end, "it rested")
		self.assertIsNone(state.digest, "what the panel shows is not known")

class TestSettings(unittest.TestCase):
	def test_the_setting_is_in_the_factory_display_settings_and_in_its_schema(self):
		cm = temp_configuration_manager(self)
		_, settings = cm.settings_manager().open("display").get()
		assert settings is not None
		self.assertEqual(settings["refreshInterval"], 60)
		schema = cm.read_schema("display")
		assert schema is not None
		prop = next(p for p in schema["schema"]["properties"] if p["name"] == "refreshInterval")
		self.assertEqual((prop["type"], prop["minimum"]), ("integer", 0))
		self.assertTrue(prop.get("title") and prop.get("description"))

if __name__ == "__main__":
	unittest.main()
