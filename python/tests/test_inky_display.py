import threading
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image

from ..display import inky_display
from ..display.inky_display import DEFAULT_SATURATION, InkyDisplay, load_driver
from ..plugins.plugin_base import PermanentError
from ..task.configure_event import ConfigureEvent, ConfigureNotify, ConfigureOptions
from ..task.display import Display
from ..task.message_router import MessageRouter
from ..task.telemetry_hub import TelemetryHub
from ..model.service_container import ServiceContainer
from .utils import temp_configuration_manager

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

class FakeInky:
	"""A 7-color board: `set_image` takes a saturation."""
	def __init__(self, width=800, height=480):
		self.width, self.height = width, height
		self.calls: list[tuple] = []
	def set_image(self, image, saturation=0.5):
		self.calls.append(("set_image", image.size, saturation))
	def show(self):
		self.calls.append(("show",))

class FakePhat:
	"""A board whose `set_image` takes no saturation (it quantizes to its own colors)."""
	def __init__(self):
		self.width, self.height = 250, 122
		self.calls: list[tuple] = []
	def set_image(self, image):
		self.calls.append(("set_image", image.size))
	def show(self):
		self.calls.append(("show",))

def settings_of(settings: dict|None = None) -> Any:
	cm = MagicMock()
	cm.settings_manager.return_value.open.return_value.get.return_value = ("rev", settings or {})
	return cm

def display_with(device: Any, settings: dict|None = None) -> InkyDisplay:
	shown = InkyDisplay("inky", loader=lambda: device)
	shown.initialize(settings_of(settings))
	return shown

class TestDriver(unittest.TestCase):
	def test_the_resolution_is_the_boards_and_the_image_reaches_it(self):
		board = FakeInky(600, 448)
		shown = display_with(board)
		self.assertEqual(shown.resolution, (600, 448))
		shown.render(Image.new("RGB", (600, 448), "red"), 1, "a page")
		self.assertEqual(board.calls, [("set_image", (600, 448), DEFAULT_SATURATION), ("show",)])

	def test_the_saturation_is_a_setting_and_a_board_without_one_is_not_given_it(self):
		board = FakeInky()
		display_with(board, { "inky-saturation": 0.8 }).render(Image.new("RGB", (800, 480)), 1)
		self.assertEqual(board.calls[0], ("set_image", (800, 480), 0.8))
		for bad in ("x", True, None):
			self.assertEqual(display_with(FakeInky(), { "inky-saturation": bad }).saturation(), DEFAULT_SATURATION)
		self.assertEqual(display_with(FakeInky(), { "inky-saturation": 7 }).saturation(), 1.0)
		phat = FakePhat()
		display_with(phat, { "inky-saturation": 0.8 }).render(Image.new("RGB", (250, 122)), 1)
		self.assertEqual(phat.calls, [("set_image", (250, 122)), ("show",)])

	def test_an_image_of_another_size_or_mode_is_fitted_not_refused(self):
		board = FakeInky()
		shown = display_with(board)
		with self.assertLogs(inky_display.__name__, level="WARNING"):
			shown.render(Image.new("RGBA", (400, 240), (255, 0, 0, 0)), 1)
		self.assertEqual(board.calls[0][1], (800, 480))

	def test_a_board_that_does_not_say_its_size_or_a_loader_that_fails_is_worded(self):
		with self.assertRaisesRegex(PermanentError, "did not say how big"):
			display_with(object())
		def broken():
			raise OSError("spi")
		with self.assertRaisesRegex(PermanentError, "could not be started"):
			InkyDisplay("inky", loader=broken).initialize(settings_of())

	def test_rendering_before_or_after_the_display_exists_is_an_error_not_a_crash_of_the_driver(self):
		shown = InkyDisplay("inky", loader=lambda: FakeInky())
		with self.assertRaises(RuntimeError):
			shown.render(Image.new("RGB", (8, 8)), 1)
		shown = display_with(FakeInky())
		shown.shutdown()
		with self.assertRaises(RuntimeError):
			shown.render(Image.new("RGB", (800, 480)), 1)

