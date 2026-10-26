"""Play, stop and next for the playlist layer (#354): the Application is the first hop, the layer cancels and re-enters tracks, and a reload goes on where it was."""
import asyncio
import unittest
from datetime import datetime
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from ..model.schedule import Playlist, PlaylistSchedule, PlaylistScheduleData
from ..model.service_container import ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..plugins.plugin_base import PluginExecutionContext
from ..task.application import Application
from ..task.message_router import MessageRouter, Route
from ..task.messages import ReloadSchedules, Telemetry, TransportCommand
from ..task.playlist_layer import NextTrack, PlaylistLayer, Position, ResumePlayback, Start, StartPlayback, StopPlayback
from .test_web_api import WebApiTestBase
from .utils import ScaledTimeOfDay, ScaledTimerThreadService, create_configuration_manager

def track(id: str, **content) -> PlaylistSchedule:
	return PlaylistSchedule("p1", id, f"Track {id}", PlaylistScheduleData(dict(content)))

def loaded(*playlists: tuple[str, list[PlaylistSchedule]]) -> list[Any]:
	"""Playlists as the schedule loader hands them over: `[(id, [tracks])]`."""
	return [{ "info": Playlist(pid, pid, items=items), "name": pid, "path": "/x", "type": "playlist" } for pid, items in playlists]

class Following(unittest.TestCase):
	def test_the_next_track_wraps_and_crosses_playlists(self):
		pls = loaded(("a", [track("a0"), track("a1")]), ("b", [track("b0")]))
		following = PlaylistLayer._following
		self.assertEqual(following(pls, Position("a", "a0", 0, 0)), (0, 1))
		self.assertEqual(following(pls, Position("a", "a1", 0, 1)), (1, 0))
		self.assertEqual(following(pls, Position("b", "b0", 1, 0)), (0, 0))
		self.assertEqual(following(pls, None), (0, 0))

	def test_an_empty_playlist_is_stepped_over(self):
		pls = loaded(("a", [track("a0")]), ("empty", []), ("c", [track("c0")]))
		self.assertEqual(PlaylistLayer._following(pls, Position("a", "a0", 0, 0)), (2, 0))

	def test_no_tracks_at_all_is_nowhere(self):
		self.assertIsNone(PlaylistLayer._following(loaded(("a", [])), None))
		self.assertIsNone(PlaylistLayer._following([], None))

class LayerCase(unittest.TestCase):
	def setUp(self):
		self.sent: list = []
		router = MessageRouter()
		self.layer = PlaylistLayer("playlistlayer", router)
		self.layer.router.send = lambda route, msg: self.sent.append((route, msg))  # type: ignore
		self.layer.cm = create_configuration_manager()
		self.layer.timebase = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		self.layer.timer = ScaledTimerThreadService(self.layer.timebase, 60)
		self.layer.playlists = loaded(("pl1", [track("t0"), track("t1"), track("t2")]))
		self.layer.state = "playing"
		self.stopped_tasks = 0
		self.started: list = []
		def task_stop():
			self.stopped_tasks += 1
		self.layer._task_stop = task_stop  # type: ignore
		self.layer._run_layer_task = lambda playlists, ts, start=None: self.started.append(start)  # type: ignore
		self.ts = datetime.now().astimezone()

