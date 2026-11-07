"""
The Clock Chime and a timer task's cue (#918): what a clock plays at each quarter, a sequence played on an output with its counts, and the cue any timer task that draws may play.
"""
import asyncio
import datetime
import threading
import time
import unittest
from typing import Any

from ..device.cues import CUES, PLAYABLE
from ..device.outputs import Outputs
from ..device.player import Player
from ..model.schedule import TimerTaskItem, TimerTaskTask
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay
from ..plugins.clock_chime.clock_chime import ClockChimeAsync, chime_steps
from ..plugins.plugin_base import PluginExecutionContext
from ..task.device_io import DeviceIO
from ..task.message_router import MessageRouter
from ..task.messages import OutputCue
from ..task.timer_layer import TimerLayer
from .test_device_io import router_that_records
from .test_layer_features import PLUGINS
from .test_outputs import OnceRenderer, wait_until

WESTMINSTER_HOUR = (("change-2", 1), ("change-3", 1), ("change-4", 1), ("change-5", 1))

def at(hour: int, minute: int = 0, second: int = 0) -> datetime.datetime:
	return datetime.datetime(2026, 11, 6, hour, minute, second)

def task(content: dict[str, Any], title: str = "Clock") -> TimerTaskItem:
	return TimerTaskItem("t1", title, True, TimerTaskTask("clock-chime", content), { "time": { "type": "hourly", "minutes": [0], "hours": [] }, "day": { "type": "dayofweek", "days": [] } })  # type: ignore[typeddict-item]

class TestWhatTheClockPlays(unittest.TestCase):
	def test_the_westminster_quarters_and_the_hours_strikes(self):
		self.assertEqual(chime_steps(at(15, 15), "westminster", True, True)[2], (("change-1", 1),))
		self.assertEqual(chime_steps(at(15, 30), "westminster", True, True)[2], (("change-2", 1), ("change-3", 1)))
		self.assertEqual(chime_steps(at(15, 45), "westminster", True, True)[2], (("change-4", 1), ("change-5", 1), ("change-1", 1)))
		self.assertEqual(chime_steps(at(15), "westminster", True, True)[2], (*WESTMINSTER_HOUR, ("bell", 3)))

	def test_it_plays_the_quarter_nearest_the_time_it_woke(self):
		self.assertEqual(chime_steps(at(10, 58, 30), "westminster", True, True), (11, 0, (*WESTMINSTER_HOUR, ("bell", 11))))
		self.assertEqual(chime_steps(at(23, 59), "westminster", True, True), (0, 0, (*WESTMINSTER_HOUR, ("bell", 12))), "midnight strikes twelve")
		self.assertEqual(chime_steps(at(12, 1), "none", True, True)[2], (("bell", 12),))
		self.assertEqual(chime_steps(at(13, 14), "westminster", True, True)[:2], (13, 1))

	def test_strikes_only_gives_one_at_half_past_and_nothing_at_the_other_quarters(self):
		self.assertEqual(chime_steps(at(9, 30), "none", True, True)[2], (("bell", 1),))
		self.assertEqual(chime_steps(at(9, 30), "none", True, False)[2], ())
		self.assertEqual(chime_steps(at(9, 15), "none", True, True)[2], ())

	def test_the_hour_need_not_be_struck(self):
		self.assertEqual(chime_steps(at(9), "westminster", False, True)[2], WESTMINSTER_HOUR)
		self.assertEqual(chime_steps(at(9), "none", False, True)[2], ())

	def test_every_cue_it_plays_is_one_every_output_plays(self):
		for minute in (0, 15, 30, 45):
			for chimes in ("westminster", "none"):
				self.assertTrue(all(cue in PLAYABLE for cue, _ in chime_steps(at(8, minute), chimes, True, True)[2]))

class TestTheClockChimeTask(unittest.TestCase):
	def run_at(self, when: datetime.datetime, **content: Any) -> list[tuple[str, Any]]:
		router, sent = router_that_records()
		container = ServiceContainer()
		container.add_service(MessageRouter, router)
		done = threading.Event()
		asyncio.run(ClockChimeAsync("clock-chime", "Clock Chime").task_async(PluginExecutionContext(container, (800, 480), when), task({ "cueOutput": "Speaker", "chimes": "westminster", "strikeHour": True, "halfHour": True, **content }), done))
		self.assertTrue(done.is_set())
		return sent.messages

	def test_it_sends_the_quarters_and_strikes_to_its_output(self):
		[(route, msg)] = self.run_at(at(7))
		self.assertEqual(route, "indicator")
		self.assertIsInstance(msg, OutputCue)
		self.assertEqual((msg.output, msg.steps, msg.why), ("Speaker", (*WESTMINSTER_HOUR, ("bell", 7)), "the clock at 07:00"))

	def test_its_night_silence_keeps_it_still_across_midnight(self):
		self.assertEqual(self.run_at(at(23), silentFrom=22, silentTo=7), [])
		self.assertEqual(self.run_at(at(3, 30), silentFrom=22, silentTo=7), [])
		self.assertEqual(len(self.run_at(at(7), silentFrom=22, silentTo=7)), 1, "it chimes again at Silent To")

	def test_a_quarter_with_nothing_to_play_sends_nothing(self):
		self.assertEqual(self.run_at(at(7, 15), chimes="none"), [])

	def test_with_no_output_it_fails_and_says_why(self):
		with self.assertRaisesRegex(RuntimeError, "No output is chosen"):
			self.run_at(at(7), cueOutput=None)

