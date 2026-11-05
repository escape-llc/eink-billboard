"""
The outputs (#885, #891): each output is a compositor of its own (a gesture over the states, held before a problem before drawing, still in the quiet hours, a Test over everything),
drawn by its kind's renderer (an LED here, a fake that does not hold for haptic and audio); opened by the DeviceIO task beside the buttons, told of each press, each state on the
`indicator` route and each Test; their pins and rows checked at a save. An output whose hardware is not there is said, and the rest play.
"""
import datetime
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import patch

from ..device import gpio_output
from ..device.cues import CUES, EVENTS, KINDS
from ..device.gpio_output import BLINK, NORMAL_BLINK, PATTERNS, SPEEDS, GpioRenderer, scale_of
from ..device.outputs import Outputs, cues_for
from ..device.pins import Panel
from ..device.player import Player, quiet
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PermanentError
from ..task.application import Application
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.device_io import DeviceIO
from ..task.messages import Indicate, InputEvent, OutputTest, QuitMessage
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

class OnceRenderer:
	"""A renderer that does not hold (a haptic motor, a sound card): each cue it is asked to play is recorded."""
	holds = False
	def __init__(self) -> None:
		self.played: list[tuple[str, Mapping[str, Any]|None]] = []
		self.closed = False
	def play(self, cue: str, stop: threading.Event, seconds: float, options: Mapping[str, Any]|None = None) -> bool:
		self.played.append((cue, options))
		return False
	def off(self) -> None:
		pass
	def close(self) -> None:
		self.closed = True

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
	"off": (),
	"one": (FAST_BLINK,),
	"two": (FAST_BLINK, FAST_BLINK),
	"three": (FAST_BLINK, FAST_BLINK, FAST_BLINK),
	"steady": ((0.05, 0.0),),
	"slow": ((0.05, 0.05),),
	"fast": ((0.02, 0.02),),
	"heartbeat": ((0.02, 0.02), (0.02, 0.06)),
}
# the factory feedback: what the LED says for each event
FACTORY = { "press": "one", "long-press": "two", "holding": "steady", "drawing": "steady" }

def led_settings(pin: int|None = 13, cues: Mapping[str, str] = FACTORY, **extra: Any) -> dict[str, Any]:
	"""The `devices` settings with one GPIO output, LED, on `pin`, saying `cues`."""
	return { "outputs": [{ "name": "LED", "kind": "gpio", "pin": pin, "speed": "0.4", "volume": None }], "feedback": [{ "event": e, "output": "LED", "cue": c } for e, c in cues.items()], **extra }