class TestStop(LayerCase):
	def test_stop_cancels_the_track_once_and_says_so(self):
		self.layer._stop_playback(StopPlayback(self.ts))
		self.assertTrue(self.layer.halted)
		self.assertEqual((self.layer.state, self.stopped_tasks), ("halted", 1))
		route, event = self.sent[-1]
		self.assertEqual(route, "telemetry")
		self.assertIsInstance(event, Telemetry)
		self.assertEqual((event.values["kind"], event.values["state"]), ("transport", "halted"))
		# again: nothing more to do
		self.layer._stop_playback(StopPlayback(self.ts))
		self.assertEqual((self.stopped_tasks, len(self.sent)), (1, 1))

	def test_a_faulted_or_unloaded_layer_ignores_it(self):
		for state in ("faulted", "uninitialized"):
			self.layer.state = state
			self.layer._stop_playback(StopPlayback(self.ts))
			self.assertFalse(self.layer.halted, state)
		self.layer.state = "playing"
		self.layer.playlists = []
		self.layer._stop_playback(StopPlayback(self.ts))
		self.assertFalse(self.layer.halted)
		self.assertEqual(self.stopped_tasks, 0)

	def test_nothing_starts_a_stopped_layer_but_play_and_next(self):
		self.layer._stop_playback(StopPlayback(self.ts))
		# the end of a pass, the restart timer and a reload all send this
		self.layer.state = "stopped"
		self.layer._start_playback(StartPlayback(self.ts))
		self.assertEqual(self.started, [])

	def test_a_pass_that_ends_as_the_stop_arrives_does_not_start_another(self):
		from concurrent.futures import Future
		from ..task.messages import AsyncTaskCompleted
		fut: Future = Future()
		fut.set_result(None)
		self.layer._halted = True
		self.layer.state = "halted"
		self.layer._async_task_completed(AsyncTaskCompleted(self.ts, "layer_task", fut, Event()))
		self.assertEqual(self.layer.state, "halted")
		self.assertEqual(self.sent, [])

class TestPlay(LayerCase):
	def test_play_goes_back_into_the_interrupted_track(self):
		self.layer._current = Position("pl1", "t1", 0, 1)
		self.layer._stop_playback(StopPlayback(self.ts))
		self.layer._resume_playback(ResumePlayback(self.ts))
		self.assertFalse(self.layer.halted)
		self.assertEqual(self.started, [Start(0, 1, True)])

	def test_play_from_a_layer_that_is_not_stopped_does_nothing(self):
		self.layer._resume_playback(ResumePlayback(self.ts))
		self.assertEqual(self.started, [])

	def test_play_before_any_track_began_starts_from_the_top(self):
		self.layer._stop_playback(StopPlayback(self.ts))
		self.layer._resume_playback(ResumePlayback(self.ts))
		self.assertEqual(self.started, [None])

	def test_a_track_edited_while_stopped_runs_afresh_not_as_a_resume(self):
		self.layer._current = Position("pl1", "t1", 0, 1, resume=False)
		self.layer._stop_playback(StopPlayback(self.ts))
		self.layer._resume_playback(ResumePlayback(self.ts))
		self.assertEqual(self.started, [Start(0, 1, False)])

class TestNext(LayerCase):
	def test_next_cancels_and_begins_at_the_following_track(self):
		self.layer._current = Position("pl1", "t0", 0, 0)
		self.layer._next_track(NextTrack(self.ts))
		self.assertEqual((self.stopped_tasks, self.started), (1, [Start(0, 1, False)]))

	def test_next_from_the_last_track_wraps(self):
		self.layer._current = Position("pl1", "t2", 0, 2)
		self.layer._next_track(NextTrack(self.ts))
		self.assertEqual(self.started, [Start(0, 0, False)])

	def test_next_on_a_stopped_layer_plays_from_the_following_track(self):
		self.layer._current = Position("pl1", "t0", 0, 0)
		self.layer._stop_playback(StopPlayback(self.ts))
		self.layer._next_track(NextTrack(self.ts))
		self.assertFalse(self.layer.halted)
		self.assertEqual(self.started, [Start(0, 1, False)])
		# the play/stop button follows the layer's events: it must hear that playback is back
		states = [msg.values["state"] for route, msg in self.sent if route == "telemetry"]
		self.assertEqual(states, ["halted", "playing"])

	def test_next_on_a_layer_that_plays_says_nothing_about_playing(self):
		self.layer._current = Position("pl1", "t0", 0, 0)
		self.layer._next_track(NextTrack(self.ts))
		self.assertEqual([r for r, _ in self.sent], [])

	def test_next_is_ignored_when_faulted_or_there_is_nothing_to_play(self):
		self.layer.state = "faulted"
		self.layer._next_track(NextTrack(self.ts))
		self.layer.state = "playing"
		self.layer.playlists = loaded(("empty", []))
		self.layer._next_track(NextTrack(self.ts))
		self.assertEqual((self.stopped_tasks, self.started), (0, []))

