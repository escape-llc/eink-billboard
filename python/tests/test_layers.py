from collections.abc import Callable
from datetime import datetime
import os
from threading import Event
from typing import cast
import unittest

from python.model.schedule_loader import ScheduleLoaderDict

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import CollectInfoDict
from ..model.schedule import Playlist, PlaylistSchedule, PlaylistScheduleData, TimerTaskItem, TimerTaskTask, TimerTasks, TriggerDict
from ..model.service_container import ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..model.schedule_manager import SCHEMA_PLAYLIST, SCHEMA_TASKS
from ..plugins.plugin_base import PluginAsync, PluginExecutionContext, TrackType
from ..task.display_messages import DisplaySettings
from ..task.timer import IProvideTimer
from ..task.messages import BasicMessage, QuitMessage, Telemetry
from ..task.protocols import MessageSink
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.playlist_layer import PlaylistLayer, StartPlayback
from ..task.message_router import MessageRouter, Route
from ..task.timer_layer import TimerLayer
from ..task.protocols import IProvideTimer, IRequireShutdown, MessageSink
from .utils import RecordingTask, ScaledTimeOfDay, ScaledTimerThreadService, create_configuration_manager, save_images

class TestPlugin(PluginAsync):
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.started = False
		self.start_args = None
		self.received: list[BasicMessage] = []
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	def start(self, context: PluginExecutionContext, track: TrackType):
		self.started = True
		self.start_args = (track, context)
	def receive(self, context: PluginExecutionContext, track: TrackType, msg: BasicMessage):
		self.received.append(msg)
	# PlaylistLayer expects plugin to expose a `start(track, context)` method

class NullMessageSink(MessageSink):
	def accept(self, msg: BasicMessage):
		pass
class MessageTriggerSink(MessageSink):
	def __init__(self, trigger: Callable[[BasicMessage], bool]):
		self.trigger = trigger
		self.captured:BasicMessage|None = None
		self.stopped = Event()
	def accept(self, msg: BasicMessage):
		if self.trigger(msg):
			self.captured = msg
			self.stopped.set()

class PlaylistLayerSimulation(unittest.TestCase):
	def test_simulate_playlist_layer(self):
		display = RecordingTask("FakeDisplay")
		tsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and (msg.values.get("state", None) == "error" or msg.values.get("current_track_index", None) == 3))
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		router.addRoute(Route("telemetry", [tsink]))
		time_base = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		timer = ScaledTimerThreadService(time_base, 60)
		cm = create_configuration_manager()
		ctr = ServiceContainer()
		ctr.add_service(TimeOfDay, time_base)
		ctr.add_service(IProvideTimer, timer)
		options = ConfigureOptions(cm, isp=ctr)
		evtime = time_base.current_time()
		configure = ConfigureEvent(evtime, options, "configure", None)
		layer = PlaylistLayer("testlayer", router)
		dev = DisplaySettings(evtime, "none", 800, 480, [])
		display.start()
		layer.start()
		layer.accept(dev)
		layer.accept(configure)
		# wait until the trigger condition is met
		completed = tsink.stopped.wait(timeout=90)
		evtime = time_base.current_time()
		layer.accept(QuitMessage(evtime))
		layer.join(timeout=2)
		display.accept(QuitMessage(evtime))
		display.join()
		save_images(display, "playlist_layer_simulation")
		self.assertTrue(completed, "PlaylistLayer simulation timed out before reaching trigger condition.")
		self.assertIsNotNone(tsink.captured)
		self.assertIsInstance(tsink.captured, Telemetry)
		telemetry:Telemetry = cast(Telemetry, tsink.captured)
		self.assertNotEqual(telemetry.values.get("state", None), "error", f"PlaylistLayer encountered error: {telemetry.values.get('message', '')}")

class TimerLayerSimulation(unittest.TestCase):
	def test_simulate_timer_layer(self):
		display = RecordingTask("FakeDisplay")
		tsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and (msg.values.get("state", None) == "error" or (msg.values.get("state", None) == "playing" and msg.values.get("schedule_ts", None) is not None)))
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		router.addRoute(Route("telemetry", [tsink]))
		cm = create_configuration_manager()
		time_base = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		timer = ScaledTimerThreadService(time_base, 60)
		ctr = ServiceContainer()
		ctr.add_service(TimeOfDay, time_base)
		ctr.add_service(IProvideTimer, timer)
		options = ConfigureOptions(cm, ctr)
		evtime = time_base.current_time()
		configure = ConfigureEvent(evtime, options, "configure", None)
		layer = TimerLayer("timerlayer", router)
		dev = DisplaySettings(evtime, "none", 800, 480, [])
		display.start()
		layer.start()
		layer.accept(dev)
		layer.accept(configure)
		# wait until the trigger condition is met
		completed = tsink.stopped.wait(timeout=20)
		evtime = time_base.current_time()
		layer.accept(QuitMessage(evtime))
		layer.join(timeout=2)
		display.accept(QuitMessage(evtime))
		display.join()
		save_images(display, "timer_layer_simulation")
		self.assertTrue(completed, "TimerLayer simulation timed out before reaching trigger condition.")
		self.assertIsNotNone(tsink.captured)
		self.assertIsInstance(tsink.captured, Telemetry)
		telemetry:Telemetry = cast(Telemetry, tsink.captured)
		self.assertNotEqual(telemetry.values.get("state", None), "error", f"TimerLayer encountered error: {telemetry.values.get('message', '')}")