class TestCueRules(unittest.TestCase):
	def test_every_choice_of_the_schema_is_ours_and_the_factory_document_is_the_leds(self):
		import json, os
		path = os.path.join(os.path.dirname(__file__), "..", "storage", "schemas", "devices.json")
		with open(path, encoding="utf-8") as f:
			schema = json.load(f)
		lookups = schema["schema"]["lookups"]
		self.assertEqual([i["value"] for i in lookups["cues"]["items"]], list(CUES))
		self.assertEqual([i["name"] for i in lookups["cues"]["items"]], [c.title for c in CUES.values()])
		self.assertEqual(tuple(i["value"] for i in lookups["speeds"]["items"]), SPEEDS)
		self.assertEqual(tuple(i["value"] for i in lookups["events"]["items"]), EVENTS)
		fields = { p["name"]: p for p in schema["schema"]["properties"] }
		kind = next(p for p in fields["outputs"]["items"]["properties"] if p["name"] == "kind")
		self.assertEqual(tuple(kind["enum"]), KINDS)
		self.assertEqual(set(PATTERNS), set(CUES), "the LED plays every cue")
		self.assertEqual(sum(BLINK), NORMAL_BLINK, "the normal speed is the blink the patterns are written for")
		factory = schema["default"]
		self.assertEqual(cues_for(factory, "LED"), FACTORY)
		self.assertEqual(factory["outputs"][0]["pin"], None, "the factory LED is not connected until its pin is chosen")

	def test_a_speed_stretches_every_cue_alike_and_anything_else_is_the_normal_speed(self):
		self.assertEqual((scale_of("0.4"), scale_of("0.8"), scale_of("0.2")), (1.0, 2.0, 0.5))
		for normal in (None, "", "0.9", 0.8, "fast"):
			self.assertEqual(scale_of(normal), 1.0, normal)

	def test_the_quiet_hours_cross_midnight_and_either_end_unset_is_never_quiet(self):
		night = { "quietFrom": 22, "quietTo": 7 }
		self.assertEqual([h for h in range(24) if quiet(night, at(h))], [0, 1, 2, 3, 4, 5, 6, 22, 23])
		lunch = { "quietFrom": 12, "quietTo": 14 }
		self.assertEqual([h for h in range(24) if quiet(lunch, at(h))], [12, 13])
		for never in ({}, { "quietFrom": 22 }, { "quietTo": 7 }, { "quietFrom": 9, "quietTo": 9 }, { "quietFrom": True, "quietTo": 7 }, { "quietFrom": 24, "quietTo": 7 }):
			self.assertFalse(any(quiet(never, at(h)) for h in range(24)), never)

	def test_an_output_plays_what_its_rows_say_and_the_first_row_of_an_event_wins(self):
		config = { "feedback": [
			{ "event": "press", "output": "LED", "cue": "one" },
			{ "event": "press", "output": "LED", "cue": "three" },
			{ "event": "press", "output": "Motor", "cue": "two" },
			{ "event": "drawing", "output": "LED", "cue": "disco" },
			{ "event": "sneeze", "output": "LED", "cue": "one" },
		] }
		self.assertEqual(cues_for(config, "LED"), { "press": "one" })
		self.assertEqual(cues_for(config, "Motor"), { "press": "two" })

	def test_what_each_kind_of_output_asks_of_the_header(self):
		outputs = Outputs()
		self.assertFalse(outputs.wanted(led_settings(pin=None)), "a GPIO output with no pin is not connected")
		self.assertEqual(outputs.pins(led_settings()), { "output-LED": 13 })
		haptic = { "outputs": [{ "name": "Motor", "kind": "haptic" }] }
		self.assertTrue(outputs.wanted(haptic))
		self.assertEqual(outputs.pins(haptic), { "i2c-data": 2, "i2c-clock": 3 }, "the haptic driver is on the I²C bus")
		audio = { "outputs": [{ "name": "Speaker", "kind": "audio" }] }
		self.assertTrue(outputs.wanted(audio))
		self.assertEqual(outputs.pins(audio), {}, "a USB sound card uses no pin")

