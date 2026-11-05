"""
The LED (#885): a pattern for each event, one at a time (a gesture over the states, a problem over drawing), dark in the quiet hours; opened by the DeviceIO task beside the buttons,
told of each press, each state on the `indicator` route and each Test; its pin checked against the panel's and the buttons' at a save.
"""
import datetime
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from ..device import led as led_module
from ..device.led import GESTURES, PATTERNS, STATES, Led, Pattern, pattern_of, quiet, state_pattern
from ..device.pins import Panel
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PermanentError
from ..task.application import Application
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.device_io import DeviceIO
from ..task.messages import Indicate, InputEvent, LedTest, QuitMessage
from .test_device_io import FakeDevice, router_that_records
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

NOW = datetime.datetime(2026, 11, 5, 12, 0)

def at(hour: int) -> datetime.datetime:
	return datetime.datetime(2026, 11, 5, hour, 30)

class FakeLed:
	"""A gpiozero-style LED: each switch is recorded with the time since it was made."""
	def __init__(self, pin: int):
		self.pin = pin
		self.lit = False
		self.closed = False
		self.lock = threading.Lock()
		self.start = time.monotonic()
		self.switches: list[tuple[float, bool]] = []
	def on(self) -> None:
		self._set(True)
	def off(self) -> None:
		self._set(False)
	def _set(self, lit: bool) -> None:
		with self.lock:
			if lit != self.lit:
				self.switches.append((time.monotonic() - self.start, lit))
			self.lit = lit
	def close(self) -> None:
		self.closed = True
	def lit_count(self) -> int:
		with self.lock:
			return sum(1 for _, lit in self.switches if lit)

def wait_until(test, seconds: float = 3.0) -> bool:
	end = time.monotonic() + seconds
	while time.monotonic() < end:
		if test():
			return True
		time.sleep(0.01)
	return test()

# the patterns, fast (a test does not wait a second for a blink); the same names, so the settings' values still choose them
FAST_BLINK = (0.03, 0.05)
FAST = {
	"off": Pattern("Off", (), False),
	"blink-1": Pattern("One blink", (FAST_BLINK,), False),
	"blink-2": Pattern("Two blinks", (FAST_BLINK, FAST_BLINK), False),
	"blink-3": Pattern("Three blinks", (FAST_BLINK, FAST_BLINK, FAST_BLINK), False),
	"steady": Pattern("Steady", ((0.05, 0.0),), True),
	"slow": Pattern("Slow blink", ((0.05, 0.05),), True),
	"fast": Pattern("Fast blink", ((0.02, 0.02),), True),
	"heartbeat": Pattern("Heartbeat", ((0.02, 0.02), (0.02, 0.06)), True),
}

