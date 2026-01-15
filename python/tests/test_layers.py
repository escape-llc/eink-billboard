from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from threading import Event
import time
import unittest

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
	def receive(self, context: BasicExecutionContext2, track: TrackType, msg: BasicMessage):
		self.received.append(msg)
	# PlaylistLayer expects plugin to expose a `start(track, context)` method
	def start(self, track, context):
		self.started = True
		self.start_args = (track, context)

class NullMessageSink(MessageSink):
	def send(self, msg: BasicMessage):
		pass
class MessageTriggerSink(MessageSink):
	def __init__(self, trigger: Callable[[BasicMessage], bool]):
		self.trigger = trigger
		self.stopped = Event()
	def send(self, msg: BasicMessage):
		if self.trigger(msg):
			self.stopped.set()

class PlaylistLayerSimulation(unittest.TestCase):
	def test_simulate_playlist_layer(self):
		display = RecordingTask("FakeDisplay")
		tsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and msg.values.get("current_track_index", None) == 3)
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		router.addRoute(Route("telemetry", [tsink]))
		cm = create_configuration_manager()
		options = ConfigureOptions(cm)
		configure = ConfigureEvent("configure", options)
		layer = PlaylistLayer("testlayer", router)
		dev = DisplaySettings("none", 800, 480)
		display.start()
		layer.start()
		layer.send(dev)
		layer.send(configure)
		# wait until the trigger condition is met
		completed = tsink.stopped.wait(timeout=20)
		layer.send(QuitMessage())
		layer.join(timeout=2)
		display.send(QuitMessage())
		display.join()
		save_images(display, "playlist_layer_simulation")
		self.assertTrue(completed, "PlaylistLayer simulation timed out before reaching trigger condition.")

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
		self.assertEqual(self.layer.state, 'playing')
		self.assertIsNotNone(self.layer.playlist_state)
		self.assertTrue(self.layer.active_plugin.started)
		# verify indices set
		self.assertEqual(self.layer.playlist_state['current_schedule_index'], 0)
		self.assertEqual(self.layer.playlist_state['current_track_index'], 0)
		self.assertIsNotNone(self.layer.playlist_state['schedule_ts'])

if __name__ == '__main__':
	unittest.main()