@patch.dict(gpio_output.PATTERNS, FAST)
class TestPlayer(unittest.TestCase):
	def open(self, clock_hour: int = 12, cues: Mapping[str, str] = FACTORY, speed: str = "0.4", **config: Any) -> tuple[Player, FakeLed]:
		made: list[FakeLed] = []
		def factory(pin: int) -> FakeLed:
			made.append(FakeLed(pin))
			return made[-1]
		self.played: list[tuple[str, str]] = []
		player = Player("LED", GpioRenderer(13, speed, factory), cues, config, lambda: at(clock_hour), lambda title, why: self.played.append((title, why)))
		player.IDLE_SECONDS = 0.05
		player.TEST_SECONDS = 0.2
		player.start()
		self.addCleanup(player.close)
		return player, made[0]

	def test_a_press_blinks_once_and_a_long_press_twice(self):
		player, fake = self.open()
		player.gesture("press")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 1 and not fake.lit))
		player.gesture("long-press")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 3 and not fake.lit))
		time.sleep(0.15)
		self.assertEqual(fake.lit_count(), 3, "a gesture plays once")
		self.assertEqual(self.played, [("One", "a press"), ("Two", "a long press")])
		player.gesture("release")
		time.sleep(0.1)
		self.assertEqual(fake.lit_count(), 3, "a release is not a gesture an output answers")

	def test_drawing_is_steady_until_it_ends_and_a_press_plays_over_it(self):
		player, fake = self.open()
		player.state("drawing", True)
		self.assertTrue(wait_until(lambda: fake.lit))
		time.sleep(0.15)
		self.assertTrue(fake.lit, "steady stays on")
		player.gesture("press")
		# the blink: off, on, off, then the steady light again
		self.assertTrue(wait_until(lambda: fake.lit_count() >= 3 and fake.lit))
		player.state("drawing", False)
		self.assertTrue(wait_until(lambda: not fake.lit))
		self.assertEqual(self.played[0], ("Steady", "the panel drawing"))
		self.assertIn(("One", "a press"), self.played)

	def test_held_comes_before_a_problem_and_a_problem_before_drawing(self):
		player, fake = self.open(cues={ **FACTORY, "problem": "slow", "holding": "fast" })
		player.state("drawing", True)
		player.state("problem", True)
		self.assertTrue(wait_until(lambda: ("Slow", "a problem") in self.played))
		count = fake.lit_count()
		self.assertTrue(wait_until(lambda: fake.lit_count() >= count + 2), "a slow blink repeats")
		player.state("holding", True)
		self.assertTrue(wait_until(lambda: self.played[-1] == ("Fast", "a button held")))
		player.state("holding", False)
		self.assertTrue(wait_until(lambda: self.played[-1] == ("Slow", "a problem")))
		player.state("problem", False)
		self.assertTrue(wait_until(lambda: self.played[-1] == ("Steady", "the panel drawing")))

	def test_the_quiet_hours_are_still_and_a_test_still_plays(self):
		player, fake = self.open(clock_hour=23, quietFrom=22, quietTo=7)
		player.state("drawing", True)
		player.gesture("press")
		time.sleep(0.2)
		self.assertEqual(fake.lit_count(), 0)
		player.test("two")
		self.assertTrue(wait_until(lambda: fake.lit_count() == 2 and not fake.lit))
		self.assertEqual(self.played, [("Two", "a test")])

	def test_a_test_of_a_cue_that_repeats_plays_a_few_seconds(self):
		player, fake = self.open()
		player.test("fast")
		# TEST_SECONDS (0.2 here) of it, then dark
		time.sleep(0.4)
		count = fake.lit_count()
		self.assertGreaterEqual(count, 3)
		self.assertFalse(fake.lit)
		time.sleep(0.2)
		self.assertEqual(fake.lit_count(), count, "then it stops")
		player.test("disco")
		time.sleep(0.1)
		self.assertEqual(fake.lit_count(), count, "not a cue: nothing")

	def test_the_speed_plays_each_step_longer_or_shorter_and_a_test_may_choose_its_own(self):
		fake = FakeLed(13)
		renderer = GpioRenderer(13, "0.8", lambda pin: fake)
		renderer.play("one", threading.Event(), 0.0)
		[(on, _), (off, _)] = fake.switches
		self.assertGreaterEqual(off - on, 0.055, "twice as long at 0.8 s a blink")
		fake.switches.clear()
		renderer.play("one", threading.Event(), 0.0, { "speed": "0.2" })
		[(on, _), (off, _)] = fake.switches
		self.assertLess(off - on, 0.05, "half as long at the Test's 0.2 s")

	def test_closing_switches_it_off_and_lets_the_pin_go(self):
		player, fake = self.open()
		player.state("drawing", True)
		self.assertTrue(wait_until(lambda: fake.lit))
		player.close()
		self.assertFalse(fake.lit)
		self.assertTrue(fake.closed)

	def test_an_led_that_cannot_be_opened_says_so_in_our_words(self):
		def broken(pin: int) -> FakeLed:
			raise OSError("pin busy: /dev/gpiochip0")
		with self.assertLogs(gpio_output.logger, "ERROR"), self.assertRaises(PermanentError) as raised:
			GpioRenderer(13, None, broken)
		self.assertNotIn("gpiochip", str(raised.exception))

