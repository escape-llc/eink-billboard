"""The configuration-change broadcast: watcher event, application, every task, and the layers' reload of the schedules."""
import os
import threading
import time
import unittest
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from ..model.configuration_manager import ConfigurationManager
from ..model.schedule import TimerTaskItem, TimerTaskTask, TimerTasks, Playlist, PlaylistSchedule, PlaylistScheduleData
from ..task.application import Application
from ..task.coalescer import Coalescer
from ..task.fanout_sink import FanoutSink
from ..task.messages import BasicMessage, ConfigurationChanged, ConfigurationWatcherEvent, ReloadSchedules, Telemetry
from ..task.message_router import MessageRouter, Route
from ..task.playlist_layer import PlaylistLayer, StartPlayback
from ..task.timer_layer import TimerLayer
from .utils import ConstantTimeOfDay, MessageCollectSink

NY = ZoneInfo("America/New_York")
NOW = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
TRIGGER: Any = { "on_startup": False, "day": { "type": "dayofweek", "days": [0] }, "time": { "type": "specific", "hour": 9, "minute": 0 } }

def timer_entry(title: str) -> Any:
	item = TimerTaskItem("i", title, True, TimerTaskTask("p", {}), TRIGGER)
	return { "info": TimerTasks("d", "D", [item]), "name": "d.json", "path": "d.json", "type": "x" }

def playlist_entry(title: str) -> Any:
	return { "info": Playlist("p", "P", [PlaylistSchedule("slide-show", "t", title, PlaylistScheduleData({}))]), "name": "p.json", "path": "p.json", "type": "x" }

class FakeManager:
	def __init__(self, tasks, playlists, error: Exception|None = None):
		self.result = { "tasks": tasks, "playlists": playlists }
		self.error = error
	def load(self):
		if self.error is not None:
			raise self.error
		return self.result
	def validate(self, info):
		pass

class TestArea(unittest.TestCase):
	def test_area_of_a_path(self):
		cm = ConfigurationManager(storage_path=os.path.join(os.sep, "tmp", "store"))
		root = cm.STORAGE_PATH
		self.assertEqual(cm.area_of(os.path.join(root, "schedules", "a.json")), "schedules")
		self.assertEqual(cm.area_of(os.path.join(root, "settings", "display-settings.json")), "settings")
		self.assertEqual(cm.area_of(os.path.join(root, "schemas", "display.json")), "schemas")
		self.assertEqual(cm.area_of(os.path.join(root, "plugins", "p", "settings.json")), "plugins")
		self.assertEqual(cm.area_of(os.path.join(root, "datasources", "d", "settings.json")), "datasources")
		self.assertEqual(cm.area_of(os.path.join(root, "notes.txt")), "other")
		self.assertEqual(cm.area_of(os.path.join(os.sep, "elsewhere", "schedules", "a.json")), "other")
		self.assertEqual(cm.area_of(os.path.join(root, "schedules", "a.json").encode()), "schedules")

class TestFanoutAndCoalescer(unittest.TestCase):
	def test_fanout_keeps_order_and_isolates_failures(self):
		heard: list[str] = []
		class Sink:
			def __init__(self, name, fail=False): self.name, self.fail = name, fail
			def accept(self, msg):
				heard.append(self.name)
				if self.fail: raise RuntimeError("boom")
		fan = FanoutSink(cast(Any, Sink("first", fail=True)))
		fan.add(cast(Any, Sink("second")))
		with self.assertLogs("python.task.fanout_sink", "ERROR"):
			fan.accept(BasicMessage(NOW))
		self.assertEqual(heard, ["first", "second"])

	def test_a_burst_is_one_call_after_the_last_trigger(self):
		fired = threading.Event()
		count = []
		def fire():
			count.append(1)
			fired.set()
		c = Coalescer(0.15, fire)
		for _ in range(5):
			c.trigger()
			time.sleep(0.03)
		self.assertTrue(fired.wait(1))
		time.sleep(0.3)
		self.assertEqual(len(count), 1)

	def test_cancel_prevents_the_call(self):
		fired = threading.Event()
		c = Coalescer(0.05, fired.set)
		c.trigger()
		c.cancel()
		self.assertFalse(fired.wait(0.3))

class TestApplication(unittest.TestCase):
	def test_a_watcher_event_is_broadcast_with_its_area(self):
		app = Application("app")
		app.router = MagicMock()
		app.cm = MagicMock()
		app.cm.area_of.return_value = "schedules"
		app._configuration_watcher_event(ConfigurationWatcherEvent(NOW, "modified", "/s/schedules/a.json"))
		route, msg = app.router.send.call_args.args
		self.assertEqual(route, "configuration")
		self.assertEqual((msg.area, msg.type, msg.path), ("schedules", "modified", "/s/schedules/a.json"))

	def test_the_watcher_event_reaches_the_handler_through_the_task(self):
		app = Application("app")
		app.router = MagicMock()
		app.cm = MagicMock()
		app.cm.area_of.return_value = "settings"
		app.start()
		try:
			app.accept(ConfigurationWatcherEvent(NOW, "modified", "/s/settings/x.json"))
			deadline = time.time() + 2
			while not app.router.send.called and time.time() < deadline:
				time.sleep(0.01)
			self.assertTrue(app.router.send.called)
		finally:
			from ..task.messages import QuitMessage
			app.accept(QuitMessage(NOW))
			app.join(timeout=3)