class TestPatternRules(unittest.TestCase):
	def test_every_choice_of_the_schema_is_a_pattern_and_the_defaults_are_the_schemas(self):
		import json, os
		path = os.path.join(os.path.dirname(__file__), "..", "storage", "schemas", "devices.json")
		with open(path, encoding="utf-8") as f:
			schema = json.load(f)
		items = schema["schema"]["lookups"]["ledPatterns"]["items"]
		self.assertEqual([i["value"] for i in items], list(PATTERNS))
		self.assertEqual([i["name"] for i in items], [p.title for p in PATTERNS.values()])
		fields = { p["name"]: p for p in schema["schema"]["properties"] }
		for field, fallback in [*GESTURES.values(), *((f, d) for _, f, d in STATES)]:
			self.assertEqual(fields[field]["default"], fallback, field)
			self.assertEqual(schema["default"][field], fallback, field)
			self.assertEqual(fields[field]["lookup"], "ledPatterns", field)

	def test_a_field_not_set_or_not_a_pattern_is_its_default(self):
		self.assertEqual(pattern_of({}, "ledPress", "blink-1"), "blink-1")
		self.assertEqual(pattern_of({ "ledPress": None }, "ledPress", "blink-1"), "blink-1")
		self.assertEqual(pattern_of({ "ledPress": "disco" }, "ledPress", "blink-1"), "blink-1")
		self.assertEqual(pattern_of({ "ledPress": "heartbeat" }, "ledPress", "blink-1"), "heartbeat")

	def test_the_quiet_hours_cross_midnight_and_either_end_unset_is_never_quiet(self):
		night = { "ledQuietFrom": 22, "ledQuietTo": 7 }
		self.assertEqual([h for h in range(24) if quiet(night, at(h))], [0, 1, 2, 3, 4, 5, 6, 22, 23])
		lunch = { "ledQuietFrom": 12, "ledQuietTo": 14 }
		self.assertEqual([h for h in range(24) if quiet(lunch, at(h))], [12, 13])
		for never in ({}, { "ledQuietFrom": 22 }, { "ledQuietTo": 7 }, { "ledQuietFrom": 9, "ledQuietTo": 9 }, { "ledQuietFrom": True, "ledQuietTo": 7 }, { "ledQuietFrom": 24, "ledQuietTo": 7 }):
			self.assertFalse(any(quiet(never, at(h)) for h in range(24)), never)

	def test_a_problem_comes_before_drawing_unless_its_pattern_is_off(self):
		chosen = { "ledProblem": "slow", "ledDrawing": "steady" }
		self.assertEqual(state_pattern(chosen, { "problem", "drawing" }), ("problem", "slow"))
		self.assertEqual(state_pattern(chosen, { "drawing" }), ("drawing", "steady"))
		self.assertEqual(state_pattern(chosen, set()), (None, "off"))
		# the factory settings: a problem is Off, so the panel drawing still shows
		self.assertEqual(state_pattern({}, { "problem", "drawing" }), ("drawing", "steady"))