class TestOutputThatDoesNotHold(unittest.TestCase):
	def test_a_state_plays_its_cue_once_when_it_begins_and_a_gesture_each_time(self):
		renderer = OnceRenderer()
		player = Player("Motor", renderer, { "press": "one", "drawing": "fast" }, {}, lambda: at(12))
		player.IDLE_SECONDS = 0.05
		player.start()
		self.addCleanup(player.close)
		player.state("drawing", True)
		self.assertTrue(wait_until(lambda: len(renderer.played) == 1))
		time.sleep(0.2)
		self.assertEqual(renderer.played, [("fast", None)], "a buzz when the panel starts drawing, not a buzz all through it")
		player.gesture("press")
		self.assertTrue(wait_until(lambda: len(renderer.played) == 2))
		time.sleep(0.2)
		self.assertEqual([cue for cue, _ in renderer.played], ["fast", "one"], "the state that goes on is not played again")
		player.state("drawing", False)
		# the player sees it end (a refresh is half a minute apart from the next)
		time.sleep(0.1)
		player.state("drawing", True)
		self.assertTrue(wait_until(lambda: len(renderer.played) == 3), "a state that begins again plays again")
		player.test("two", { "volume": 30 })
		self.assertTrue(wait_until(lambda: renderer.played[-1] == ("two", { "volume": 30 })))

class TestOutputs(unittest.TestCase):
	def test_an_output_whose_hardware_is_not_there_is_said_and_the_rest_play(self):
		def gpio(row: Mapping[str, Any]) -> GpioRenderer:
			return GpioRenderer(row["pin"], row.get("speed"), FakeLed)
		def missing(row: Mapping[str, Any]) -> Any:
			raise PermanentError("No haptic driver answers on the I²C bus.")
		outputs = Outputs({ "gpio": gpio, "haptic": missing, "audio": lambda row: OnceRenderer() })
		config = { "outputs": [
			{ "name": "LED", "kind": "gpio", "pin": 13 },
			{ "name": "Motor", "kind": "haptic" },
			{ "name": "Speaker", "kind": "audio" },
			{ "name": "Spare", "kind": "gpio", "pin": None },
		] }
		with self.assertLogs("python.device.outputs", "WARNING"):
			outputs.open(lambda name, gesture: None, config)
		self.addCleanup(outputs.close)
		self.assertEqual(outputs.names, ("LED", "Speaker"))
		self.assertEqual(outputs.problems, ["The output Motor: No haptic driver answers on the I²C bus."])
		self.assertTrue(outputs.test("Speaker", "one"))
		self.assertFalse(outputs.test("Motor", "one"))
		self.assertFalse(outputs.test("Spare", "one"))