class TestTimerLayerReload(unittest.TestCase):
	def _layer(self, manager: FakeManager):
		router = MessageRouter()
		telemetry = MessageCollectSink()
		router.addRoute(Route("telemetry", [telemetry]))
		layer = TimerLayer("t", router)
		layer.timebase = ConstantTimeOfDay(NOW)
		cm_mock: Any = MagicMock()
		cm_mock.schedule_manager.return_value = manager
		layer.cm = cm_mock
		layer.state = "waiting"
		layer.tasks = [timer_entry("old")]
		accepted: list[BasicMessage] = []
		layer.accept = accepted.append  # type: ignore
		stops: list[int] = []
		layer._layer_stop = lambda: stops.append(1)  # type: ignore
		return layer, accepted, stops, telemetry

	def test_only_schedule_changes_trigger_a_reload(self):
		layer, *_ = self._layer(FakeManager([], []))
		triggered: list[int] = []
		layer._reload = cast(Any, MagicMock(trigger=lambda: triggered.append(1)))
		for area in ("settings", "plugins", "other", "datasources"):
			layer._configuration_changed(ConfigurationChanged(NOW, area, "modified", "p"))
		self.assertEqual(triggered, [])
		layer._configuration_changed(ConfigurationChanged(NOW, "schedules", "modified", "p"))
		self.assertEqual(triggered, [1])

	def test_changed_tasks_stop_the_running_plan_and_start_the_new_one(self):
		new = [timer_entry("new")]
		layer, accepted, stops, _ = self._layer(FakeManager(new, [playlist_entry("x")]))
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual(stops, [1])
		self.assertIs(layer.tasks, new)
		self.assertEqual(layer.state, "loaded")
		self.assertEqual([type(m) for m in accepted], [StartPlayback])

	def test_the_same_tasks_do_nothing(self):
		layer, accepted, stops, _ = self._layer(FakeManager([timer_entry("old")], [playlist_entry("x")]))
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((stops, accepted), ([], []))

	def test_no_timer_documents_left_is_a_valid_change(self):
		layer, accepted, stops, _ = self._layer(FakeManager([], [playlist_entry("x")]))
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((layer.tasks, stops, len(accepted)), ([], [1], 1))

	def test_schedules_that_do_not_load_keep_the_ones_in_use(self):
		layer, accepted, stops, telemetry = self._layer(FakeManager([], [], error=ValueError("broken file")))
		old = layer.tasks
		with self.assertLogs("python.task.timer_layer", "WARNING"):
			layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((layer.tasks is old, stops, accepted), (True, [], []))
		self.assertTrue(any(isinstance(m, Telemetry) and m.values.get("state") == "error" for m in telemetry.messages))

	def test_nothing_happens_before_the_layer_is_configured(self):
		layer, accepted, stops, _ = self._layer(FakeManager([timer_entry("new")], []))
		layer.state = "uninitialized"
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((stops, accepted), ([], []))

class TestPlaylistLayerReload(unittest.TestCase):
	def _layer(self, manager: FakeManager):
		router = MessageRouter()
		router.addRoute(Route("telemetry", [MessageCollectSink()]))
		layer = PlaylistLayer("p", router)
		layer.timebase = ConstantTimeOfDay(NOW)
		cm_mock: Any = MagicMock()
		cm_mock.schedule_manager.return_value = manager
		layer.cm = cm_mock
		layer.state = "playing"
		layer.playlists = [playlist_entry("old")]
		layer._backoff = 16.0
		accepted: list[BasicMessage] = []
		layer.accept = accepted.append  # type: ignore
		stops: list[int] = []
		layer._task_stop = lambda: stops.append(1)  # type: ignore
		return layer, accepted, stops

	def test_changed_playlists_start_again_from_the_top(self):
		new = [playlist_entry("new")]
		layer, accepted, stops = self._layer(FakeManager([], new))
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((stops, layer.playlists is new, layer._backoff, layer.state), ([1], True, 0.0, "loaded"))
		self.assertEqual([type(m) for m in accepted], [StartPlayback])

	def test_the_same_playlists_and_timer_only_changes_do_nothing(self):
		layer, accepted, stops = self._layer(FakeManager([timer_entry("anything")], [playlist_entry("old")]))
		layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((stops, accepted), ([], []))

	def test_playlists_that_do_not_load_keep_the_ones_in_use(self):
		layer, accepted, stops = self._layer(FakeManager([], [], error=ValueError("No playlists found in schedule")))
		old = layer.playlists
		with self.assertLogs("python.task.playlist_layer", "ERROR"):
			layer._reload_schedules(ReloadSchedules(NOW))
		self.assertEqual((layer.playlists is old, stops, accepted), (True, [], []))

if __name__ == "__main__":
	unittest.main()