@patch.dict(led_module.PATTERNS, FAST)
class TestLed(unittest.TestCase):
	def open(self, clock_hour: int = 12, **config: Any) -> tuple[Led, list[FakeLed]]:
		made: list[FakeLed] = []
		def factory(pin: int) -> FakeLed:
			made.append(FakeLed(pin))
			return made[-1]
		led = Led(factory=factory, clock=lambda: at(clock_hour))
		led.IDLE_SECONDS = 0.05
		led.TEST_SECONDS = 0.2
		self.played: list[tuple[str, str]] = []
		led.on_play = lambda title, why: self.played.append((title, why))
		led.open(lambda name, gesture: None, { "ledPin": 13, **config })
		self.addCleanup(led.close)
		return led, made

	def test_no_pin_is_no_led(self):
		led = Led(factory=lambda pin: self.fail("opened with no pin"))
		self.assertEqual(led.pins({}), {})
		self.assertEqual(led.pins({ "ledPin": True }), {})
		self.assertEqual(Led().pins({ "ledPin": 13 }), { "led": 13 })
		led.open(lambda name, gesture: None, {})
		led.close()

	def test_a_press_blinks_once_and_a_long_press_twice(self):
		led, [fake] = self.open()
		led.gesture("press")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 1 and not fake.lit))
		led.gesture("long-press")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 3 and not fake.lit))
		time.sleep(0.15)
		self.assertEqual(fake.lit_count(), 3, "a gesture plays once")
		self.assertEqual(self.played, [("One blink", "a press"), ("Two blinks", "a long press")])
		led.gesture("release")
		time.sleep(0.1)
		self.assertEqual(fake.lit_count(), 3, "a release is not a gesture the LED answers")

	def test_drawing_is_steady_until_it_ends_and_a_press_plays_over_it(self):
		led, [fake] = self.open()
		led.state("drawing", True)
		self.assertTrue(wait_until(lambda: fake.lit))
		time.sleep(0.15)
		self.assertTrue(fake.lit, "steady stays on")
		led.gesture("press")
		# the blink: off, on, off, then the steady light again
		self.assertTrue(wait_until(lambda: fake.lit_count() >= 3 and fake.lit))
		led.state("drawing", False)
		self.assertTrue(wait_until(lambda: not fake.lit))
		self.assertEqual(self.played[0], ("Steady", "the panel drawing"))
		self.assertIn(("One blink", "a press"), self.played)

	def test_a_problem_shows_before_drawing_and_drawing_again_after_it(self):
		led, [fake] = self.open(ledProblem="slow")
		led.state("drawing", True)
		led.state("problem", True)
		self.assertTrue(wait_until(lambda: ("Slow blink", "a problem") in self.played))
		count = fake.lit_count()
		self.assertTrue(wait_until(lambda: fake.lit_count() >= count + 2), "a slow blink repeats")
		led.state("problem", False)
		self.assertTrue(wait_until(lambda: self.played[-1] == ("Steady", "the panel drawing")))

	def test_the_quiet_hours_are_dark_and_a_test_still_plays(self):
		led, [fake] = self.open(clock_hour=23, ledQuietFrom=22, ledQuietTo=7)
		led.state("drawing", True)
		led.gesture("press")
		time.sleep(0.2)
		self.assertEqual(fake.lit_count(), 0)
		led.test("blink-2")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 2 and not fake.lit))
		self.assertEqual(self.played, [("Two blinks", "a test")])

	def test_a_test_of_a_pattern_that_repeats_plays_a_few_seconds(self):
		led, [fake] = self.open()
		led.test("fast")
		# TEST_SECONDS (0.2 here) of it, then dark
		time.sleep(0.4)
		count = fake.lit_count()
		self.assertGreaterEqual(count, 3)
		self.assertFalse(fake.lit)
		time.sleep(0.2)
		self.assertEqual(fake.lit_count(), count, "then it stops")
		led.test("disco")
		time.sleep(0.1)
		self.assertEqual(fake.lit_count(), count, "not a pattern: nothing")

	def test_closing_switches_it_off_and_lets_the_pin_go(self):
		led, [fake] = self.open()
		led.state("drawing", True)
		self.assertTrue(wait_until(lambda: fake.lit))
		led.close()
		self.assertFalse(fake.lit)
		self.assertTrue(fake.closed)

	def test_an_led_that_cannot_be_opened_says_so_in_our_words(self):
		def broken(pin: int) -> FakeLed:
			raise OSError("pin busy: /dev/gpiochip0")
		with self.assertLogs(led_module.logger, "ERROR"), self.assertRaises(PermanentError) as raised:
			Led(factory=broken).open(lambda name, gesture: None, { "ledPin": 13 })
		self.assertNotIn("gpiochip", str(raised.exception))