class TestPlayingSteps(unittest.TestCase):
	def player(self, config: dict[str, Any]|None = None, hour: int = 12) -> tuple[Player, OnceRenderer, list[tuple[str, str]]]:
		renderer = OnceRenderer()
		told: list[tuple[str, str]] = []
		player = Player("Speaker", renderer, {}, config or {}, lambda: at(hour), lambda title, why: told.append((title, why)))
		player.STRIKE_SECONDS = 0.01
		player.start()
		self.addCleanup(player.close)
		return player, renderer, told

	def test_each_cue_plays_its_count_in_turn_and_is_said_once(self):
		player, renderer, told = self.player()
		player.play((("change-1", 1), ("bell", 3)), "the clock at 03:00")
		self.assertTrue(wait_until(lambda: len(renderer.played) == 4))
		self.assertEqual([cue for cue, _ in renderer.played], ["change-1", "bell", "bell", "bell"])
		self.assertEqual(told, [("Westminster change 1", "the clock at 03:00"), ("Bell ×3", "the clock at 03:00")])

	def test_the_quiet_hours_keep_it_still(self):
		player, renderer, told = self.player({ "quietFrom": 22, "quietTo": 7 }, hour=23)
		player.play((("bell", 11),), "the clock at 23:00")
		time.sleep(0.2)
		self.assertEqual((renderer.played, told), ([], []))

	def test_an_unknown_cue_is_left_out(self):
		player, renderer, _ = self.player()
		player.play((("gong", 1), ("off", 1), ("one", 0)), "a task")
		self.assertTrue(wait_until(lambda: len(renderer.played) == 1))
		self.assertEqual(renderer.played, [("one", None)], "a count below one plays once")

	def test_outputs_play_on_the_named_output_only(self):
		renderer = OnceRenderer()
		outputs = Outputs({ "audio": lambda row: renderer })
		outputs.open(lambda *args: None, { "outputs": [{ "name": "Speaker", "kind": "audio" }] })
		self.addCleanup(outputs.close)
		self.assertFalse(outputs.play("Chime", (("bell", 1),), "a task"))
		self.assertTrue(outputs.play("Speaker", (("bell", 1),), "a task"))
		self.assertTrue(wait_until(lambda: renderer.played == [("bell", None)]))

	def test_a_cue_for_an_output_that_is_not_open_is_said(self):
		router, sent = router_that_records()
		DeviceIO("DeviceIO", router)._output_cue(OutputCue(at(9), "Speaker", (("bell", 9),), "the clock at 09:00"))
		[(route, msg)] = sent.messages
		self.assertEqual(route, "telemetry")
		self.assertEqual(msg.values["message"], "The output Speaker is not open, so the clock at 09:00 played nothing: add it in the GPIO settings, with its hardware connected.")

class TestATimerTasksCue(unittest.TestCase):
	def cue_of(self, content: dict[str, Any]) -> list[tuple[str, Any]]:
		router, sent = router_that_records()
		TimerLayer("timer", router)._play_task_cue(SystemTimeOfDay(), task(content, "Dentist"))
		return sent.messages

	def test_a_task_with_an_output_and_a_cue_plays_it_once(self):
		[(route, msg)] = self.cue_of({ "dataSource": "calendar", "cueOutput": "Speaker", "cue": "bell" })
		self.assertEqual((route, msg.output, msg.steps, msg.why), ("indicator", "Speaker", (("bell", 1),), "the task 'Dentist'"))

	def test_a_task_without_both_plays_nothing(self):
		for content in ({ "dataSource": "calendar" }, { "cueOutput": None, "cue": None }, { "cueOutput": "Speaker", "cue": "off" }, { "cueOutput": "Speaker", "cue": "change-1" }):
			with self.subTest(content):
				self.assertEqual(self.cue_of(content), [])

class TestTheCueFields(unittest.TestCase):
	"""Every timer plugin that draws carries the same output cue fields, and their cues are ours."""
	def cue_part(self, plugin: dict) -> tuple[list[dict], dict]:
		schema = plugin["instanceSettings"]["schema"]
		props = [p for p in schema["properties"] if p["name"] in ("cueHeader", "cueOutput", "cue")]
		return props, { name: schema["lookups"][name] for name in ("outputs", "cues") }

	def test_every_timer_plugin_that_draws_has_them_alike(self):
		drawing = [p for p in PLUGINS.values() if { "layer-priority", "layer-overlay" } & set(p["features"])]
		self.assertEqual({ p["id"] for p in drawing }, { "priority-update", "overlay" })
		first = self.cue_part(drawing[0])
		for plugin in drawing[1:]:
			self.assertEqual(self.cue_part(plugin), first, plugin["id"])
		self.assertEqual([p["name"] for p in first[0]], ["cueHeader", "cueOutput", "cue"], "the last section of the form")

	def test_the_cues_offered_are_every_cue_but_off_the_bell_first(self):
		_, lookups = self.cue_part(PLUGINS["overlay"])
		values = [item["value"] for item in lookups["cues"]["items"]]
		self.assertEqual(values[0], "bell")
		self.assertEqual(set(values), set(CUES) - { "off" })
		self.assertEqual({ item["value"]: item["name"] for item in lookups["cues"]["items"] }, { cue: CUES[cue].title for cue in values })

	def test_the_clock_chimes_output_is_the_same_lookup(self):
		_, lookups = self.cue_part(PLUGINS["overlay"])
		self.assertEqual(PLUGINS["clock-chime"]["instanceSettings"]["schema"]["lookups"], { "outputs": lookups["outputs"] })

if __name__ == "__main__":
	unittest.main()
