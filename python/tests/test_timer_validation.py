"""A timer task in a schedule file edited by hand or seeded is checked as the write routes check it (#211): a bad one is skipped and reported, the others run."""
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from ..model.schedule import TimerTaskItem, TimerTaskTask, TimerTasks
from ..task.message_router import MessageRouter, Route
from ..task.messages import ReloadSchedules, Telemetry
from ..task.timer_layer import TimerLayer
from .test_config_broadcast import FakeManager, playlist_entry
from .utils import ConstantTimeOfDay, MessageCollectSink, temp_configuration_manager

NOW = datetime(2024, 1, 1, 8, 0, tzinfo=ZoneInfo("America/New_York"))
GOOD_TRIGGER: Any = { "on_startup": False, "day": { "type": "dayofweek", "days": [0] }, "time": { "type": "specific", "hour": 9, "minute": 0 } }
GOOD: Any = { "dataSource": "clock", "face": "brass", "slideMinutes": 1 }

def entry(*items: TimerTaskItem) -> Any:
	return { "info": TimerTasks("d", "D", list(items)), "name": "d.json", "path": "d.json", "type": "x" }

def task(id: str, content: Any = None, trigger: Any = None, plugin: str = "priority-update", enabled: bool = True, title: str|None = None) -> TimerTaskItem:
	return TimerTaskItem(id, title or f"Task {id}", enabled, TimerTaskTask(plugin, GOOD if content is None else content), GOOD_TRIGGER if trigger is None else trigger)

class TimerValidationCase(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		router = MessageRouter()
		self.telemetry = MessageCollectSink()
		router.addRoute(Route("telemetry", [self.telemetry]))
		self.layer = TimerLayer("t", router)
		self.layer.timebase = ConstantTimeOfDay(NOW)
		self.layer.cm = self.cm
		self.layer.plugin_info = self.cm.enum_plugins()
		self.layer.state = "waiting"
		self.layer.accept = lambda m: None  # type: ignore
		self.layer._layer_stop = lambda: None  # type: ignore

	def messages(self) -> list[str]:
		return [str(m.values.get("message")) for m in self.telemetry.messages if isinstance(m, Telemetry)]

class TestCheckTasks(TimerValidationCase):
	def check(self, *items: TimerTaskItem) -> dict[str, str]:
		return self.layer._check_tasks([entry(*items)])

	def test_a_good_task_is_fine(self):
		self.assertEqual(self.check(task("a")), {})

	def test_a_trigger_that_cannot_be_evaluated(self):
		bad = self.check(task("a", trigger={ "day": { "type": "dayofweek", "days": [9] }, "time": GOOD_TRIGGER["time"] }))
		self.assertEqual(list(bad), ["a"])
		self.assertTrue(bad["a"].startswith("trigger: "))

	def test_settings_out_of_range_or_missing(self):
		self.assertIn("slideMinutes", self.check(task("a", content={ **GOOD, "slideMinutes": 0 }))["a"])
		self.assertIn("dataSource", self.check(task("b", content={ **GOOD, "dataSource": None }))["b"])

	def test_a_data_source_the_plugin_cannot_use(self):
		# Slide Show's sources are background and foreground; Priority Update (priority-update) asks for layer-priority
		self.assertIn("dataSource", self.check(task("a", content={ **GOOD, "dataSource": "rss" }))["a"])

	def test_a_plugin_that_is_not_there_is_left_for_its_error_page(self):
		self.assertEqual(self.check(task("a", plugin="no-such-plugin")), {})

	def test_a_disabled_task_is_not_checked(self):
		self.assertEqual(self.check(task("a", content={ **GOOD, "slideMinutes": 0 }, enabled=False)), {})

	def test_the_message_never_holds_a_stored_value(self):
		bad = self.check(task("a", content={ **GOOD, "slideMinutes": "hunter2" }))
		self.assertNotIn("hunter2", bad["a"])

class TestSkipAndReport(TimerValidationCase):
	def reload(self, *items: TimerTaskItem) -> None:
		cm: Any = MagicMock(wraps=self.cm)
		cm.schedule_manager.return_value = FakeManager([entry(*items)], [playlist_entry("x")])
		self.layer.cm = cm
		self.layer.tasks = []
		self.layer._reload_schedules(ReloadSchedules(NOW))

	def test_a_bad_task_is_skipped_reported_once_and_the_others_stay(self):
		with self.assertLogs("python.task.timer_layer", "WARNING"):
			self.reload(task("a"), task("b", content={ **GOOD, "slideMinutes": 0 }, title="Broken"))
		self.assertEqual([t.id for t in self.layer._get_enabled_tasks(self.layer.tasks)], ["a"])
		said = [m for m in self.messages() if "Broken" in m]
		self.assertEqual(len(said), 1)
		self.assertIn("skipped", said[0])
		self.assertTrue(any(m.values.get("kind") == "task-failed" for m in self.telemetry.messages if isinstance(m, Telemetry)))

	def test_a_bad_task_does_not_stop_the_schedule_from_loading(self):
		with self.assertLogs("python.task.timer_layer", "WARNING"):
			self.reload(task("b", trigger={ "day": 5, "time": 5 }))
		self.assertEqual(self.layer.state, "loaded")
		self.assertEqual(self.layer._get_enabled_tasks(self.layer.tasks), [])

	def test_the_same_schedule_again_says_nothing_more(self):
		with self.assertLogs("python.task.timer_layer", "WARNING"):
			self.reload(task("b", content={ **GOOD, "slideMinutes": 0 }))
		before = len(self.messages())
		same = entry(task("b", content={ **GOOD, "slideMinutes": 0 }))
		cm: Any = MagicMock(wraps=self.cm)
		cm.schedule_manager.return_value = FakeManager([same], [playlist_entry("x")])
		self.layer.cm = cm
		self.layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual(len(self.messages()), before)

if __name__ == "__main__":
	unittest.main()
