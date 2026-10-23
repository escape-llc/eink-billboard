"""
The DeviceIO task and the devices it owns (#365): the single owner of the GPIO, I2C and SPI lines that are not the panel's. A device says that something happened (`InputEvent`) and the Application
gives it a meaning; the pins are checked against the panel's lines before anything is opened; and a configuration that cannot be opened leaves the previous one working.
"""
import datetime
import inspect
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from unittest.mock import patch

from ..device.bindings import DEFAULT_BINDINGS, action_for
from ..device.buttons import DEBOUNCE_SECONDS, LONG_PRESS_SECONDS, Buttons, load_button
from ..device.pins import FIRST_PIN, LAST_PIN, Panel, check_pins, panel_lines
from ..device.registry import available_devices
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PermanentError
from ..task.application import Application
from ..task.basic_task import handler_claims
from ..task.configure_event import ConfigureEvent, ConfigureNotify, ConfigureOptions
from ..task.device_io import DeviceIO
from ..task.display import Display
from ..task.message_router import MessageRouter
from ..task.messages import BasicMessage, ConfigurationChanged, InputEvent, QuitMessage, Telemetry
from ..task.playlist_layer import NextTrack, PlaylistLayer, ResumePlayback, StopPlayback
from ..task.timer_layer import TimerLayer
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

NOW = datetime.datetime(2026, 10, 19, 12, 0)

class FakeButton:
	"""A gpiozero-style button: the app sets `when_pressed` and `when_held`; a test presses it."""
	made: list["FakeButton"] = []
	def __init__(self, pin: int, pull_up: bool = True, bounce_time: float|None = None, hold_time: float = 1.0):
		self.pin, self.pull_up, self.bounce_time, self.hold_time = pin, pull_up, bounce_time, hold_time
		self.when_pressed: Callable[[], None]|None = None
		self.when_held: Callable[[], None]|None = None
		self.closed = False
		FakeButton.made.append(self)
	def close(self) -> None:
		self.closed = True

def fake_factory() -> tuple[Callable[..., FakeButton], list[FakeButton]]:
	made: list[FakeButton] = []
	def make(pin: int, **kwargs: Any) -> FakeButton:
		button = FakeButton(pin, **kwargs)
		made.append(button)
		return button
	return make, made

class TestPins(unittest.TestCase):
	def test_the_panels_lines_depend_on_the_display(self):
		self.assertEqual(panel_lines(None), {})
		self.assertEqual(panel_lines(Panel("mock", 800, 480)), {})
		self.assertEqual(panel_lines(Panel("tk", 800, 480)), {})
		self.assertEqual(set(panel_lines(Panel("waveshare", 800, 480))), {17, 25, 8, 24, 18, 10, 11})
		self.assertEqual(set(panel_lines(Panel("inky", 800, 480))), {27, 17, 22, 8, 10, 11})

	def test_the_big_inky_uses_two_more_lines(self):
		self.assertEqual(set(panel_lines(Panel("inky", 1600, 1200))) - set(panel_lines(Panel("inky", 800, 480))), {26, 16})
		self.assertEqual(set(panel_lines(Panel("inky", 1200, 1600))), set(panel_lines(Panel("inky", 1600, 1200))))

	def test_nothing_wrong_is_nothing_said(self):
		self.assertEqual(check_pins({ "a": 5, "b": 6 }, Panel("waveshare", 800, 480)), [])
		self.assertEqual(check_pins({}, Panel("inky", 800, 480)), [])

	def test_a_pin_the_panel_uses_is_refused_and_named(self):
		[problem] = check_pins({ "next": 17 }, Panel("waveshare", 800, 480), { "next": "next button" })
		self.assertIn("next button", problem)
		self.assertIn("pin 17", problem)
		self.assertIn("reset", problem)
		# the same pin is free on a display that is not a panel, and busy on the Inky
		self.assertEqual(check_pins({ "next": 17 }, Panel("mock", 800, 480)), [])
		self.assertIn("busy", check_pins({ "next": 17 }, Panel("inky", 800, 480))[0])

	def test_a_pin_used_twice_is_refused(self):
		[problem] = check_pins({ "a": 5, "b": 5 }, None, { "a": "play/stop button", "b": "next button" })
		self.assertIn("both on pin 5", problem)

	def test_a_pin_that_is_not_on_the_header_is_refused(self):
		for pin in (FIRST_PIN - 1, LAST_PIN + 1, 99, -3):
			with self.subTest(pin):
				self.assertIn("not a GPIO pin", check_pins({ "a": pin }, None)[0])