class TestOutputsInDeviceIO(unittest.TestCase):
	def setUp(self) -> None:
		self.cm = temp_configuration_manager(self)
		self.router, self.sent = router_that_records()
		self.fakes: list[FakeLed] = []
		self.missing = False
		def gpio(row: Mapping[str, Any]) -> GpioRenderer:
			def factory(pin: int) -> FakeLed:
				self.fakes.append(FakeLed(pin))
				return self.fakes[-1]
			return GpioRenderer(row["pin"], row.get("speed"), factory)
		def haptic(row: Mapping[str, Any]) -> Any:
			raise PermanentError("No haptic driver answers on the I²C bus.")
		self.io = DeviceIO("DeviceIO", self.router, { "fake": FakeDevice, "outputs": lambda: Outputs({ "gpio": gpio, "haptic": haptic, "audio": lambda row: OnceRenderer() }) })
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
		with patch.dict(gpio_output.PATTERNS, FAST):
			note = self.configure(**led_settings(), triggers=[{ "pin": 5, "action": "next" }])
			self.assertFalse(note.error, note.content)
			self.assertTrue(self.io.output_open("LED"))
			[fake] = self.fakes
			self.assertEqual(fake.pin, 13)
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "press"))
			self.assertTrue(wait_until(lambda: fake.lit_count() == 1 and not fake.lit))
			# faulted and unclaimed are both a problem; the factory has no cue for one, so drawing shows
			self.io.accept(Indicate(NOW, "drawing", True))
			self.assertTrue(wait_until(lambda: fake.lit))
			self.io.accept(Indicate(NOW, "drawing", False))
			self.assertTrue(wait_until(lambda: not fake.lit))
			count = fake.lit_count()
			self.io.accept(OutputTest(NOW, "LED", "three"))
			self.assertTrue(wait_until(lambda: fake.lit_count() == count + 3 and not fake.lit))
			# the cues it played are said, for the GPIO tab's live view
			said = [m.values["message"] for m in self.sent.wait_for("telemetry", 1) if m.values.get("kind") == "output"]
			self.assertIn("LED: one, a press", said)
			self.assertIn("LED: three, a test", said)

	def test_held_past_a_long_press_the_led_says_let_go_and_then_plays_the_long_press(self):
		with patch.dict(gpio_output.PATTERNS, FAST):
			self.configure(**led_settings(), triggers=[{ "pin": 5, "action": "next" }])
			[fake] = self.fakes
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "down"))
			time.sleep(0.1)
			self.assertEqual(fake.lit_count(), 0, "a button going down plays nothing: what it is is decided at the release")
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "hold"))
			self.assertTrue(wait_until(lambda: fake.lit), "held: steady, the cue to let go")
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "release"))
			self.io.accept(InputEvent(NOW, "fake", "gpio-5", "long-press"))
			self.assertTrue(wait_until(lambda: fake.lit_count() == 3 and not fake.lit), "then two blinks, and dark")
			time.sleep(0.15)
			self.assertEqual(fake.lit_count(), 3, "the hold is over: nothing more")

	def test_a_state_that_began_before_the_outputs_were_opened_shows_at_once(self):
		self.io.cm = self.cm
		self.io._indicate(Indicate(NOW, "faulted", True))
		self.io._indicate(Indicate(NOW, "unclaimed", True))
		self.io._indicate(Indicate(NOW, "unclaimed", False))
		self.assertEqual(self.io._signals, { "faulted" })
		with patch.dict(gpio_output.PATTERNS, FAST):
			self.configure(**led_settings(cues={ "problem": "slow" }))
			[fake] = self.fakes
			self.assertTrue(wait_until(lambda: fake.lit_count() >= 2), "the problem is shown as soon as the LED is open")

	def test_the_factory_led_has_no_pin_so_nothing_is_opened(self):
		self.configure()
		self.assertFalse(self.io.output_open("LED"))
		self.assertEqual(self.fakes, [])

	def test_an_output_and_a_button_on_one_pin_are_refused_before_anything_is_opened(self):
		with self.assertLogs(level="ERROR"):
			note = self.configure(**led_settings(pin=5), triggers=[{ "pin": 5, "action": "next" }])
		self.assertTrue(note.error)
		self.assertIn("output LED", str(note.content))
		self.assertEqual(self.fakes, [])

	def test_an_output_is_not_on_a_pin_the_panel_uses(self):
		with self.assertLogs(level="ERROR"):
			note = self.configure(Panel("inky", 800, 480), **led_settings(pin=17))
		self.assertTrue(note.error)
		self.assertIn("The output LED is on pin 17, which the panel uses", str(note.content))

	def test_an_output_whose_hardware_is_missing_is_told_and_the_buttons_and_the_led_still_work(self):
		settings = led_settings()
		settings["outputs"].append({ "name": "Motor", "kind": "haptic" })
		with self.assertLogs("python.device.outputs", "WARNING"):
			note = self.configure(**settings, triggers=[{ "pin": 5, "action": "next" }])
		self.assertFalse(note.error, note.content)
		self.assertEqual(self.io.open_devices, ("fake", "outputs"))
		self.assertTrue(self.io.output_open("LED"))
		told = [m.values["message"] for m in self.sent.wait_for("telemetry", 1) if m.values.get("kind") == "devices"]
		self.assertIn("The output Motor: No haptic driver answers on the I²C bus.", told)