class TestPass(unittest.TestCase):
	"""One pass over real `_layer_task`, with plugins that write down what they were given."""
	def setUp(self):
		self.layer = PlaylistLayer("playlistlayer", MessageRouter())
		self.layer.router.send = lambda route, msg: None  # type: ignore
		self.layer.cm = create_configuration_manager()
		self.layer.timebase = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		self.calls: list[tuple[str, bool]] = []
		calls = self.calls
		class Rec:
			def __init__(self, id, name):
				self.id, self.name = id, name
			async def task_async(self, ctx: PluginExecutionContext, track, donev):
				calls.append((track.id, ctx.resumed))
		self.layer._evaluate_plugin = lambda t: {"plugin": Rec("p1", "Plugin"), "track": t}  # type: ignore
		self.root = ServiceContainer()
		self.root.add_service(TimeOfDay, self.layer.timebase)
		self.playlists = loaded(("a", [track("a0"), track("a1"), track("a2")]), ("b", [track("b0"), track("b1")]))

	def run_pass(self, start: Start|None):
		return asyncio.run(self.layer._layer_task(self.root, self.playlists, Event(), start))

	def test_a_pass_from_the_top_resumes_nothing(self):
		self.run_pass(None)
		self.assertEqual(self.calls, [("a0", False), ("a1", False), ("a2", False), ("b0", False), ("b1", False)])
		self.assertEqual(self.layer._current, Position("b", "b1", 1, 1))

	def test_a_pass_begins_at_its_start_and_only_that_track_is_a_resume(self):
		self.run_pass(Start(0, 1, True))
		self.assertEqual(self.calls, [("a1", True), ("a2", False), ("b0", False), ("b1", False)])

	def test_a_start_in_a_later_playlist_skips_the_ones_before(self):
		self.run_pass(Start(1, 0, False))
		self.assertEqual(self.calls, [("b0", False), ("b1", False)])

	def test_a_start_past_the_end_ends_the_pass_at_once_without_backing_off(self):
		import time
		self.layer.BACKOFF_INITIAL_SECONDS = 5
		began = time.monotonic()
		self.assertIsNone(self.run_pass(Start(1, 9, False)))
		self.assertEqual(self.calls, [])
		self.assertLess(time.monotonic() - began, 2)

class TestReload(LayerCase):
	"""A schedule reload goes on where the layer was, found by the ids in the new playlists."""
	def setUp(self):
		super().setUp()
		self.old = loaded(("pl1", [track("t0", n=0), track("t1", n=1), track("t2", n=2)]))
		self.layer.playlists = self.old
		self.layer._loaded = self.layer._signature(self.old)
		self.layer._snapshots = self.layer._snapshot(self.old)
		self.layer._current = Position("pl1", "t1", 0, 1)
		self.accepted: list = []
		self.layer.accept = lambda msg: self.accepted.append(msg)  # type: ignore

	def reload(self, new: list[Any]):
		manager = mock.MagicMock()
		manager.load.return_value = { "playlists": new }
		self.layer.cm = SimpleNamespace(schedule_manager=lambda: manager)  # type: ignore
		self.layer._reload_schedules(ReloadSchedules(self.ts))

	def start(self) -> Start|None:
		self.assertEqual(len(self.accepted), 1)
		self.assertIsInstance(self.accepted[0], StartPlayback)
		return self.accepted[0].start

	def test_the_same_track_resumes_wherever_the_edit_moved_it(self):
		self.reload(loaded(("pl1", [track("new", n=9), track("t0", n=0), track("t1", n=1), track("t2", n=2)])))
		self.assertEqual(self.start(), Start(0, 2, True))
		self.assertEqual(self.stopped_tasks, 1)

	def test_a_track_whose_own_settings_changed_runs_afresh(self):
		self.reload(loaded(("pl1", [track("t0", n=0), track("t1", n=100), track("t2", n=2)])))
		self.assertEqual(self.start(), Start(0, 1, False))

	def test_a_track_that_is_gone_leaves_its_place_in_the_playlist(self):
		self.reload(loaded(("pl1", [track("t0", n=0), track("t2", n=2)])))
		self.assertEqual(self.start(), Start(0, 1, False))

	def test_a_playlist_that_is_gone_starts_from_the_top(self):
		self.reload(loaded(("other", [track("o0")])))
		self.assertIsNone(self.start())

	def test_a_layer_that_has_not_begun_starts_from_the_top(self):
		self.layer._current = None
		self.reload(loaded(("pl1", [track("t0", n=5)])))
		self.assertIsNone(self.start())

	def test_a_faulted_layer_starts_from_the_top(self):
		self.layer.state = "faulted"
		self.reload(loaded(("pl1", [track("t0", n=0), track("t1", n=1), track("t2", n=2)])))
		self.assertIsNone(self.start())

	def test_the_defaults_the_layer_filled_in_are_not_a_change(self):
		# the tracks that ran have their defaults in them; the files do not
		self.old[0]["info"].items[1].content.data["filled"] = "by the layer"
		self.reload(loaded(("pl1", [track("t0", n=0), track("t1", n=1), track("t2", n=2)])))
		self.assertEqual((self.accepted, self.stopped_tasks), ([], 0))

	def test_a_stopped_layer_loads_the_playlists_and_waits_for_play(self):
		self.layer._halted = True
		self.layer.state = "halted"
		self.reload(loaded(("pl1", [track("new", n=9), track("t0", n=0), track("t1", n=1), track("t2", n=2)])))
		self.assertEqual((self.accepted, self.layer.state), ([], "halted"))
		self.assertEqual(self.layer._current, Position("pl1", "t1", 0, 2, True))
		self.layer._resume_playback(ResumePlayback(self.ts))
		self.assertEqual(self.started, [Start(0, 2, True)])

