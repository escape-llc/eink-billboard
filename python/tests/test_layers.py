from collections.abc import Callable
from unittest import mock
from PIL import Image
from datetime import datetime, timedelta, timezone
import os
from threading import Event
from typing import Any, cast
import unittest

from python.model.schedule_loader import ScheduleLoaderDict

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import CollectInfoDict
from ..model.schedule import Playlist, PlaylistSchedule, PlaylistScheduleData, TimerTaskItem, TimerTaskTask, TimerTasks, TriggerDict, SCHEMA_PLAYLIST, SCHEMA_TASKS
from ..model.service_container import ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..plugins.plugin_base import PermanentError, PluginAsync, PluginExecutionContext, TrackType
from ..task.display_messages import DisplaySettings
from ..task.timer import IProvideTimer
from ..task.messages import BasicMessage, QuitMessage, Telemetry
from ..task.protocols import MessageSink
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.playlist_layer import LayerFaulted, PlaylistLayer, RetryStruckOut, StartPlayback
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

class NewDeviceHasNothingScheduled(unittest.TestCase):
	"""A new device's storage has no playlist and no timer task (found on a Pi: both layers failed). The playlist layer says so on the panel; neither fails."""
	def test_both_layers_start_and_the_panel_says_nothing_is_scheduled(self):
		import tempfile
		from ..model.configuration_manager import ConfigurationManager
		from ..task.display_messages import DisplayImage
		with tempfile.TemporaryDirectory() as folder:
			cm = ConfigurationManager(storage_path=folder)
			cm.hard_reset()
			display = RecordingTask("FakeDisplay")
			errors: list[BasicMessage] = []
			shown = Event()
			router = MessageRouter()
			router.addRoute(Route("display", [display]))
			router.addRoute(Route("telemetry", [MessageTriggerSink(lambda m: isinstance(m, Telemetry) and m.values.get("state") == "error" and not errors.append(m))]))
			time_base = ScaledTimeOfDay(datetime.now().astimezone(), 60)
			ctr = ServiceContainer()
			ctr.add_service(TimeOfDay, time_base)
			ctr.add_service(IProvideTimer, ScaledTimerThreadService(time_base, 60))
			now = time_base.current_time()
			layers = [PlaylistLayer("playlist", router), TimerLayer("timer", router)]
			display.start()
			for layer in layers:
				layer.start()
				layer.accept(DisplaySettings(now, "none", 800, 480, []))
				layer.accept(ConfigureEvent(now, ConfigureOptions(cm, ctr), "configure", None))
			for _ in range(100):
				if any(isinstance(m, DisplayImage) and m.title == "Nothing to show" for m in display.msgs):
					break
				Event().wait(0.1)
			for layer in layers:
				layer.accept(QuitMessage(now))
				layer.join(timeout=2)
			display.accept(QuitMessage(now))
			display.join()
			self.assertTrue(any(isinstance(m, DisplayImage) and m.title == "Nothing to show" for m in display.msgs), "the panel was not told nothing is scheduled")
			self.assertEqual([], errors)

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

	def test_no_playlists_shows_a_page_that_says_so(self):
		from ..task.display_messages import DisplayImage
		self.layer.playlists = []
		self.layer.state = 'loaded'
		self.layer.router = mock.MagicMock()
		self.layer._start_playback(StartPlayback(datetime.now()))
		route, message = self.layer.router.send.call_args.args
		self.assertEqual(route, "display")
		self.assertIsInstance(message, DisplayImage)
		self.assertEqual((message.title, message.layer), ("Nothing to show", "override"))

	def test_a_failing_pass_holds_each_slot_instead_of_spinning(self):
		import asyncio, time
		class Boom:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				raise RuntimeError("boom")
		layer = self.layer
		layer.ERROR_SLOT_MINUTES = 0.2
		layer.MAX_STRIKES = 100  # this test is about the wait; the strikes have their own tests
		layer.router.send = lambda *a, **k: None  # type: ignore
		track = PlaylistSchedule("p1", "t1", "Title", PlaylistScheduleData({}))
		playlists = cast(list[ScheduleLoaderDict], [{"info": Playlist("pl1", "Main", items=[track]), "name": "x", "path": "/x", "type": SCHEMA_PLAYLIST}])
		layer._evaluate_plugin = lambda t: {"plugin": Boom("p1", "Plugin"), "track": t}  # type: ignore
		root = ServiceContainer()
		root.add_service(TimeOfDay, layer.timebase)
		with mock.patch("python.task.playlist_layer.render_error_image", return_value=Image.new("RGB", (8, 8))):
			start = time.monotonic()
			asyncio.run(layer._layer_task(root, playlists, Event()))
		# 0.2 minutes of model time at 60x is 0.2 s
		self.assertGreaterEqual(time.monotonic() - start, 0.15)

	def test_an_image_a_track_sends_says_which_track_made_it(self):
		import asyncio
		from ..task.display_messages import DisplayImage
		from ..task.message_router import MessageRouter, Route
		got: list = []
		class Catcher:
			def accept(self, msg): got.append(msg)
		class Draws:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				ctx.provider.required(MessageRouter).send("display", DisplayImage(ctx.timestamp, "Picture", Image.new("RGB", (8, 8))))
		layer = self.layer
		layer.router = MessageRouter()
		layer.router.addRoute(Route("display", [Catcher()]))
		track = PlaylistSchedule("p1", "t1", "Morning Joe", PlaylistScheduleData({}))
		playlists = cast(list[ScheduleLoaderDict], [{"info": Playlist("pl1", "Main", items=[track]), "name": "x", "path": "/x", "type": SCHEMA_PLAYLIST}])
		layer._evaluate_plugin = lambda t: {"plugin": Draws("p1", "Plugin"), "track": t}  # type: ignore
		root = ServiceContainer()
		root.add_service(TimeOfDay, layer.timebase)
		asyncio.run(layer._layer_task(root, playlists, Event()))
		self.assertEqual(len(got), 1)
		self.assertEqual(dict(got[0].origin), { "kind": "playlist", "title": "Morning Joe", "plugin": "p1", "name": "Main" })

	def _strike_setup(self, plugin_factory, track_count=1):
		"""A layer whose tracks all run `plugin_factory`'s plugin; returns (layer, playlists, services, calls)."""
		layer = self.layer
		layer.BACKOFF_INITIAL_SECONDS = 0.01
		layer.BACKOFF_MAX_SECONDS = 0.01
		layer.ERROR_SLOT_MINUTES = 0.0001
		self.sent: list = []
		layer.router.send = lambda route, msg: self.sent.append((route, msg))  # type: ignore
		patcher = mock.patch("python.task.playlist_layer.render_error_image", side_effect=lambda stm, dims, title, lines, theme=None, **kw: Image.new("RGB", (8, 8)))
		self.render_error = patcher.start()
		self.addCleanup(patcher.stop)
		calls: list[str] = []
		def make(id, name):
			plugin = plugin_factory(id, name)
			plugin.calls = calls
			return plugin
		tracks = [PlaylistSchedule("p1", f"t{i}", f"Track {i}", PlaylistScheduleData({})) for i in range(track_count)]
		playlists = cast(list[ScheduleLoaderDict], [{"info": Playlist("pl1", "Main", items=tracks), "name": "x", "path": "/x", "type": SCHEMA_PLAYLIST}])
		layer._evaluate_plugin = lambda t: {"plugin": make("p1", "Plugin"), "track": t}  # type: ignore
		root = ServiceContainer()
		root.add_service(TimeOfDay, layer.timebase)
		return layer, playlists, root, calls

	def _run_pass(self, layer, playlists, root):
		import asyncio
		return asyncio.run(layer._layer_task(root, playlists, Event()))

	def test_a_transient_failure_gets_three_strikes_then_the_layer_faults(self):
		class Flaky:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
				raise ConnectionError("network down")
		layer, playlists, root, calls = self._strike_setup(Flaky)
		self.assertIsNone(self._run_pass(layer, playlists, root))
		self.assertIsNone(self._run_pass(layer, playlists, root))
		self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
		self.assertEqual(calls, ["t0", "t0", "t0"])
		# struck out: a later pass does not run it again
		self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
		self.assertEqual(len(calls), 3)

	def test_a_struck_out_track_is_tried_again_after_its_wait_and_a_success_clears_it(self):
		class Recovers:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
				if not self.up[0]:
					raise ConnectionError("network down")
		up = [False]
		layer, playlists, root, calls = self._strike_setup(Recovers, track_count=2)
		now = [1000.0]
		layer._clock = lambda: now[0]
		original = layer._evaluate_plugin
		def with_up(t):
			found = original(t)
			found["plugin"].up = up
			return found
		layer._evaluate_plugin = with_up  # type: ignore
		for _ in range(3):
			self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 3)
		# still waiting: the track is not run, its error page is shown
		self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 3)
		# the wait is over and the network is still down: one attempt, struck out again, and the wait is longer
		now[0] += layer.STRIKE_RETRY_SECONDS + 1
		self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 4)
		self.assertEqual(layer._retry_seconds(layer._strikes[(0, 0)]), layer.STRIKE_RETRY_SECONDS * 2)
		now[0] += layer.STRIKE_RETRY_SECONDS + 1
		self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 4)
		# the network is back: the next try after the longer wait works, and the track is no longer struck out
		up[0] = True
		now[0] += layer.STRIKE_RETRY_SECONDS * 2
		self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 5)
		self.assertFalse(layer._struck_out((0, 0)))
		self.assertNotIn((0, 0), layer._strikes)
		self._run_pass(layer, playlists, root)
		self.assertEqual(calls.count("t0"), 6)

	def test_the_system_settings_decide_the_strikes_and_the_waits(self):
		from types import SimpleNamespace
		layer = self.layer
		def settings(document):
			return SimpleNamespace(settings_manager=lambda: SimpleNamespace(open=lambda name: SimpleNamespace(get=lambda: ("rev", document))))
		layer.cm = settings({ "maxStrikes": 2, "strikeRetrySeconds": 30, "strikeRetryMaxSeconds": 40 })  # type: ignore
		self.assertEqual(tuple(layer._policy()), (2, 30.0, 40.0))
		self.assertEqual([layer._retry_seconds(count) for count in (2, 3, 4)], [30.0, 40.0, 40.0])
		# a value that is missing, out of range or not a number is the built-in one
		layer.cm = settings({ "maxStrikes": 0, "strikeRetrySeconds": "soon" })  # type: ignore
		self.assertEqual(tuple(layer._policy()), (layer.MAX_STRIKES, layer.STRIKE_RETRY_SECONDS, layer.STRIKE_RETRY_MAX_SECONDS))
		layer.cm = settings(None)  # type: ignore
		self.assertEqual(layer._policy().strikes, layer.MAX_STRIKES)

	def test_the_wait_before_another_try_is_capped(self):
		layer = self.layer
		self.assertEqual(layer._retry_seconds(layer.MAX_STRIKES), layer.STRIKE_RETRY_SECONDS)
		self.assertEqual(layer._retry_seconds(layer.MAX_STRIKES + 40), layer.STRIKE_RETRY_MAX_SECONDS)

	def test_a_faulted_layer_tries_its_tracks_again_when_one_is_due(self):
		class Flaky:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
				raise ConnectionError("network down")
		layer, playlists, root, calls = self._strike_setup(Flaky)
		now = [1000.0]
		layer._clock = lambda: now[0]
		for _ in range(3):
			self._run_pass(layer, playlists, root)
		layer._layer_faulted(LayerFaulted(datetime.now()))
		self.addCleanup(layer._cancel_restart)
		self.assertEqual(layer.state, "faulted")
		# a timer is waiting for the first track's wait to end
		self.assertIsNotNone(layer._restart_timer)
		accepted: list = []
		layer.accept = accepted.append  # type: ignore
		layer._retry_struck_out(RetryStruckOut(datetime.now()))
		self.assertEqual(layer.state, "loaded")
		self.assertEqual([type(m) for m in accepted], [StartPlayback])
		# a stopped layer stays stopped
		layer.state = "faulted"
		layer._halted = True
		layer._retry_struck_out(RetryStruckOut(datetime.now()))
		self.assertEqual(layer.state, "faulted")

	def test_a_permanent_failure_strikes_out_at_once(self):
		for error in (PermanentError("gone for good"), TypeError("bad setting"), ImportError("no module")):
			with self.subTest(type(error).__name__):
				class Hard:
					def __init__(self, id, name):
						self.id, self.name = id, name
					async def task_async(self, ctx, track, donev):
						self.calls.append(track.id)
						raise error
				self.setUp()
				layer, playlists, root, calls = self._strike_setup(Hard)
				self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
				self.assertEqual(calls, ["t0"])

	def _slot_events(self) -> list:
		"""The start, failure and end of each track the layer reported (in order), as `[(kind, track)]`, from what `_strike_setup` recorded."""
		seen: list = []
		for route, msg in self.sent:
			kind = getattr(msg, "values", {}).get("kind") if route == "telemetry" else None
			if kind in ("track-started", "track-failed", "track-ended"):
				seen.append((kind, msg.values.get("current_track") if kind != "track-failed" else None))
		return seen

	def test_a_track_that_fails_is_started_and_ended_around_its_error_page(self):
		class Flaky:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				raise ConnectionError("network down")
		layer, playlists, root, calls = self._strike_setup(Flaky)
		self.assertIsNone(self._run_pass(layer, playlists, root))
		# the plugin announced the start, the failure was told, and the slot's end is said when the error page's time is over
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started", "track-failed", "track-ended"])
		self.assertEqual([track.title for kind, track in seen if track is not None], ["Track 0", "Track 0"])

	def test_a_track_that_struck_out_still_has_a_start_and_an_end_for_its_page(self):
		class Hard:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				raise PermanentError("gone for good")
		layer, playlists, root, calls = self._strike_setup(Hard, track_count=2)
		self._run_pass(layer, playlists, root)
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started", "track-failed", "track-ended", "track-started", "track-failed", "track-ended"])
		self.sent.clear()
		# a later pass does not run them again, but their slots still show the page, and say so
		self._run_pass(layer, playlists, root)
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started", "track-ended", "track-started", "track-ended"])

	def test_a_plugin_that_is_not_there_and_settings_that_are_wrong_are_slots_too(self):
		class Fine:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				return None
		layer, playlists, root, _ = self._strike_setup(Fine)
		layer._evaluate_plugin = lambda t: {"plugin": None, "track": t}  # type: ignore
		self._run_pass(layer, playlists, root)
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started", "track-failed", "track-ended"], "no plugin")
		self.setUp()
		layer, playlists, root, _ = self._strike_setup(Fine)
		layer._settings_problem = lambda track, plugins, datasources: "folder: Required"  # type: ignore
		self._run_pass(layer, playlists, root)
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started", "track-failed", "track-ended"], "settings problem")

	def test_a_track_that_works_is_unchanged(self):
		class Fine:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				return None
		layer, playlists, root, _ = self._strike_setup(Fine)
		self._run_pass(layer, playlists, root)
		# the end of a good slot is the layer's `playing` state, which the hub names `track-ended`: no `kind` of its own
		seen = self._slot_events()
		self.assertEqual([kind for kind, _ in seen], ["track-started"])
	def _completed(self, outcome) -> tuple[list, list, datetime]:
		"""The layer is told that its pass has ended (`outcome`: None, or an exception); returns what it sent to the telemetry, what it asked of itself, and the stamp the pass began with."""
		from concurrent.futures import Future
		from ..task.messages import AsyncTaskCompleted
		layer = self.layer
		layer.state = 'playing'
		sent: list = []
		layer.router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		accepted: list = []
		layer.accept = accepted.append  # type: ignore
		began = datetime(2020, 1, 1, tzinfo=timezone.utc)
		future: Future = Future()
		if isinstance(outcome, BaseException):
			future.set_exception(outcome)
		else:
			future.set_result(outcome)
		layer._async_task_completed(AsyncTaskCompleted(began, "layer_task", future, Event()))
		layer._cancel_restart()
		return sent, accepted, began

	def test_the_end_of_a_pass_is_not_announced_as_a_stop_and_the_next_pass_is_stamped_now(self):
		sent, accepted, began = self._completed(None)
		self.assertEqual([m for route, m in sent if route == "telemetry"], [], "an ordinary end of a pass tells nobody anything: the next track's start does")
		[start] = [m for m in accepted if isinstance(m, StartPlayback)]
		# the stamp the pass began with is not passed on: every pass was stamped with the first one's, for good
		self.assertGreater(start.timestamp, began + timedelta(days=365))

	def test_a_pass_that_failed_is_told_with_the_time_it_failed(self):
		sent, accepted, began = self._completed(RuntimeError("boom"))
		[event] = [m for route, m in sent if route == "telemetry"]
		self.assertEqual(event.values["kind"], "error")
		self.assertIn("The playlist stopped on an error", event.values["message"])
		self.assertGreater(event.timestamp, began + timedelta(days=365))

	def test_a_success_resets_the_strikes(self):
		outcomes = [ConnectionError("x"), ConnectionError("x"), None, ConnectionError("x"), ConnectionError("x"), None]
		class Sometimes:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				outcome = outcomes.pop(0)
				if outcome is not None:
					raise outcome
		layer, playlists, root, calls = self._strike_setup(Sometimes)
		for _ in range(6):
			self.assertIsNone(self._run_pass(layer, playlists, root))
		self.assertEqual(layer._strikes, {})

	def test_a_struck_out_track_is_skipped_while_the_others_keep_playing(self):
		class OneBad:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
				if track.id == "t0":
					raise PermanentError("never works")
		layer, playlists, root, calls = self._strike_setup(OneBad, track_count=2)
		for _ in range(3):
			self.assertIsNone(self._run_pass(layer, playlists, root))
		self.assertEqual(calls, ["t0", "t1", "t1", "t1"])

	def test_a_failed_slot_shows_an_error_page_and_a_struck_out_one_keeps_showing_it(self):
		class Hard:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
				raise PermanentError("the folder is gone")
		layer, playlists, root, calls = self._strike_setup(Hard, track_count=2)
		self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
		self.assertEqual(calls, ["t0", "t1"])
		shown = [(m.title, kind) for kind, m in self.sent if kind == "display" for m in [m]]
		self.assertEqual([t for t, _ in shown], ["Error: Track 0", "Error: Track 1", "Error: playback stopped"])
		# every error page is foreground (override): the overlays are not drawn on it, they would compete with its text
		self.assertEqual({m.layer for kind, m in self.sent if kind == "display"}, {"override"})
		# the page is told what failed and why, in our own words
		first = self.render_error.call_args_list[0].args
		self.assertEqual((first[2], first[3]), ("Track 0", ["the folder is gone"]))
		# a later pass does not run the plugin again, but each slot still says why
		self.sent.clear()
		self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
		self.assertEqual(calls, ["t0", "t1"])
		self.assertEqual(len([1 for kind, _ in self.sent if kind == "display"]), 3)

	def test_the_error_page_never_carries_the_exceptions_text(self):
		class Leaky:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				raise ConnectionError("https://api.example/x?key=SECRET")
		layer, playlists, root, calls = self._strike_setup(Leaky)
		self._run_pass(layer, playlists, root)
		lines = self.render_error.call_args_list[0].args[3]
		self.assertEqual(lines, ["Could not connect to the server. Check the address and the network."])

	def test_missing_required_settings_strike_out_without_running_the_plugin(self):
		class Never:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx, track, donev):
				self.calls.append(track.id)
		layer, playlists, root, calls = self._strike_setup(Never)
		layer.plugin_info = [{"info": {"id": "p1", "instanceSettings": {"schema": {"properties": [
			{"name": "folder", "type": "string", "required": True}
		]}}}}]  # type: ignore
		self.assertIsInstance(self._run_pass(layer, playlists, root), LayerFaulted)
		self.assertEqual(calls, [])

	def test_faulted_layer_waits_then_retries_on_a_configuration_change(self):
		import asyncio
		from ..task.messages import ConfigurationChanged
		layer = self.layer
		layer.cm = object()  # type: ignore
		layer._layer_faulted(LayerFaulted(datetime.now()))
		self.addCleanup(layer._cancel_restart)
		self.assertEqual(layer.state, "faulted")
		fired = []
		layer._reload.trigger = lambda: fired.append(1)  # type: ignore
		layer._configuration_changed(ConfigurationChanged(datetime.now(), "plugin", "modified", "x"))
		self.assertEqual(fired, [1])
		layer.state = "loaded"
		layer._configuration_changed(ConfigurationChanged(datetime.now(), "plugin", "modified", "x"))
		self.assertEqual(fired, [1])

	def test_empty_playlists_back_off(self):
		import asyncio, time
		layer = self.layer
		layer.BACKOFF_INITIAL_SECONDS = 0.2
		root = ServiceContainer()
		root.add_service(TimeOfDay, layer.timebase)
		start = time.monotonic()
		asyncio.run(layer._layer_task(root, [], Event()))
		self.assertGreaterEqual(time.monotonic() - start, 0.2)

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

