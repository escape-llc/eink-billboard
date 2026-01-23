from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from threading import Event
import unittest

from python.model.service_container import ServiceContainer

from .test_plugin import RecordingTask
from ..datasources.data_source import DataSourceManager
from ..model.schedule import Playlist, PlaylistSchedule, PlaylistScheduleData, TimerTaskItem, TimerTaskTask, TimerTasks
from ..plugins.plugin_base import BasicExecutionContext2, PluginProtocol, TrackType
from ..task.display import DisplaySettings
from ..task.timer import TimerService
from ..task.messages import BasicMessage, ConfigureEvent, ConfigureOptions, MessageSink, QuitMessage, Telemetry
from ..task.playlist_layer import PlaylistLayer, StartPlayback
from ..task.message_router import MessageRouter, Route
from ..task.future_source import FutureSource
from ..task.timer_layer import TimerLayer
from .utils import create_configuration_manager, save_images

class TestPlugin(PluginProtocol):
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
	def start(self, context: BasicExecutionContext2, track: TrackType):
		self.started = True
		self.start_args = (track, context)
	def receive(self, context: BasicExecutionContext2, track: TrackType, msg: BasicMessage):
		self.received.append(msg)
	# PlaylistLayer expects plugin to expose a `start(track, context)` method

class NullMessageSink(MessageSink):
	def accept(self, msg: BasicMessage):
		pass
class MessageTriggerSink(MessageSink):
	def __init__(self, trigger: Callable[[BasicMessage], bool]):
		self.trigger = trigger
		self.captured:BasicMessage = None
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
		cm = create_configuration_manager()
		ctr = ServiceContainer()
		options = ConfigureOptions(cm, isp=ctr)
		configure = ConfigureEvent("configure", options, datetime.now())
		layer = PlaylistLayer("testlayer", router)
		dev = DisplaySettings("none", 800, 480)
		display.start()
		layer.start()
		layer.accept(dev)
		layer.accept(configure)
		# wait until the trigger condition is met
		completed = tsink.stopped.wait(timeout=20)
		layer.accept(QuitMessage(datetime.now()))
		layer.join(timeout=2)
		display.accept(QuitMessage(datetime.now()))
		display.join()
		save_images(display, "playlist_layer_simulation")
		self.assertTrue(completed, "PlaylistLayer simulation timed out before reaching trigger condition.")
		self.assertIsNotNone(tsink.captured)
		telemetry:Telemetry = tsink.captured
		self.assertNotEqual(telemetry.values.get("state", None), "error", f"PlaylistLayer encountered error: {telemetry.values.get('message', '')}")

class TimerLayerSimulation(unittest.TestCase):
	def test_simulate_timer_layer(self):
		display = RecordingTask("FakeDisplay")
		tsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and (msg.values.get("state", None) == "error" or msg.values.get("schedule_ts", None) is not None))
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		router.addRoute(Route("telemetry", [tsink]))
		cm = create_configuration_manager()
		ctr = ServiceContainer()
		options = ConfigureOptions(cm, ctr)
		configure = ConfigureEvent("configure", options, datetime.now())
		layer = TimerLayer("timerlayer", router)
		dev = DisplaySettings("none", 800, 480)
		display.start()
		layer.start()
		layer.accept(dev)
		layer.accept(configure)
		# wait until the trigger condition is met
		completed = tsink.stopped.wait(timeout=20000)
		layer.accept(QuitMessage(datetime.now()))
		layer.join(timeout=2)
		display.accept(QuitMessage(datetime.now()))
		display.join()
		save_images(display, "timer_layer_simulation")
		self.assertTrue(completed, "TimerLayer simulation timed out before reaching trigger condition.")
		self.assertIsNotNone(tsink.captured)
		telemetry:Telemetry = tsink.captured
		self.assertNotEqual(telemetry.values.get("state", None), "error", f"TimerLayer encountered error: {telemetry.values.get('message', '')}")

class PlaylistLayerTests(unittest.TestCase):
	def setUp(self):
		self.router = MessageRouter()
		self.layer = PlaylistLayer("playlistlayer", self.router)
		self.layer.cm = create_configuration_manager()
		self.layer.datasources = DataSourceManager(None, {})
		self.layer.timer = TimerService(None)
		sink = NullMessageSink()
		self.layer.future_source = FutureSource("playlist_layer_test", sink, ThreadPoolExecutor())

	def test_start_playback_success(self):
		# Prepare a plugin and a playlist with one track that references it