class TestButtons(unittest.TestCase):
	def test_the_pins_are_the_settings_that_are_set(self):
		buttons = Buttons(fake_factory()[0])
		self.assertEqual(buttons.pins({}), {})
		self.assertEqual(buttons.pins({ "buttonPlayStop": None, "buttonNext": 6, "buttonStop": "x" }), { "next": 6 })
		self.assertEqual(buttons.pins({ "buttonPlayStop": 5, "buttonNext": 6, "buttonStop": 13 }), { "play-stop": 5, "next": 6, "stop": 13 })
		self.assertEqual(buttons.pins({ "buttonNext": True }), {}, "a boolean is not a pin")

	def test_each_pin_is_a_button_wired_to_ground_with_a_debounce(self):
		make, made = fake_factory()
		Buttons(make).open(lambda name, gesture: None, { "buttonPlayStop": 5, "buttonNext": 6 })
		self.assertEqual([b.pin for b in made], [5, 6])
		for button in made:
			self.assertTrue(button.pull_up)
			self.assertEqual((button.bounce_time, button.hold_time), (DEBOUNCE_SECONDS, LONG_PRESS_SECONDS))

	def test_a_press_and_a_long_press_are_reported_with_the_inputs_name(self):
		make, made = fake_factory()
		said: list[tuple[str, str]] = []
		Buttons(make).open(lambda name, gesture: said.append((name, gesture)), { "buttonPlayStop": 5, "buttonNext": 6 })
		assert made[0].when_pressed and made[1].when_pressed and made[1].when_held
		made[0].when_pressed()
		made[1].when_pressed()
		made[1].when_held()
		self.assertEqual(said, [("play-stop", "press"), ("next", "press"), ("next", "long-press")])

	def test_callbacks_take_no_arguments_as_gpiozero_looks_at_them(self):
		make, made = fake_factory()
		Buttons(make).open(lambda name, gesture: None, { "buttonNext": 6 })
		assert made[0].when_pressed is not None
		self.assertEqual(len(inspect.signature(made[0].when_pressed).parameters), 0)

	def test_close_closes_every_button_and_is_safe_twice(self):
		make, made = fake_factory()
		buttons = Buttons(make)
		buttons.open(lambda name, gesture: None, { "buttonPlayStop": 5, "buttonNext": 6 })
		buttons.close()
		buttons.close()
		self.assertTrue(all(b.closed for b in made))

	def test_a_button_that_cannot_be_opened_leaves_nothing_open_and_says_so_in_our_words(self):
		made: list[FakeButton] = []
		def make(pin: int, **kwargs: Any) -> FakeButton:
			if pin == 6:
				raise OSError("pin busy: /dev/gpiochip0 secret detail")
			button = FakeButton(pin, **kwargs)
			made.append(button)
			return button
		with self.assertRaises(PermanentError) as caught:
			Buttons(make).open(lambda name, gesture: None, { "buttonPlayStop": 5, "buttonNext": 6 })
		self.assertTrue(all(b.closed for b in made), "the one that was opened is closed again")
		self.assertNotIn("gpiochip", str(caught.exception), "the library's words are in the log, not in the message")

	def test_without_the_device_libraries_it_says_what_to_do(self):
		with patch.dict(sys.modules, { "gpiozero": None }):
			with self.assertRaisesRegex(PermanentError, "device libraries"):
				load_button()

	def test_the_registry_knows_the_buttons(self):
		self.assertIsInstance(available_devices()["buttons"](), Buttons)

class TestBindings(unittest.TestCase):
	def test_a_press_means_what_the_table_says_and_the_rest_means_nothing(self):
		self.assertEqual(action_for("buttons", "next", "press"), "next")
		self.assertEqual(action_for("buttons", "play-stop", "press"), "toggle")
		self.assertEqual(action_for("buttons", "stop", "press"), "stop")
		self.assertIsNone(action_for("buttons", "next", "long-press"))
		self.assertIsNone(action_for("sensor", "next", "press"))
		self.assertEqual(set(DEFAULT_BINDINGS.values()), {"toggle", "next", "stop"})

class Sent:
	"""What went to the router, by route."""
	def __init__(self) -> None:
		self.messages: list[tuple[str, BasicMessage]] = []
		self.lock = threading.Lock()
	def on(self, route: str) -> list[BasicMessage]:
		with self.lock:
			return [m for r, m in self.messages if r == route]
	def wait_for(self, route: str, count: int = 1, seconds: float = 3.0) -> list[BasicMessage]:
		end = time.monotonic() + seconds
		while time.monotonic() < end:
			found = self.on(route)
			if len(found) >= count:
				return found
			time.sleep(0.02)
		return self.on(route)