class Recorder:
	def __init__(self):
		self.got: list = []
	def accept(self, msg):
		self.got.append(msg)

class TestApplication(unittest.TestCase):
	def setUp(self):
		self.app = Application("app")
		self.layer = Recorder()
		self.app.router = MessageRouter()
		self.app.router.addRoute(Route("playlist-layer", [cast(Any, self.layer)]))
		self.ts = datetime.now().astimezone()

	def test_each_command_becomes_a_message_for_the_playlist_layer_only(self):
		for command, kind in (("stop", StopPlayback), ("play", ResumePlayback), ("next", NextTrack)):
			self.app._transport_command(TransportCommand(self.ts, command))
			self.assertIsInstance(self.layer.got[-1], kind)
		self.assertEqual(len(self.layer.got), 3)

	def test_an_unclaimed_device_drops_them(self):
		self.app._held = cast(Any, object())
		self.app._transport_command(TransportCommand(self.ts, "stop"))
		self.assertEqual(self.layer.got, [])

	def test_a_command_the_application_does_not_know_goes_nowhere(self):
		self.app._transport_command(TransportCommand(self.ts, "rewind"))
		self.assertEqual(self.layer.got, [])
		self.assertFalse(self.app.transport("rewind"))

	def test_transport_hands_the_command_to_the_applications_own_thread(self):
		accepted: list = []
		self.app.accept = lambda msg: accepted.append(msg)  # type: ignore
		self.assertTrue(self.app.transport("stop"))
		self.assertEqual([(type(m), m.command) for m in accepted], [(TransportCommand, "stop")])

	def test_the_application_that_has_stopped_says_so(self):
		def refuse(msg):
			raise ValueError("stopped")
		self.app.accept = refuse  # type: ignore
		self.assertFalse(self.app.transport("stop"))

	def test_playback_stopped_is_what_the_layer_says(self):
		self.assertFalse(self.app.playback_stopped)
		self.app.playlist_layer = cast(Any, SimpleNamespace(halted=True))
		self.assertTrue(self.app.playback_stopped)

	def test_the_position_is_the_layers_by_id(self):
		self.assertIsNone(self.app.playback_position)
		self.app.playlist_layer = cast(Any, SimpleNamespace(position=None))
		self.assertIsNone(self.app.playback_position)
		self.app.playlist_layer = cast(Any, SimpleNamespace(position=Position("main", "t2", 0, 1)))
		self.assertEqual(self.app.playback_position, ("main", "t2"))