class TestLedInDeviceIO(unittest.TestCase):
	def setUp(self) -> None:
		self.cm = temp_configuration_manager(self)
		self.router, self.sent = router_that_records()
		self.leds: list[Led] = []
		self.fakes: list[FakeLed] = []
		def make_led() -> Led:
			def factory(pin: int) -> FakeLed:
				self.fakes.append(FakeLed(pin))
				return self.fakes[-1]
			self.leds.append(Led(factory=factory))
			return self.leds[-1]
		self.io = DeviceIO("DeviceIO", self.router, { "fake": FakeDevice, "led": make_led })
		self.notified: list[Any] = []
		self.addCleanup(self.stop)

	def stop(self) -> None:
		if self.io.is_alive():
			self.io.accept(QuitMessage(NOW))
			self.io.join(timeout=3)

	def configure(self, panel: Panel|None = None, **settings: Any) -> Any:
		cob = self.cm.settings_manager().open("devices")
		rev, content = cob.get()
		committed, _ = cob.save(rev, { **(content or {}), **settings })
		assert committed
		container = ServiceContainer()
		container.add_service(TimeOfDay, SystemTimeOfDay())
		if panel is not None:
			container.add_service(Panel, panel)
		self.io.start()
		self.io.accept(ConfigureEvent(NOW, ConfigureOptions(cm=self.cm, isp=container), "device-io", SimpleNamespace(accept=self.notified.append)))  # type: ignore[arg-type]
		self.assertTrue(wait_until(lambda: bool(self.notified)))
		return self.notified[-1]

	def test_the_led_is_opened_with_its_pin_and_answers_a_press_a_state_and_a_test(self):
		with patch.dict(led_module.PATTERNS, FAST):
			note = self.configure(ledPin=13, triggers=[{ "pin": 5, "action": "next" }])
			self.assertFalse(note.error, note.content)
			self.assertTrue(self.io.led_open)
			[fake] = self.fakes
			self.assertEqual(fake.pin, 13)
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "press"))
			self.assertTrue(wait_until(lambda: fake.lit_count() == 1 and not fake.lit))
			# faulted and unclaimed are both a problem; the factory pattern for one is Off, so drawing shows
			self.io.accept(Indicate(NOW, "drawing", True))
			self.assertTrue(wait_until(lambda: fake.lit))
			self.io.accept(Indicate(NOW, "drawing", False))
			self.assertTrue(wait_until(lambda: not fake.lit))
			count = fake.lit_count()
			self.io.accept(LedTest(NOW, "blink-3"))
			self.assertTrue(wait_until(lambda: fake.lit_count() == count + 3 and not fake.lit))
			# the patterns it played are said, for the GPIO tab's live view
			said = [m.values["message"] for m in self.sent.wait_for("telemetry", 1) if m.values.get("kind") == "led"]
			self.assertIn("LED: one blink, a press", said)
			self.assertIn("LED: three blinks, a test", said)

	def test_a_state_that_began_before_the_led_was_opened_shows_at_once(self):
		self.io.cm = self.cm
		self.io._indicate(Indicate(NOW, "faulted", True))
		self.io._indicate(Indicate(NOW, "unclaimed", True))
		self.io._indicate(Indicate(NOW, "unclaimed", False))
		self.assertEqual(self.io._signals, { "faulted" })
		with patch.dict(led_module.PATTERNS, FAST):
			self.configure(ledPin=13, ledProblem="slow")
			[fake] = self.fakes
			self.assertTrue(wait_until(lambda: fake.lit_count() >= 2), "the problem is shown as soon as the LED is open")

	def test_no_pin_no_led_and_a_test_is_not_taken(self):
		self.configure()
		self.assertFalse(self.io.led_open)
		self.assertEqual(self.fakes, [])

	def test_the_led_and_a_button_on_one_pin_are_refused_before_anything_is_opened(self):
		with self.assertLogs(level="ERROR"):
			note = self.configure(ledPin=5, triggers=[{ "pin": 5, "action": "next" }])
		self.assertTrue(note.error)
		self.assertIn("LED", str(note.content))
		self.assertEqual(self.fakes, [])

	def test_the_led_is_not_on_a_pin_the_panel_uses(self):
		with self.assertLogs(level="ERROR"):
			note = self.configure(Panel("inky", 800, 480), ledPin=17)
		self.assertTrue(note.error)
		self.assertIn("The LED is on pin 17, which the panel uses", str(note.content))

class TestPlaylistFault(unittest.TestCase):
	def test_the_led_hears_once_that_playback_stopped_and_once_that_it_is_over(self):
		from ..task.playlist_layer import LayerFaulted, PlaylistLayer
		router, sent = router_that_records()
		layer = PlaylistLayer("playlistlayer", router)
		self.addCleanup(layer._cancel_restart)
		layer._layer_faulted(LayerFaulted(NOW))
		layer._layer_faulted(LayerFaulted(NOW))
		layer._show_fault(False, NOW)
		layer._show_fault(False, NOW)
		self.assertEqual([(m.signal, m.on) for m in sent.on("indicator")], [("faulted", True), ("faulted", False)])