def router_that_records() -> tuple[MessageRouter, Sent]:
	sent = Sent()
	router = MessageRouter()
	def record(route: str, msg: BasicMessage) -> None:
		with sent.lock:
			sent.messages.append((route, msg))
	router.send = record  # type: ignore[method-assign]
	return router, sent

class FakeDevice:
	"""A device with pins; opening it is recorded, and pin 26 cannot be opened (it passes the pin check, the device is what fails)."""
	id = "fake"
	def __init__(self) -> None:
		self.opened_with: dict[str, Any]|None = None
		self.emit: Callable[[str, str], None]|None = None
		self.closed = False
	def pins(self, config: Mapping[str, Any]) -> dict[str, int]:
		pin = config.get("buttonNext")
		return { "next": pin } if isinstance(pin, int) else {}
	def open(self, emit: Callable[[str, str], None], config: Mapping[str, Any]) -> None:
		if config.get("buttonNext") == 26:
			raise PermanentError("cannot open")
		self.opened_with, self.emit = dict(config), emit
	def close(self) -> None:
		self.closed = True

class TestDeviceIO(unittest.TestCase):
	def setUp(self) -> None:
		self.cm = temp_configuration_manager(self)
		self.router, self.sent = router_that_records()
		self.made: list[FakeDevice] = []
		def maker() -> FakeDevice:
			device = FakeDevice()
			self.made.append(device)
			return device
		self.io = DeviceIO("DeviceIO", self.router, { "fake": maker })
		self.io.RELOAD_DELAY_SECONDS = 0.05
		self.io._reload_coalescer._delay = 0.05
		# what the task swallows to keep running goes to the telemetry, as the Application wires it
		self.io.failure_sink = lambda telemetry: self.router.send("telemetry", telemetry)
		self.notified: list[ConfigureNotify] = []
		self.addCleanup(self.stop)

	def stop(self) -> None:
		if self.io.is_alive():
			self.io.accept(QuitMessage(NOW))
			self.io.join(timeout=3)

	def save(self, **pins: Any) -> None:
		cob = self.cm.settings_manager().open("devices")
		rev, content = cob.get()
		committed, _ = cob.save(rev, { **(content or {}), **pins })
		assert committed

	def configure(self, panel: Panel|None = None) -> ConfigureNotify:
		container = ServiceContainer()
		container.add_service(TimeOfDay, SystemTimeOfDay())
		if panel is not None:
			container.add_service(Panel, panel)
		sink = SimpleNamespace(accept=lambda msg: self.notified.append(msg))
		self.io.start()
		self.io.accept(ConfigureEvent(NOW, ConfigureOptions(cm=self.cm, isp=container), "device-io", sink))  # type: ignore[arg-type]
		end = time.monotonic() + 3
		while not self.notified and time.monotonic() < end:
			time.sleep(0.01)
		self.assertTrue(self.notified, "the task did not answer the configure event")
		return self.notified[-1]

	def test_the_factory_settings_connect_nothing(self):
		note = self.configure()
		self.assertFalse(note.error)
		self.assertEqual(note.content, { "open": [] })
		self.assertEqual(self.io.open_devices, ())
		self.assertEqual(self.made[0].opened_with, None, "a device with no pin set is not opened")

	def test_a_device_with_a_pin_is_opened_with_the_settings(self):
		self.save(buttonNext=6)
		note = self.configure()
		self.assertFalse(note.error)
		self.assertEqual(note.content, { "open": ["fake"] })
		self.assertEqual(self.made[0].opened_with["buttonNext"], 6)  # type: ignore[index]

	def test_what_a_device_reports_goes_to_the_application_on_the_device_input_route(self):
		self.save(buttonNext=6)
		self.configure()
		emit = self.made[0].emit
		assert emit is not None
		# from another thread, as a library's callback would
		threading.Thread(target=emit, args=("next", "press")).start()
		[event] = self.sent.wait_for("device-input")
		assert isinstance(event, InputEvent)
		self.assertEqual((event.source, event.name, event.gesture), ("fake", "next", "press"))

	def test_a_pin_the_panel_uses_is_refused_and_nothing_is_opened(self):
		self.save(buttonNext=17)
		note = self.configure(Panel("waveshare", 800, 480))
		self.assertTrue(note.error)
		self.assertIn("pin 17", str(note.content))
		self.assertIn("panel", str(note.content))
		self.assertEqual(self.io.open_devices, ())
		self.assertIsNone(self.made[0].opened_with)

	def test_a_device_that_cannot_be_opened_is_the_notes_error(self):
		self.save(buttonNext=26)
		note = self.configure()
		self.assertTrue(note.error)
		self.assertEqual(self.io.open_devices, ())

	def test_a_change_of_the_settings_is_applied_without_a_restart(self):
		self.save(buttonNext=6)
		self.configure()
		first = self.made[0]
		self.save(buttonNext=13)
		self.io.accept(ConfigurationChanged(NOW, "settings", "modified", "x"))
		self.assertTrue(self.wait_until(lambda: first.closed), "the old device was closed")
		self.assertTrue(self.wait_until(lambda: self.io.open_devices == ("fake",) and self.made[-1].opened_with is not None and self.made[-1].opened_with.get("buttonNext") == 13))
		self.assertTrue(self.sent.on("telemetry"), "the change is told")

	def test_a_burst_of_changes_is_read_once(self):
		self.save(buttonNext=6)
		self.configure()
		before = len(self.made)
		self.save(buttonNext=13)
		for _ in range(5):
			self.io.accept(ConfigurationChanged(NOW, "settings", "modified", "x"))
		self.assertTrue(self.wait_until(lambda: len(self.made) > before))
		time.sleep(0.4)
		# the previous device set up again once: one new set of devices, not five
		self.assertEqual(len(self.made) - before, 1)

	def test_a_change_to_something_else_in_the_settings_does_nothing(self):
		self.save(buttonNext=6)
		self.configure()
		before = len(self.made)
		self.io.accept(ConfigurationChanged(NOW, "settings", "modified", "theme"))
		time.sleep(0.4)
		self.assertEqual(len(self.made), before, "the devices' own document did not change: nothing is made again")
		self.assertFalse(self.made[0].closed)

	def test_a_bad_new_configuration_leaves_the_working_one_in_place(self):
		self.save(buttonNext=6)
		self.configure()
		self.save(buttonNext=26)
		self.io.accept(ConfigurationChanged(NOW, "settings", "modified", "x"))
		# the failure is reported, and the previous configuration is opened again
		self.assertTrue(self.wait_until(lambda: any(m.values.get("kind") == "error" for m in self.errors())), "the failure is told")
		self.assertTrue(self.wait_until(lambda: self.io.open_devices == ("fake",) and self.made[-1].opened_with is not None and self.made[-1].opened_with.get("buttonNext") == 6))

	def test_a_pin_the_panel_uses_in_a_changed_setting_keeps_the_working_device_open(self):
		self.save(buttonNext=6)
		self.configure(Panel("waveshare", 800, 480))
		first = self.made[0]
		self.save(buttonNext=17)
		self.io.accept(ConfigurationChanged(NOW, "settings", "modified", "x"))
		self.assertTrue(self.wait_until(lambda: any(m.values.get("kind") == "error" for m in self.errors())))
		self.assertFalse(first.closed, "nothing was closed to make room for a configuration that was refused")

	def test_quitting_closes_the_devices_and_a_late_press_is_dropped(self):
		self.save(buttonNext=6)
		self.configure()
		device = self.made[0]
		emit = device.emit
		assert emit is not None
		self.io.accept(QuitMessage(NOW))
		self.io.join(timeout=3)
		self.assertTrue(device.closed)
		emit("next", "press")   # nobody is listening: no error

	def errors(self) -> list[Telemetry]:
		return [m for m in self.sent.on("telemetry") if isinstance(m, Telemetry)]

	@staticmethod
	def wait_until(condition: Callable[[], bool], seconds: float = 3.0) -> bool:
		end = time.monotonic() + seconds
		while time.monotonic() < end:
			if condition():
				return True
			time.sleep(0.02)
		return condition()