#		plugin = TestPlugin("p1", "TestPlugin")
		# plugin_map keys are plugin ids used in PlaylistSchedule.plugin_name
		test_file_path = os.path.abspath(__file__)
		folder = os.path.dirname(test_file_path)
		self.layer.plugin_info = [
			{
				"info": {
					"id": "p1", "name": "Test Plugin",
					"module":"python.tests.test_layers",
					"class":"TestPlugin",
					"file":"test_layers.py"
				},
				"path": folder
			}
		]

		# Create a playlist with a single PlaylistSchedule track
		track = PlaylistSchedule("p1", "t1", "Title", PlaylistScheduleData({}))
		playlist = Playlist("pl1", "Main", items=[track])
		self.layer.playlists = [{"info": playlist}]
		self.layer.state = 'loaded'

		# Trigger playback
		startts = datetime.now()
		self.layer._start_playback(StartPlayback(startts))
		self.layer.timer.shutdown()
		self.layer.future_source.shutdown()
		self.assertEqual(self.layer.state, 'playing')
		self.assertIsNotNone(self.layer.playlist_state)
		self.assertIsNotNone(self.layer.active_context)
		self.assertIsNotNone(self.layer.active_plugin)
		self.assertTrue(self.layer.active_plugin.started)
		# verify indices set
		self.assertEqual(self.layer.playlist_state['current_playlist_index'], 0)
		self.assertEqual(self.layer.playlist_state['current_track_index'], 0)

	def test_start_playback_no_playlists(self):
		self.layer.playlists = []
		self.layer.plugin_info = []
		self.layer.state = 'loaded'

		# Should not raise, but should not start playback
		self.layer._start_playback(StartPlayback())
		self.assertNotEqual(self.layer.state, 'playing')
		self.assertIsNone(self.layer.playlist_state)

	def test_ctor_invalid_router(self):
		with self.assertRaises(ValueError):
			PlaylistLayer("bad", None)

	def test_start_playback_missing_plugin(self):
		# Playlist refers to a plugin that is not in plugin_map
		track = PlaylistSchedule("missing", "t2", "Title2", PlaylistScheduleData({}))
		playlist = Playlist("pl2", "Main2", items=[track])
		self.layer.playlists = [{"info": playlist}]
		self.layer.plugin_info = []
		self.layer.state = 'loaded'

		# Trigger playback; plugin missing should prevent start
		self.layer._start_playback(StartPlayback())
		self.assertNotEqual(self.layer.state, 'playing')
		self.assertIsNone(self.layer.playlist_state)

class TimerLayerTests(unittest.TestCase):
	def setUp(self):
		self.router = MessageRouter()
		self.layer = TimerLayer("timerlayer", self.router)
		self.layer.cm = create_configuration_manager()
		self.layer.datasources = DataSourceManager(None, {})
		self.layer.timer = TimerService(None)
		sink = NullMessageSink()
		self.layer.future_source = FutureSource("timer_layer_test", sink, ThreadPoolExecutor())
	def test_start_schedule_success(self):
		# Prepare a plugin_info and a playlist with one track that references it
		# plugin_map keys are plugin ids used in PlaylistSchedule.plugin_name
		test_file_path = os.path.abspath(__file__)
		folder = os.path.dirname(test_file_path)
		self.layer.plugin_info = [
			# reference the plugin defined in this file
			{
				"info": {
					"id": "p1", "name": "Test Plugin",
					"module":"python.tests.test_layers",
					"class":"TestPlugin",
					"file":"test_layers.py"
				},
				"path": folder
			}
		]

		# Create a playlist with a single TimedSchedule track
		task = TimerTaskTask("p1", "t1", 1, {})
		trigger = {
			"day": {
				"type": "dayofweek",
				"days": [0,1,2,3,4,5,6]
			},
			"time": {
				"type": "hourly",
				"minutes": list(range(0,60))
			}
		}
		item = TimerTaskItem("p1", "t1", True, "Title", task, trigger)
		tasks = TimerTasks("pl1", "Main", items=[item])
		self.layer.tasks = [{"info": tasks}]
		self.layer.state = 'loaded'

		# Trigger playback
		startts = datetime.now()
		self.layer._start_playback(StartPlayback(startts))
		self.layer.timer.shutdown()
		self.layer.future_source.shutdown()
		self.assertEqual(self.layer.state, 'waiting')
		self.assertIsNotNone(self.layer.playlist_state)
		self.assertIsNotNone(self.layer.active_context)
		self.assertIsNotNone(self.layer.active_plugin)
		self.assertTrue(isinstance(self.layer.active_plugin, TestPlugin))
		self.assertFalse(self.layer.active_plugin.started)
		# verify indices set
		self.assertIsNotNone(self.layer.playlist_state['current_playlist'])
		self.assertEqual(self.layer.playlist_state['current_track_index'], 0)
		self.assertIsNotNone(self.layer.playlist_state['schedule_ts'])

	def test_ctor_invalid_router(self):
		with self.assertRaises(ValueError):
			TimerLayer("bad", None)

if __name__ == '__main__':
	unittest.main()