class TestGuard(unittest.TestCase):
	def test_a_panel_that_never_says_it_is_done_is_a_timeout_and_nothing_more_is_sent(self):
		release = threading.Event()
		class Stuck(FakeInky):
			def show(self):
				release.wait(5)
		self.addCleanup(release.set)
		shown = InkyDisplay("inky", loader=lambda: Stuck(), refresh_seconds=0.1)
		# no rest between refreshes here: it is the guard that refuses the second one (the rest is tested in test_refresh_gate)
		shown.initialize(settings_of({ "refreshInterval": 0 }))
		with self.assertRaisesRegex(RuntimeError, "did not finish refreshing"):
			shown.render(Image.new("RGB", (800, 480)), 1)
		with self.assertRaisesRegex(RuntimeError, "has not finished the last refresh"):
			shown.render(Image.new("RGB", (800, 480)), 2)
		release.set()

	def test_a_board_that_never_answers_when_it_is_made_is_worded_not_waited_for(self):
		release = threading.Event()
		def silent():
			release.wait(5)
		self.addCleanup(release.set)
		with self.assertRaisesRegex(PermanentError, "did not answer when it was started"):
			InkyDisplay("inky", loader=silent, start_seconds=0.1).initialize(settings_of())
		release.set()

class TestLoading(unittest.TestCase):
	def test_a_machine_without_the_driver_is_told_what_to_do(self):
		with patch("importlib.import_module", side_effect=ImportError("No module named 'inky'")), self.assertRaisesRegex(PermanentError, "driver is not installed.*mock or tk"):
			load_driver()

	def test_no_board_is_told_to_check_the_wiring(self):
		auto = MagicMock(side_effect=RuntimeError("No EEPROM detected! You must manually initialise your Inky board."))
		module = MagicMock(auto=auto)
		with patch("importlib.import_module", return_value=module), self.assertRaisesRegex(PermanentError, "No Inky display was found.*SPI and I2C"):
			load_driver()
		auto.assert_called_once_with(ask_user=False, verbose=False)

	def test_a_board_the_driver_does_not_know_is_told_apart_from_no_board(self):
		module = MagicMock(auto=MagicMock(side_effect=RuntimeError("Can't find a driver this display.")))
		with patch("importlib.import_module", return_value=module), self.assertRaisesRegex(PermanentError, "does not support it.*Update the driver"):
			load_driver()

	def test_a_board_is_returned_as_the_driver_made_it(self):
		board = FakeInky()
		with patch("importlib.import_module", return_value=MagicMock(auto=MagicMock(return_value=board))):
			self.assertIs(load_driver(), board)

class TestDisplayTask(unittest.TestCase):
	"""The Display task makes the Inky display; when the driver cannot be loaded it does not start, and says why."""
	def configure(self, driver_error: BaseException|None):
		cm = temp_configuration_manager(self)
		cob = cm.settings_manager().open("display")
		rev, doc = cob.get()
		assert doc is not None
		cob.save(rev, { **doc, "display_type": "inky" })
		notes: list[ConfigureNotify] = []
		sink = MagicMock()
		sink.accept.side_effect = notes.append
		display = Display("Display", MessageRouter())
		patcher = patch.object(inky_display, "load_driver", side_effect=driver_error) if driver_error is not None else patch.object(inky_display, "load_driver", return_value=FakeInky())
		with patcher:
			display._configure_event(ConfigureEvent(NOW, ConfigureOptions(cm=cm, isp=ServiceContainer()), "display", sink))  # type: ignore[arg-type]
		return display, notes

	def test_a_missing_driver_fails_the_display_in_our_words_and_the_status_says_so(self):
		_, [note] = self.configure(PermanentError("The Inky driver is not installed. Choose the mock display."))
		self.assertTrue(note.error)
		hub = TelemetryHub()
		hub.accept(note)
		status = hub.status()["components"]
		self.assertEqual(status["display"]["state"], "failed")
		self.assertIn("The Inky driver is not installed", status["display"]["message"])
		self.assertEqual(status["playlist-layer"]["message"], "Waiting for the display.")
		[event] = hub.since(0)
		self.assertEqual(event["kind"], "configure-failed")
		self.assertIn("The Inky driver is not installed", event["message"])

	def test_an_error_that_is_not_ours_is_not_put_in_the_status(self):
		hub = TelemetryHub()
		hub.accept(ConfigureNotify(NOW, "display", True, ValueError("spi at /dev/spidev0.0 with key=SECRET")))  # type: ignore[call-arg]
		self.assertEqual(hub.status()["components"]["display"]["message"], "Could not be set up. See the log, fix the settings, then restart.")
		self.assertNotIn("SECRET", str(hub.since(0)))

if __name__ == "__main__":
	unittest.main()