class TestApplicationBindings(unittest.TestCase):
	"""The Application gives an input its meaning and sends the same commands the web app's buttons do."""
	def application(self, halted: bool = False, claimed: bool = True) -> tuple[Application, Sent]:
		app = Application("TestApp")
		router, sent = router_that_records()
		app.router = router
		app.playlist_layer = SimpleNamespace(halted=halted)  # type: ignore[assignment]
		if not claimed:
			app._held = (None, None)  # type: ignore[assignment]
		return app, sent

	def press(self, app: Application, name: str, gesture: str = "press") -> None:
		app._input_event(InputEvent(NOW, "buttons", name, gesture))

	def test_next_goes_to_the_playlist_layer(self):
		app, sent = self.application()
		self.press(app, "next")
		self.assertEqual([type(m) for m in sent.on("playlist-layer")], [NextTrack])

	def test_play_stop_toggles_with_the_state_of_playback(self):
		playing, sent = self.application(halted=False)
		self.press(playing, "play-stop")
		self.assertEqual([type(m) for m in sent.on("playlist-layer")], [StopPlayback])
		stopped, sent = self.application(halted=True)
		self.press(stopped, "play-stop")
		self.assertEqual([type(m) for m in sent.on("playlist-layer")], [ResumePlayback])

	def test_stop_only_stops(self):
		app, sent = self.application(halted=True)
		self.press(app, "stop")
		self.assertEqual([type(m) for m in sent.on("playlist-layer")], [StopPlayback])

	def test_a_press_is_told_to_the_telemetry_in_words(self):
		app, sent = self.application()
		self.press(app, "next")
		[event] = [m for m in sent.on("telemetry") if isinstance(m, Telemetry)]
		self.assertEqual(event.values["kind"], "input")
		self.assertEqual(event.values["action"], "next")
		self.assertIn("next button", event.values["message"])

	def test_an_input_bound_to_nothing_is_ignored(self):
		app, sent = self.application()
		self.press(app, "next", "long-press")
		self.press(app, "nothing")
		self.assertEqual(sent.messages, [])

	def test_a_press_while_the_device_is_not_claimed_is_dropped(self):
		app, sent = self.application(claimed=False)
		self.press(app, "next")
		self.assertEqual(sent.on("playlist-layer"), [])

