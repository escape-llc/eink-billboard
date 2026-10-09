"""
TimerLayer behaviour, on a virtual clock: sleeping advances the fake time instantly, so days pass in milliseconds.
The tests set their own time zone and write their own schedules; they need no datasources/ or plugins/ in the storage.
"""
import asyncio
import contextlib
import threading
import time
import unittest
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

from ..datasources.data_source import DataSourceManager
from ..model.schedule import SCHEMA_TASKS, TimerTaskItem, TimerTaskTask, TimerTasks, TriggerDict
from ..model.schedule_loader import ScheduleLoaderDict
from ..model.service_container import ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..task.messages import AsyncTaskCompleted, BasicMessage, Telemetry
from ..task.message_router import MessageRouter, Route
from ..task.playlist_layer import StartPlayback
from ..task.protocols import IProvideTimer
from ..task.timer import TimerThreadService
from ..task.timer_layer import TimerLayer
from .utils import ConstantTimeOfDay, MessageCollectSink, create_configuration_manager

NY = ZoneInfo("America/New_York")

class FakeClock(TimeOfDay):
	def __init__(self, now: datetime):
		self.now = now
	def current_time(self) -> datetime:
		return self.now
	def current_time_utc(self) -> datetime:
		return self.now.astimezone(timezone.utc)
	def advance(self, delta: timedelta) -> None:
		# absolute time moves; the wall clock follows the zone (so DST gaps are crossed correctly)
		self.now = (self.now.astimezone(timezone.utc) + delta).astimezone(self.now.tzinfo)

class FakeTimer(IProvideTimer):
	"""sleep() moves the clock and returns at once; once the clock reaches `stop_at` it blocks until cancelled."""
	def __init__(self, clock: FakeClock, stop_at: datetime):
		self.clock = clock
		self.stop_at = stop_at
		self.reached = asyncio.Event()
		self.sleeps: list[timedelta] = []
	async def sleep(self, deltatime: timedelta) -> None:
		if deltatime.total_seconds() < 0:
			raise ValueError("negative sleep")
		self.sleeps.append(deltatime)
		self.clock.advance(deltatime)
		await asyncio.sleep(0)
		if self.clock.now >= self.stop_at:
			self.reached.set()
			await asyncio.Event().wait()
	def delta_for(self, deltatime: timedelta) -> timedelta:
		return deltatime
	def create_timer(self, deltatime, sink, token, state):
		raise NotImplementedError()

class FakePlugin:
	def __init__(self, clock: FakeClock, runs: list, durations: dict[str, timedelta], events: list):
		self.clock, self.runs, self.durations, self.events = clock, runs, durations, events
	async def task_async(self, context, track, donev):
		self.runs.append((track.id, self.clock.now))
		self.events.append(donev)
		self.clock.advance(self.durations.get(track.id, timedelta(0)))
		return None

def at(hour: int, minute: int, *, startup: bool = False, day: dict|None = None) -> TriggerDict:
	return cast(TriggerDict, {
		"on_startup": startup,
		"day": day if day is not None else { "type": "dayofweek", "days": [0, 1, 2, 3, 4, 5, 6] },
		"time": { "type": "specific", "hour": hour, "minute": minute },
	})

NEVER = { "type": "dayandmonth", "day": 31, "month": 12 }

def make_item(ident: str, trigger: Any, enabled: bool = True) -> TimerTaskItem:
	return TimerTaskItem(ident, f"Title {ident}", enabled, TimerTaskTask("p", {}), cast(TriggerDict, trigger))

def make_tasks(items: list[TimerTaskItem]) -> list[ScheduleLoaderDict]:
	return cast(list[ScheduleLoaderDict], [{ "info": TimerTasks("ts", "Tasks", items=items), "name": "n", "path": "/x", "type": SCHEMA_TASKS }])

class LayerRun:
	"""Runs `_layer_task` on a virtual clock until the clock reaches `stop_at`, then cancels it."""
	def __init__(self, layer: TimerLayer, start: datetime, stop_at: datetime, durations: dict[str, timedelta]|None = None):
		self.layer = layer
		self.clock = FakeClock(start)
		self.stop_at = stop_at
		self.runs: list[tuple[str, datetime]] = []
		self.task_events: list[threading.Event] = []
		self.outer = threading.Event()
		self.status = ""
		self.timer: FakeTimer
		plugin = FakePlugin(self.clock, self.runs, durations or {}, self.task_events)
		layer._evaluate_plugin = lambda t: { "plugin": plugin, "track": t }  # type: ignore
	def go(self, tasks: list[ScheduleLoaderDict]) -> "LayerRun":
		isp = ServiceContainer()
		isp.add_service(TimeOfDay, self.clock)
		async def main():
			self.timer = FakeTimer(self.clock, self.stop_at)
			isp.add_service(IProvideTimer, self.timer)
			task = asyncio.ensure_future(self.layer._layer_task(isp, tasks, self.outer))
			waiter = asyncio.ensure_future(self.timer.reached.wait())
			done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED, timeout=5)
			waiter.cancel()
			if task in done:
				self.status = "returned"
				return
			task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await task
			self.status = "cancelled" if done else "timeout"
		asyncio.run(main())
		return self