class TestTransportApi(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.commands: list[str] = []
		self.application = SimpleNamespace(playlist_layer=object(), playback_stopped=False, playback_position=None, transport=lambda command: self.commands.append(command) or True)
		self.app.state.root_container.add_service(Application, self.application)

	def test_a_command_is_forwarded_to_the_application(self):
		for command in ("play", "stop", "next"):
			resp = self.client.post("/api/transport", json={ "command": command })
			self.assertEqual((resp.status_code, resp.json()), (200, { "success": True }), resp.text)
		self.assertEqual(self.commands, ["play", "stop", "next"])

	def test_anything_else_is_a_422(self):
		resp = self.client.post("/api/transport", json={ "command": "rewind" })
		self.assertEqual(resp.status_code, 422)
		self.assertFalse(resp.json()["success"])
		self.assertEqual(self.commands, [])
		self.assertEqual(self.client.post("/api/transport", json={}).status_code, 422)

	def test_get_says_whether_it_is_stopped(self):
		self.assertEqual(self.client.get("/api/transport").json(), { "stopped": False })
		self.application.playback_stopped = True
		self.assertEqual(self.client.get("/api/transport").json(), { "stopped": True })

	def test_get_says_where_the_layer_is_once_it_has_played(self):
		self.application.playback_position = ("main", "t2")
		self.assertEqual(self.client.get("/api/transport").json(), { "stopped": False, "playlist_id": "main", "track_id": "t2" })

	def test_before_the_layers_exist_it_is_a_503_in_our_words(self):
		self.application.playlist_layer = None
		for resp in (self.client.get("/api/transport"), self.client.post("/api/transport", json={ "command": "stop" })):
			self.assertEqual(resp.status_code, 503)
			self.assertEqual(set(resp.json()), { "success", "message", "id" })

	def test_a_device_shutting_down_is_a_503(self):
		self.application.transport = lambda command: False
		self.assertEqual(self.client.post("/api/transport", json={ "command": "stop" }).status_code, 503)

class TestSignIn(WebApiTestBase):
	token = "secret"
	auth = "required"

	def test_it_needs_a_sign_in_like_the_rest_of_the_api(self):
		self.app.state.root_container.add_service(Application, SimpleNamespace(playlist_layer=object(), playback_stopped=False, playback_position=None, transport=lambda command: True))
		self.assertEqual(self.client.post("/api/transport", json={ "command": "stop" }).status_code, 401)
		resp = self.client.post("/api/transport", json={ "command": "stop" }, headers={ "Authorization": "Bearer secret" })
		self.assertEqual(resp.status_code, 200, resp.text)

class TestPluginsHandleResume(unittest.TestCase):
	"""Every plugin says how it handles `PluginExecutionContext.resumed` (the contract is in `PluginAsync`), so a new plugin cannot forget it."""
	def test_every_plugin_in_the_repository_says_how(self):
		cm = create_configuration_manager()
		found = [info["info"]["id"] for info in cm.enum_plugins()]
		self.assertTrue({ "slide-show", "overlay", "priority-update" } <= set(found), found)
		for info in cm.enum_plugins():
			plugin = cm.create_plugin(info)
			self.assertIn(getattr(plugin, "resume_contract", None), ("honours", "ignores"), f"plugin '{info['info']['id']}' does not say how it handles `resumed`")

	def test_the_plugins_the_playlist_layer_runs_honour_it(self):
		cm = create_configuration_manager()
		contracts = { info["info"]["id"]: getattr(cm.create_plugin(info), "resume_contract", None) for info in cm.enum_plugins() }
		# the playlist layer's plugin lookup asks for `layer-background` / `layer-foreground`; the timer layer's for priority and overlay
		self.assertEqual(contracts["slide-show"], "honours")
		self.assertEqual((contracts["overlay"], contracts["priority-update"]), ("ignores", "ignores"))

	def test_the_context_defaults_to_not_resumed(self):
		context = PluginExecutionContext(ServiceContainer(), (8, 8), datetime.now().astimezone())
		self.assertFalse(context.resumed)
		self.assertTrue(PluginExecutionContext(ServiceContainer(), (8, 8), datetime.now().astimezone(), resumed=True).resumed)

if __name__ == "__main__":
	unittest.main()