class TestPlaylistFault(unittest.TestCase):
	def test_the_outputs_hear_once_that_playback_stopped_and_once_that_it_is_over(self):
		from ..task.playlist_layer import LayerFaulted, PlaylistLayer
		router, sent = router_that_records()
		layer = PlaylistLayer("playlistlayer", router)
		self.addCleanup(layer._cancel_restart)
		layer._layer_faulted(LayerFaulted(NOW))
		layer._layer_faulted(LayerFaulted(NOW))
		layer._show_fault(False, NOW)
		layer._show_fault(False, NOW)
		self.assertEqual([(m.signal, m.on) for m in sent.on("indicator")], [("faulted", True), ("faulted", False)])

class TestApplicationOutputTest(unittest.TestCase):
	def test_a_test_goes_to_the_device_io_task_only_when_its_output_is_open(self):
		app = Application.__new__(Application)
		app._now = lambda: NOW  # type: ignore[method-assign]
		app.device_io = None
		self.assertFalse(app.output_test("LED", "one"))
		taken: list[Any] = []
		app.device_io = SimpleNamespace(output_open=lambda name: False, accept=taken.append)  # type: ignore[assignment]
		self.assertFalse(app.output_test("LED", "one"))
		app.device_io = SimpleNamespace(output_open=lambda name: name == "LED", accept=taken.append)  # type: ignore[assignment]
		self.assertTrue(app.output_test("LED", "one"))
		self.assertFalse(app.output_test("Motor", "one"))
		self.assertTrue(app.output_test("LED", "three", { "speed": "0.6" }))
		self.assertEqual([(m.output, m.cue, m.options) for m in taken], [("LED", "one", None), ("LED", "three", { "speed": "0.6" })])