class PlaylistLayerTests(unittest.TestCase):
	def setUp(self):
		self.router = MessageRouter()
		self.layer = PlaylistLayer("playlistlayer", self.router)
		self.layer.cm = create_configuration_manager()
		self.layer.datasources = DataSourceManager({})
		self.layer.timebase = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		self.layer.timer = ScaledTimerThreadService(self.layer.timebase, 60)
		sink = NullMessageSink()

	def test_start_playback_success(self):
		# Prepare a plugin and a playlist with one track that references it
#		plugin = TestPlugin("p1", "TestPlugin")
		# plugin_map keys are plugin ids used in PlaylistSchedule.plugin_name
		test_file_path = os.path.abspath(__file__)
		folder = os.path.dirname(test_file_path)
		self.layer.plugin_info = cast(list[CollectInfoDict], [
			{
				"info": {
					"id": "p1", "name": "Test Plugin",
					"module":"python.tests.test_layers",
					"class":"TestPlugin",
					"file":"test_layers.py"
				},
				"name": "Test Plugin",
				"path": folder,
				"type": SCHEMA_PLAYLIST
			}
		])

		# Create a playlist with a single PlaylistSchedule track
		track = PlaylistSchedule("p1", "t1", "Title", PlaylistScheduleData({}))
		playlist = Playlist("pl1", "Main", items=[track])
		self.layer.playlists = cast(list[ScheduleLoaderDict], [{"info": playlist, "name": "Test Playlist", "path": "/some/bogus/path", "type": SCHEMA_PLAYLIST}])
		self.layer.state = 'loaded'

		# Trigger playback
		startts = datetime.now()
		self.layer._start_playback(StartPlayback(startts))
		self.assertEqual(self.layer.state, 'loaded')

	def test_start_playback_no_playlists(self):
		self.layer.playlists = []
		self.layer.plugin_info = []
		self.layer.state = 'loaded'

		# Should not raise, but should not start playback
		self.layer._start_playback(StartPlayback(datetime.now()))
		self.assertEqual(self.layer.state, 'loaded')

	def test_ctor_invalid_router(self):
		with self.assertRaises(ValueError):
			PlaylistLayer("bad", cast(MessageRouter, None))

	def test_start_playback_missing_plugin(self):
		# Playlist refers to a plugin that is not in plugin_map
		track = PlaylistSchedule("missing", "t2", "Title2", PlaylistScheduleData({}))
		playlist = Playlist("pl2", "Main2", items=[track])
		self.layer.playlists = cast(list[ScheduleLoaderDict], [{"info": playlist, "name": "Test Playlist", "path": "/some/bogus/path", "type": SCHEMA_PLAYLIST}])
		self.layer.plugin_info = []
		self.layer.state = 'loaded'

		# Trigger playback; plugin missing should prevent start
		self.layer._start_playback(StartPlayback(datetime.now()))
		self.assertNotEqual(self.layer.state, 'playing')

class TimerLayerTests(unittest.TestCase):
	def setUp(self):
		self.router = MessageRouter()
		self.layer = TimerLayer("timerlayer", self.router)
		self.layer.cm = create_configuration_manager()
		self.layer.datasources = DataSourceManager({})
		self.layer.timebase = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		self.layer.timer = ScaledTimerThreadService(self.layer.timebase, 60)
		sink = NullMessageSink()
	def test_start_schedule_success(self):
		# Prepare a plugin_info and a playlist with one track that references it
		# plugin_map keys are plugin ids used in PlaylistSchedule.plugin_name
		test_file_path = os.path.abspath(__file__)
		folder = os.path.dirname(test_file_path)
		self.layer.plugin_info = cast(list[CollectInfoDict], [
			# reference the plugin defined in this file
			{
				"info": {
					"id": "p1", "name": "Test Plugin",
					"module":"python.tests.test_layers",
					"class":"TestPlugin",
					"file":"test_layers.py"
				},
				"name": "Test Plugin",
				"path": folder,
				"type": SCHEMA_PLAYLIST
			}
		])

		# Create a playlist with a single track
		task = TimerTaskTask("p1", {})
		trigger = {
			"day": {
				"type": "dayofweek",
				"days": [0,1,2,3,4,5,6]
			},
			"time": {
				"type": "hourly",
				"hours": list(range(0,24)),
				"minutes": list(range(0,60))
			}
		}
		item = TimerTaskItem("p1", "Title", True, task, cast(TriggerDict, trigger))
		tasks = TimerTasks("pl1", "Main", items=[item])
		self.layer.tasks = [{"info": tasks, "name": "Test Tasks", "path": "/some/bogus/path", "type": SCHEMA_TASKS}]
		self.layer.state = 'loaded'

		# Trigger playback
		startts = datetime.now()
		self.layer._start_playback(StartPlayback(startts))
		self.assertEqual(self.layer.state, 'loaded')

	def test_ctor_invalid_router(self):
		with self.assertRaises(ValueError):
			TimerLayer("bad", cast(MessageRouter, None))

if __name__ == '__main__':
	unittest.main()