def new_layer() -> TimerLayer:
	layer = TimerLayer("timerlayer", MessageRouter())
	layer.dimensions = (800, 480)
	return layer

class TestFailedTask(unittest.TestCase):
	def _run(self, plugin, item: TimerTaskItem):
		from unittest import mock
		from PIL import Image
		from ..task.display_messages import PriorityImage
		layer = new_layer()
		sent: list = []
		layer.router.send = lambda route, msg: sent.append((route, msg))  # type: ignore
		layer._evaluate_plugin = lambda t: { "plugin": plugin, "track": t }  # type: ignore
		clock = FakeClock(datetime(2024, 1, 1, 9, 0, tzinfo=NY))
		isp = ServiceContainer()
		isp.add_service(TimeOfDay, clock)
		with mock.patch("python.task.timer_layer.render_error_image", side_effect=lambda stm, dims, title, lines, theme=None: Image.new("RGB", (8, 8))) as render:
			asyncio.run(layer._run_task_item(isp, clock, item, "scheduled", 0, None, None))
		return sent, render, PriorityImage

	def test_a_failing_task_shows_an_error_page_for_its_slide_time(self):
		class Boom:
			async def task_async(self, context, track, donev):
				raise ConnectionError("https://api.example/x?key=SECRET")
		item = TimerTaskItem("a", "Weather", True, TimerTaskTask("p", { "slideMinutes": 5 }), cast(TriggerDict, at(9, 0)))
		sent, render, PriorityImage = self._run(Boom(), item)
		displays = [m for route, m in sent if route == "display"]
		self.assertEqual(len(displays), 1)
		self.assertIsInstance(displays[0], PriorityImage)
		self.assertEqual((displays[0].title, displays[0].duration), ("Error: Weather", timedelta(minutes=5)))
		# the page says the exception's type, never its text (a URL may carry a key)
		self.assertEqual(render.call_args.args[2:4], ("Weather", ["ConnectionError"]))

	def test_a_task_without_slide_minutes_shows_it_for_one_minute(self):
		class Boom:
			async def task_async(self, context, track, donev):
				raise RuntimeError("x")
		sent, _, _ = self._run(Boom(), make_item("a", at(9, 0)))
		self.assertEqual([m.duration for route, m in sent if route == "display"], [timedelta(minutes=1)])

	def test_a_task_that_works_shows_no_error_page(self):
		class Fine:
			async def task_async(self, context, track, donev):
				return None
		sent, _, _ = self._run(Fine(), make_item("a", at(9, 0)))
		self.assertEqual([r for r, _ in sent if r == "display"], [])

