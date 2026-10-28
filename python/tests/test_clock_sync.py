"""The layers wait for the clock to be set (#785): `ClockSync` reads timesyncd's flag, and the Application holds the layers until it is there, or for a while at most."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from ..model.clock_sync import SYNCED_FLAG, ClockSync
from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import ServiceContainer
from ..task.application import Application
from ..task.configure_event import ConfigureEvent
from ..task.display_messages import DisplaySettings
from ..task.messages import ClockCheck, SetupDone, Telemetry, TransportCommand

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

class TestClockSync(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.folder = os.path.join(tmp.name, "timesync")

	def test_no_timesyncd_is_unknown_its_folder_unsynced_and_its_flag_synced(self):
		clock = ClockSync(self.folder)
		self.assertEqual(clock.state(), "unknown")
		os.mkdir(self.folder)
		self.assertEqual(clock.state(), "unsynced")
		with open(os.path.join(self.folder, SYNCED_FLAG), "w", encoding="utf-8"):
			pass
		self.assertEqual(clock.state(), "synced")

class FakeClock:
	def __init__(self, state: str):
		self.value = state
	def state(self) -> str:
		return self.value

class Steps:
	"""The hub, as the Application's start sees it: the steps it says."""
	def __init__(self):
		self.kinds: list[str] = []
		self.messages: list[str] = []
	def accept(self, msg: Any) -> None:
		if isinstance(msg, Telemetry):
			self.kinds.append(msg.values["kind"])
			self.messages.append(msg.values["message"])

class ClockHoldCase(unittest.TestCase):
	def application(self, state: str|None, notice=lambda: None) -> tuple[Application, FakeClock]:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.steps = Steps()
		app = Application("t", sink=self.steps)
		app.cm = ConfigurationManager(storage_path=tmp.name)
		app.cm.hard_reset()
		app.router = MagicMock()
		app.setup_notice = notice
		app.root_container = ServiceContainer()
		clock = FakeClock(state or "unknown")
		if state is not None:
			app.root_container.add_service(ClockSync, clock)
		app.playlist_layer, app.timer_layer = MagicMock(), MagicMock()
		# the poll is driven by the test, never by a real timer
		app.clock_poll_seconds = 3600
		self.addCleanup(app._end_clock_wait)
		app._display_settings(DisplaySettings(NOW, "mock", 800, 480, []))
		return app, clock

	def assertStarted(self, app: Application):
		for layer, token in ((app.playlist_layer, "playlist-layer"), (app.timer_layer, "timer-layer")):
			[(event,), _] = layer.accept.call_args  # type: ignore[union-attr]
			self.assertIsInstance(event, ConfigureEvent)
			self.assertEqual(event.token, token)

	def assertWaiting(self, app: Application):
		app.playlist_layer.accept.assert_not_called()  # type: ignore[union-attr]
		app.timer_layer.accept.assert_not_called()  # type: ignore[union-attr]

class TestTheLayersWaitForTheClock(ClockHoldCase):
	def test_a_clock_that_is_set_starts_the_layers_at_once_and_says_so(self):
		app, _ = self.application("synced")
		self.assertStarted(app)
		self.assertEqual(self.steps.kinds, ["clock-ready"])

	def test_no_timesyncd_starts_them_at_once_as_before(self):
		for state in ("unknown", None):
			with self.subTest(state=state):
				app, _ = self.application(state)
				self.assertStarted(app)
				self.assertEqual(self.steps.kinds, [])

	def test_a_clock_set_after_the_start_starts_them_then(self):
		app, clock = self.application("unsynced")
		self.assertWaiting(app)
		self.assertEqual(self.steps.kinds, ["waiting-for-clock"])
		app._clock_check(ClockCheck(NOW))
		self.assertWaiting(app)
		clock.value = "synced"
		app._clock_check(ClockCheck(NOW))
		self.assertStarted(app)
		self.assertEqual(self.steps.kinds, ["waiting-for-clock", "clock-ready"])
		self.assertIsNone(app._clock_held)
		# a late check after the start does nothing
		app._clock_check(ClockCheck(NOW))
		app.playlist_layer.accept.assert_called_once()  # type: ignore[union-attr]

	def test_a_clock_never_set_starts_them_after_the_limit_and_says_it_may_be_wrong(self):
		app, _ = self.application("unsynced")
		app._clock_deadline = 0.0
		app._clock_check(ClockCheck(NOW))
		self.assertStarted(app)
		self.assertEqual(self.steps.kinds, ["waiting-for-clock", "clock-unsure"])
		self.assertIn("may be wrong", self.steps.messages[-1])

	def test_while_they_wait_play_stop_next_and_run_now_are_refused(self):
		app, _ = self.application("unsynced")
		app._transport_command(TransportCommand(NOW, "stop"))
		app.router.send.assert_not_called()  # type: ignore[attr-defined]
		self.assertFalse(app.run_task("a"))
		self.assertIn("clock", app.run_trigger(17))

	def test_an_unclaimed_device_waits_for_its_owner_then_for_the_clock(self):
		notice = ["Open http://pi.local", "Setup code 1234 5678"]
		app, clock = self.application("unsynced", notice=lambda: notice)
		self.assertWaiting(app)
		self.assertEqual(self.steps.kinds, ["waiting-for-setup"])
		notice.clear()
		app._setup_done(SetupDone(NOW))
		self.assertWaiting(app)
		self.assertEqual(self.steps.kinds, ["waiting-for-setup", "set-up", "waiting-for-clock"])
		clock.value = "synced"
		app._clock_check(ClockCheck(NOW))
		self.assertStarted(app)

	def test_a_stop_while_they_wait_ends_the_wait(self):
		app, _ = self.application("unsynced")
		self.assertIsNotNone(app._clock_timer)
		app._handleStop(NOW)
		self.assertIsNone(app._clock_timer)
		self.assertIsNone(app._clock_held)