class TestDevicesSettings(WebApiTestBase):
	def test_the_factory_document_has_no_buttons(self):
		doc = self.client.get("/api/settings/devices").json()
		self.assertEqual((doc["buttonPlayStop"], doc["buttonNext"], doc["buttonStop"]), (None, None, None))

	def test_its_schema_is_served_and_every_property_is_described(self):
		schema = self.client.get("/api/schemas/devices").json()
		properties = [p for p in schema["schema"]["properties"] if p["type"] != "header"]
		self.assertEqual({p["name"] for p in properties}, {"buttonPlayStop", "buttonNext", "buttonStop"})
		for p in properties:
			self.assertTrue(p.get("title") and p.get("description"), p["name"])
			self.assertEqual((p["type"], p["minimum"], p["maximum"]), ("integer", FIRST_PIN, LAST_PIN))

	def test_a_pin_is_saved_and_one_off_the_header_is_refused(self):
		doc = self.client.get("/api/settings/devices").json()
		saved = self.client.put("/api/settings/devices", json={ **doc, "buttonNext": 6 })
		self.assertEqual(saved.status_code, 200, saved.text)
		self.assertEqual(self.client.get("/api/settings/devices").json()["buttonNext"], 6)
		refused = self.client.put("/api/settings/devices", json={ **self.client.get("/api/settings/devices").json(), "buttonNext": 40 })
		self.assertEqual(refused.status_code, 422)
		self.assertEqual(refused.json()["errors"][0]["path"], ["buttonNext"])

class TestMissingDocument(unittest.TestCase):
	def test_a_storage_seeded_before_the_devices_settings_connects_nothing(self):
		# upgrade_settings leaves a missing document alone (a deleted file stays deleted): the task reads none as none connected, and the settings page starts from the schema's default
		cm = temp_configuration_manager(self)
		os.remove(cm.settings_manager().settings_path("devices"))
		router, _ = router_that_records()
		io = DeviceIO("DeviceIO", router, { "fake": FakeDevice })
		io.cm = cm
		self.assertEqual(io._read_settings(), {})
		self.assertEqual(io._apply({}), ())

class TestEveryHandlerIsRegistered(unittest.TestCase):
	"""
	A task's handlers are the methods marked @handles (#579); two of one class for the same message type, or a mark that disagrees with its parameter, fail
	when the task is made. This checks the real tasks without making them (they need a router and a storage): a mistake fails here, not on a device.
	"""
	def test_every_task_class_has_consistent_marks(self):
		for cls in (Application, Display, PlaylistLayer, TimerLayer, DeviceIO):
			with self.subTest(cls.__name__):
				claims = handler_claims(cls)
				self.assertTrue(claims, "a task with no handlers")
				self.assertFalse(any(issubclass(t, QuitMessage) for t in claims))

if __name__ == "__main__":
	unittest.main()