class TestLayerDays(unittest.TestCase):
	def test_rearms_for_the_following_days(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		run = LayerRun(new_layer(), start, datetime(2024, 1, 4, 8, 0, tzinfo=NY)).go(make_tasks([make_item("a", at(9, 0))]))
		self.assertEqual(run.status, "cancelled")
		self.assertEqual([r[1] for r in run.runs], [datetime(2024, 1, d, 9, 0, tzinfo=NY) for d in (1, 2, 3)])

	def test_rearm_follows_the_wall_clock_across_dst(self):
		start = datetime(2024, 3, 9, 20, 0, tzinfo=NY)
		run = LayerRun(new_layer(), start, datetime(2024, 3, 12, 8, 0, tzinfo=NY)).go(make_tasks([make_item("a", at(9, 0))]))
		self.assertEqual([r[1].isoformat() for r in run.runs], ["2024-03-10T09:00:00-04:00", "2024-03-11T09:00:00-04:00"])

	def test_startup_tasks_run_once_not_on_each_day(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		tasks = make_tasks([make_item("boot", at(9, 0, startup=True, day=NEVER)), make_item("daily", at(9, 0))])
		run = LayerRun(new_layer(), start, datetime(2024, 1, 4, 8, 0, tzinfo=NY)).go(tasks)
		self.assertEqual([r[0] for r in run.runs].count("boot"), 1)
		self.assertEqual([r[0] for r in run.runs].count("daily"), 3)
		self.assertEqual(run.runs[0][0], "boot")

	def test_a_day_without_entries_waits_for_midnight_without_spinning(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		stop = datetime(2024, 1, 4, 8, 0, tzinfo=NY)
		run = LayerRun(new_layer(), start, stop).go(make_tasks([make_item("a", at(9, 0, day=NEVER)), make_item("off", at(9, 0), enabled=False)]))
		self.assertEqual(run.status, "cancelled")
		self.assertEqual(run.runs, [])
		self.assertLessEqual(len(run.timer.sleeps), 6)
		self.assertTrue(all(s >= timedelta(minutes=1) for s in run.timer.sleeps), run.timer.sleeps)

	def test_nothing_enabled_at_all_does_not_spin_either(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		run = LayerRun(new_layer(), start, datetime(2024, 1, 3, 8, 0, tzinfo=NY)).go(make_tasks([make_item("off", at(9, 0), enabled=False)]))
		self.assertEqual(run.status, "cancelled")
		self.assertLessEqual(len(run.timer.sleeps), 4)

class TestLayerSequence(unittest.TestCase):
	def test_entries_due_during_a_long_task_run_late_in_order_within_the_grace(self):
		layer = new_layer()
		self.assertEqual(layer.LATE_GRACE, timedelta(minutes=5))
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		items = [make_item("a", at(9, 0)), make_item("b", at(9, 1)), make_item("c", at(9, 2)), make_item("e", at(9, 3)), make_item("d", at(9, 30))]
		durations = { k: timedelta(minutes=3) for k in "abce" }
		with self.assertLogs("python.task.timer_layer", level="WARNING") as logs:
			run = LayerRun(layer, start, datetime(2024, 1, 1, 10, 0, tzinfo=NY), durations).go(make_tasks(items))
		got = [(i, t.strftime("%H:%M")) for i, t in run.runs]
		# a 09:00-09:03, b (due 09:01) 09:03-09:06, c (due 09:02) 09:06-09:09; e (due 09:03) is 6 minutes late > grace: skipped
		self.assertEqual(got, [("a", "09:00"), ("b", "09:03"), ("c", "09:06"), ("d", "09:30")])
		self.assertTrue(any("Title e" in line for line in logs.output), logs.output)

	def test_exactly_the_grace_late_still_runs(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		items = [make_item("a", at(9, 0)), make_item("b", at(9, 1))]
		run = LayerRun(new_layer(), start, datetime(2024, 1, 1, 10, 0, tzinfo=NY), { "a": timedelta(minutes=6) }).go(make_tasks(items))
		self.assertEqual([i for i, _ in run.runs], ["a", "b"])

class TestLayerEvents(unittest.TestCase):
	def test_the_outer_done_event_is_set_and_tasks_get_their_own(self):
		start = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		run = LayerRun(new_layer(), start, datetime(2024, 1, 1, 10, 0, tzinfo=NY)).go(make_tasks([make_item("a", at(9, 0)), make_item("boot", at(9, 0, startup=True, day=NEVER))]))
		self.assertEqual(run.status, "cancelled")
		self.assertTrue(run.outer.is_set(), "the Event passed in must be set when the layer task ends")
		self.assertTrue(all(ev is not run.outer for ev in run.task_events))
		self.assertEqual(len(run.task_events), 2)

class TestLayerLogging(unittest.TestCase):
	def test_a_bad_trigger_is_skipped_with_a_warning_naming_the_title(self):
		layer = new_layer()
		bad = make_item("bad", { "day": { "type": "dayofweek", "days": [1] }, "time": { "type": "hourofday", "hours": [25], "minutes": [0] } })
		good = make_item("good", at(9, 0))
		with self.assertLogs("python.task.timer_layer", level="WARNING") as logs:
			entries = layer._next_scheduled_playlist(datetime(2024, 1, 1, 0, 0, tzinfo=NY), [bad, good])
		self.assertEqual([item.id for _, item in entries], ["good"])
		self.assertTrue(any("Title bad" in line for line in logs.output), logs.output)
		self.assertFalse(any("None" in line for line in logs.output), logs.output)

	def test_entries_are_ordered_by_instant_across_the_utc_offset_change(self):
		layer = new_layer()
		items = [make_item("late", at(5, 0)), make_item("early", at(1, 30)), make_item("gap", at(2, 30))]
		entries = layer._next_scheduled_playlist(datetime(2024, 3, 10, 0, 0, tzinfo=NY), items)
		self.assertEqual([i.id for _, i in entries], ["early", "gap", "late"])
		self.assertEqual(entries[1][0].isoformat(), "2024-03-10T03:30:00-04:00")

class TestLayerFailure(unittest.TestCase):
	def _layer(self) -> tuple[TimerLayer, list[BasicMessage], MessageCollectSink, threading.Event]:
		router = MessageRouter()
		telemetry = MessageCollectSink()
		router.addRoute(Route("telemetry", [telemetry]))
		layer = TimerLayer("timerlayer", router)
		layer.timebase = ConstantTimeOfDay(datetime(2024, 1, 1, 8, 0, tzinfo=NY))
		layer.RESTART_DELAY_SECONDS = 0.05
		accepted: list[BasicMessage] = []
		restarted = threading.Event()
		def record(msg: BasicMessage):
			accepted.append(msg)
			if isinstance(msg, StartPlayback):
				restarted.set()
		layer.accept = record  # type: ignore
		return layer, accepted, telemetry, restarted

	def test_a_crashed_layer_task_is_logged_reported_and_restarted(self):
		layer, accepted, telemetry, restarted = self._layer()
		fut: Future = Future()
		fut.set_exception(RuntimeError("kaboom"))
		donev = threading.Event()
		layer.layer_task = (fut, donev)
		layer.state = "playing"
		ts = datetime(2024, 1, 1, 8, 0, tzinfo=NY)
		with self.assertLogs("python.task.timer_layer", level="ERROR") as logs:
			layer._async_task_completed(AsyncTaskCompleted(ts, "layer_task", fut, donev))
		self.assertTrue(any("kaboom" in line for line in logs.output), logs.output)
		self.assertIsNone(layer.layer_task)
		errors = [m for m in telemetry.messages if isinstance(m, Telemetry) and m.values.get("state") == "error"]
		self.assertEqual(len(errors), 1)
		self.assertTrue(restarted.wait(2.0))
		self.assertTrue(any(isinstance(m, StartPlayback) for m in accepted))
		self.assertEqual(layer.state, "loaded")

	def test_a_cancelled_layer_task_is_not_restarted(self):
		layer, accepted, _, restarted = self._layer()
		fut: Future = Future()
		fut.cancel()
		donev = threading.Event()
		layer.layer_task = (fut, donev)
		layer._async_task_completed(AsyncTaskCompleted(datetime(2024, 1, 1, 8, 0, tzinfo=NY), "layer_task", fut, donev))
		self.assertIsNone(layer.layer_task)

	def test_a_finished_old_layer_task_does_not_clear_its_replacement(self):
		layer, accepted, _, restarted = self._layer()
		old: Future = Future()
		old.cancel()
		replacement = (Future(), threading.Event())
		layer.layer_task = replacement
		layer._async_task_completed(AsyncTaskCompleted(datetime(2024, 1, 1, 8, 0, tzinfo=NY), "layer_task", old, threading.Event()))
		self.assertIs(layer.layer_task, replacement)
		self.assertFalse(restarted.wait(0.3))
		self.assertEqual(accepted, [])

class TestLayerStop(unittest.TestCase):
	def test_stop_returns_promptly_after_a_task_has_run(self):
		layer = new_layer()
		runs: list = []
		plugin = FakePlugin(FakeClock(datetime(2024, 1, 1, 8, 0, tzinfo=NY)), runs, {}, [])
		layer._evaluate_plugin = lambda t: { "plugin": plugin, "track": t }  # type: ignore
		layer.cm = create_configuration_manager()
		layer.datasources = DataSourceManager({})
		layer.timebase = ConstantTimeOfDay(datetime(2024, 1, 1, 8, 0, tzinfo=NY))
		layer.timer = TimerThreadService(layer.timebase)
		pool = AsyncHttpWorkerPool()
		pool.start()
		layer.task_pool = pool
		try:
			tasks = make_tasks([make_item("a", at(8, 0))])  # due now: runs at once, then waits for the next day
			self.assertTrue(layer._run_layer_task(tasks, layer.timebase.current_time()))
			deadline = time.monotonic() + 3
			while (layer.state != "waiting" or not runs) and time.monotonic() < deadline:
				time.sleep(0.01)
			self.assertEqual(len(runs), 1)
			self.assertEqual(layer.state, "waiting")
			t0 = time.monotonic()
			layer._layer_stop()
			self.assertLess(time.monotonic() - t0, 1.0)
		finally:
			pool.shutdown()

if __name__ == "__main__":
	unittest.main()