class TestApplicationLedTest(unittest.TestCase):
	def test_a_test_goes_to_the_device_io_task_only_when_an_led_is_open(self):
		app = Application.__new__(Application)
		app._now = lambda: NOW  # type: ignore[method-assign]
		app.device_io = None
		self.assertFalse(app.led_test("blink-1"))
		taken: list[Any] = []
		app.device_io = SimpleNamespace(led_open=False, accept=taken.append)  # type: ignore[assignment]
		self.assertFalse(app.led_test("blink-1"))
		app.device_io = SimpleNamespace(led_open=True, accept=taken.append)  # type: ignore[assignment]
		self.assertTrue(app.led_test("blink-1"))
		[msg] = taken
		self.assertIsInstance(msg, LedTest)
		self.assertEqual(msg.pattern, "blink-1")

class TestLedSettings(WebApiTestBase):
	def put(self, **fields: Any):
		doc = self.client.get("/api/settings/devices").json()
		return self.client.put("/api/settings/devices", json={ **doc, **fields })

	def test_the_factory_document_has_no_led_and_the_default_patterns(self):
		doc = self.client.get("/api/settings/devices").json()
		self.assertEqual((doc["ledPin"], doc["ledPress"], doc["ledLongPress"], doc["ledDrawing"], doc["ledProblem"]), (None, "blink-1", "blink-2", "steady", "off"))

	def test_an_led_is_saved_and_its_pin_is_not_a_buttons_or_the_panels(self):
		saved = self.put(ledPin=13, ledProblem="heartbeat", ledQuietFrom=22, ledQuietTo=7)
		self.assertEqual(saved.status_code, 200, saved.text)
		clash = self.put(ledPin=5, triggers=[{ "pin": 5, "action": "next", "playlist": None }])
		self.assertEqual(clash.status_code, 422)
		self.assertIn({ "path": ["ledPin"], "message": "A button uses this pin: each needs its own." }, clash.json()["errors"])
		doc = self.client.get("/api/settings/display").json()
		self.assertEqual(self.client.put("/api/settings/display", json={ **doc, "display_type": "inky" }).status_code, 200)
		panel = self.put(ledPin=17, triggers=[])
		self.assertIn({ "path": ["ledPin"], "message": "The panel uses this pin (busy): choose another." }, panel.json()["errors"])

	def test_a_pattern_that_is_not_one_and_an_hour_off_the_clock_are_refused(self):
		bad = self.put(ledPress="disco", ledQuietFrom=24)
		self.assertEqual(bad.status_code, 422)
		paths = [e["path"] for e in bad.json()["errors"]]
		self.assertIn(["ledPress"], paths)
		self.assertIn(["ledQuietFrom"], paths)

	def test_the_test_beside_a_pattern_plays_it_when_there_is_an_led(self):
		asked: list[str] = []
		self.open = True
		self.app.state.root_container.add_service(Application, SimpleNamespace(playlist_layer=object(), led_test=lambda p: asked.append(p) or self.open))
		played = self.client.post("/api/devices/led/test", json={ "value": "heartbeat" })
		self.assertEqual(played.json(), { "ok": True, "message": "Playing heartbeat on the LED." })
		self.assertEqual(asked, ["heartbeat"])
		self.open = False
		self.assertFalse(self.client.post("/api/devices/led/test", json={ "value": "slow" }).json()["ok"])
		self.assertEqual(self.client.post("/api/devices/led/test", json={ "value": "disco" }).json(), { "ok": False, "message": "Choose a pattern first." })
		self.assertTrue(self.client.post("/api/devices/led/test", json={ "value": "off" }).json()["ok"])
		self.assertEqual(asked, ["heartbeat", "slow"], "Off and a pattern that is not one are not played")

if __name__ == "__main__":
	unittest.main()