class TestOutputSettings(WebApiTestBase):
	def put(self, **fields: Any):
		doc = self.client.get("/api/settings/devices").json()
		return self.client.put("/api/settings/devices", json={ **doc, **fields })

	def errors(self, response) -> list[dict]:
		self.assertEqual(response.status_code, 422, response.text)
		return response.json()["errors"]

	def test_the_factory_document_has_the_led_with_no_pin_and_its_feedback(self):
		doc = self.client.get("/api/settings/devices").json()
		self.assertEqual([(o["name"], o["kind"], o["pin"]) for o in doc["outputs"]], [("LED", "gpio", None)])
		self.assertEqual(cues_for(doc, "LED"), FACTORY)

	def test_an_output_is_saved_and_its_pin_is_not_a_buttons_another_outputs_or_the_panels(self):
		self.assertEqual(self.put(**led_settings(quietFrom=22, quietTo=7)).status_code, 200)
		clash = self.put(**led_settings(pin=5), triggers=[{ "pin": 5, "action": "next", "playlist": None }])
		self.assertIn({ "path": ["outputs", "0", "pin"], "message": "A button uses this pin: each needs its own." }, self.errors(clash))
		twice = led_settings()
		twice["outputs"].append({ "name": "Buzzer", "kind": "gpio", "pin": 13, "speed": "0.4", "volume": None })
		self.assertIn({ "path": ["outputs", "1", "pin"], "message": "Another output uses this pin: each needs its own." }, self.errors(self.put(**twice)))
		doc = self.client.get("/api/settings/display").json()
		self.assertEqual(self.client.put("/api/settings/display", json={ **doc, "display_type": "inky" }).status_code, 200)
		self.assertIn({ "path": ["outputs", "0", "pin"], "message": "The panel uses this pin (busy): choose another." }, self.errors(self.put(**led_settings(pin=17), triggers=[])))

	def test_a_haptic_output_keeps_the_i2c_pins_free(self):
		settings = led_settings(pin=3)
		settings["outputs"].append({ "name": "Motor", "kind": "haptic", "pin": None, "speed": None, "volume": None })
		errors = self.errors(self.put(**settings, triggers=[{ "pin": 2, "action": "next", "playlist": None }]))
		self.assertIn({ "path": ["outputs", "0", "pin"], "message": "The haptic output uses this pin (the I²C bus): choose another." }, errors)
		self.assertIn({ "path": ["triggers", "0", "pin"], "message": "The haptic output uses this pin (the I²C bus): choose another." }, errors)

	def test_a_row_names_an_output_of_the_settings_and_a_cue_and_an_event_are_ours(self):
		settings = led_settings()
		settings["feedback"] += [{ "event": "press", "output": "Motor", "cue": "one" }, { "event": "sneeze", "output": "LED", "cue": "disco" }]
		paths = { tuple(e["path"]): e["message"] for e in self.errors(self.put(**settings)) }
		self.assertEqual(paths[("feedback", "4", "output")], "No output has this name: add it under Outputs.")
		self.assertIn(("feedback", "5", "event"), paths)
		self.assertIn(("feedback", "5", "cue"), paths)
		self.assertIn(("quietFrom",), { tuple(e["path"]) for e in self.errors(self.put(quietFrom=24)) })

	def test_a_feedback_row_chooses_from_the_saved_outputs(self):
		self.assertEqual(self.client.get("/api/devices/outputs").json(), [{ "name": "LED", "value": "LED" }])

	def test_the_test_beside_a_cue_plays_it_on_the_rows_output_when_it_is_open(self):
		asked: list[tuple[str, str, Any]] = []
		self.open = True
		self.app.state.root_container.add_service(Application, SimpleNamespace(playlist_layer=object(), output_test=lambda o, c, opts=None: asked.append((o, c, opts)) or self.open))
		played = self.client.post("/api/devices/outputs/test", json={ "value": "heartbeat", "row": { "event": "drawing", "output": "LED", "cue": "heartbeat" } })
		self.assertEqual(played.json(), { "ok": True, "message": "Playing heartbeat on LED." })
		self.open = False
		self.assertFalse(self.client.post("/api/devices/outputs/test", json={ "value": "slow", "row": { "output": "LED" } }).json()["ok"])
		self.assertEqual(self.client.post("/api/devices/outputs/test", json={ "value": "disco", "row": { "output": "LED" } }).json(), { "ok": False, "message": "Choose a cue first." })
		self.assertEqual(self.client.post("/api/devices/outputs/test", json={ "value": "one" }).json(), { "ok": False, "message": "Choose an output first." })
		self.assertTrue(self.client.post("/api/devices/outputs/test", json={ "value": "off", "row": { "output": "LED" } }).json()["ok"])
		self.assertEqual(asked, [("LED", "heartbeat", None), ("LED", "slow", None)], "Off and a cue that is not one are not played")

	def test_the_test_beside_a_speed_plays_three_blinks_at_the_speed_chosen(self):
		asked: list[tuple[str, str, Any]] = []
		self.app.state.root_container.add_service(Application, SimpleNamespace(playlist_layer=object(), output_test=lambda o, c, opts=None: asked.append((o, c, opts)) or True))
		played = self.client.post("/api/devices/outputs/speed-test", json={ "value": "0.7", "row": { "name": "LED", "kind": "gpio" } })
		self.assertEqual(played.json(), { "ok": True, "message": "Playing three blinks at 0.7 s a blink on LED." })
		self.assertEqual(asked, [("LED", "three", { "speed": "0.7" })])
		self.assertEqual(self.client.post("/api/devices/outputs/speed-test", json={ "value": "9", "row": { "name": "LED" } }).json(), { "ok": False, "message": "Choose a speed first." })

if __name__ == "__main__":
	unittest.main()
