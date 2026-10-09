"""Robustness tests for the task layer (GROUP C of issue #61): shutdown, logging, timeouts, bounded queues.

None of these need the internet, real hardware, or the plugins/datasources of the test storage.
"""
import asyncio
import importlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image

from ..display.display_base import DisplayBase
from ..display.mock_display import MockDisplay
from ..model.time_of_day import TimeOfDay
from ..plugins.plugin_base import PluginAsync
from ..task import async_http_worker_pool as ahwp_module
from ..task.application import Application
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..task.async_worker_pool import AsyncWorkerPool
from ..task.basic_task import CoreTask
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.display import Display
from ..task.display_messages import DisplayImage, PriorityImage
from ..task.message_router import MessageRouter, Route
from ..task.messages import AsyncTaskCompleted, BasicMessage, QuitMessage, Telemetry
from ..task.playlist_layer import PlaylistLayer, StartPlayback
from ..task.telemetry_sink import TelemetrySink
from .utils import ConstantTimeOfDay, RecordingTask

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def now() -> datetime:
	return datetime.now().astimezone()

def run_bounded(fn, timeout: float = 5.0):
	"""Run fn on a helper thread; fail (instead of hanging the suite) when it does not finish."""
	box: dict[str, Any] = {}
	def target():
		try:
			box["result"] = fn()
		except BaseException as e:
			box["error"] = e
	th = threading.Thread(target=target, daemon=True)
	th.start()
	th.join(timeout)
	if th.is_alive():
		raise AssertionError(f"did not finish within {timeout}s")
	if "error" in box:
		raise box["error"]
	return box.get("result")

class CapturedRecords(logging.Handler):
	"""Collects records and formats them the way a real handler would (so a bad format call shows up)."""
	def __init__(self):
		super().__init__(logging.DEBUG)
		self.messages: list[tuple[int, str]] = []
	def emit(self, record: logging.LogRecord):
		try:
			self.messages.append((record.levelno, record.getMessage()))
		except Exception as e:
			self.messages.append((record.levelno, f"<<unformattable: {e}>> {record.msg}"))

@contextmanager
def capture_logs(name: str = "python"):
	handler = CapturedRecords()
	lg = logging.getLogger(name)
	old_level = lg.level
	lg.addHandler(handler)
	lg.setLevel(logging.DEBUG)
	try:
		yield handler
	finally:
		lg.removeHandler(handler)
		lg.setLevel(old_level)

class ImportTests(unittest.TestCase):
	def test_import_task_modules_prints_nothing(self):
		# importing must not run demos or print: the task modules, including the two worker pools
		for module in ("basic_task", "async_worker_pool", "async_http_worker_pool"):
			with self.subTest(module=module):
				result = subprocess.run([sys.executable, "-c", f"import python.task.{module}"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
				self.assertEqual(result.returncode, 0, result.stderr)
				self.assertEqual(result.stdout, "")

class BrokenLoggingCalls(unittest.TestCase):
	def test_core_task_unhandled_logs_exception_text(self):
		class Boom(CoreTask):
			def _dispatch(self, msg: BasicMessage):
				raise RuntimeError("boom-text")
		task = Boom("boomer")
		with capture_logs() as cap:
			task.start()
			task.accept(BasicMessage(now()))
			task.accept(QuitMessage(now()))
			task.join(timeout=3)
		errors = [m for lvl, m in cap.messages if lvl >= logging.ERROR]
		self.assertTrue(any("boom-text" in m for m in errors), errors)
		self.assertFalse(any("unformattable" in m for m in errors), errors)

	def _display_with_failing_cm(self) -> Display:
		d = Display("d", MessageRouter())
		d.cm = MagicMock()
		d.cm.settings_manager.side_effect = RuntimeError("cm-failure-text")
		d.display = MagicMock()
		d.task_pool = MagicMock()
		d.commitq = MagicMock()
		d.priorityq = MagicMock()
		return d

	def test_display_image_logs_exception_text(self):
		d = self._display_with_failing_cm()
		with capture_logs() as cap:
			d._display_image(DisplayImage(now(), "t", Image.new("RGB", (4, 4))))
		errors = [m for lvl, m in cap.messages if lvl >= logging.ERROR]
		self.assertTrue(any("cm-failure-text" in m for m in errors), errors)
		self.assertFalse(any("unformattable" in m for m in errors), errors)

	def test_priority_image_logs_exception_text(self):
		d = self._display_with_failing_cm()
		from datetime import timedelta
		with capture_logs() as cap:
			d._priority_image(PriorityImage(now(), "t", Image.new("RGB", (4, 4)), timedelta(seconds=1)))
		errors = [m for lvl, m in cap.messages if lvl >= logging.ERROR]
		self.assertTrue(any("cm-failure-text" in m for m in errors), errors)
		self.assertFalse(any("unformattable" in m for m in errors), errors)

	def test_no_logger_call_has_a_stray_argument(self):
		"""logger.error("text", e) with no placeholder is a logging error; look for the pattern in the sources."""
		import re
		pattern = re.compile(r"""logger\.\w+\(\s*f?(["'])[^"']*\1\s*,\s*\w+\s*\)""")
		offenders = []
		for base, _, files in os.walk(os.path.join(REPO_ROOT, "python")):
			if ".storage" in base or "tests" in base.split(os.sep):
				continue
			for fn in files:
				if fn.endswith(".py"):
					path = os.path.join(base, fn)
					with open(path, encoding="utf-8") as f:
						for ix, line in enumerate(f, 1):
							if pattern.search(line) and "%" not in line:
								offenders.append(f"{path}:{ix}")
		self.assertEqual(offenders, [])

class FailingMockDisplay(MockDisplay):
	def initialize(self, cm):
		raise RuntimeError("init-failed")

def fake_cm(display_type: str = "mock", **settings) -> MagicMock:
	cm = MagicMock()
	cob = MagicMock()
	cob.get.return_value = ("rev", {"display_type": display_type, **settings})
	cm.settings_manager.return_value.open.return_value = cob
	return cm

class DisplayShutdownTests(unittest.TestCase):
	def test_quit_after_failed_configuration_shuts_display_down(self):
		d = Display("d", MessageRouter())
		shut = threading.Event()
		class Fake(FailingMockDisplay):
			def shutdown(self):
				shut.set()
		notified: list[Any] = []
		sink = MagicMock()
		sink.accept.side_effect = lambda m: notified.append(m)
		with patch("python.task.display.MockDisplay", Fake):
			d.start()
			isp = MagicMock()
			isp.get_service.return_value = None
			d.accept(ConfigureEvent(now(), ConfigureOptions(fake_cm(), isp), "display", sink))
			d.accept(QuitMessage(now()))
			d.join(timeout=5)
		self.assertFalse(d.is_alive())
		self.assertTrue(shut.is_set(), "display.shutdown() was not called")
		self.assertEqual(len(notified), 1)
		self.assertTrue(notified[0].error)

	def test_quit_shuts_pool_down_even_when_display_shutdown_raises(self):
		d = Display("d", MessageRouter())
		pool = MagicMock()
		disp = MagicMock()
		disp.shutdown.side_effect = RuntimeError("display-shutdown-failed")
		d.task_pool = pool
		d.display = disp
		with capture_logs():
			d.quitMsg(QuitMessage(now()))
		pool.shutdown.assert_called_once()
		disp.shutdown.assert_called_once()

	def test_quit_shuts_display_down_even_when_pool_shutdown_raises(self):
		d = Display("d", MessageRouter())
		pool = MagicMock()
		pool.shutdown.side_effect = RuntimeError("pool-failed")
		disp = MagicMock()
		d.task_pool = pool
		d.display = disp
		with capture_logs():
			d.quitMsg(QuitMessage(now()))
		disp.shutdown.assert_called_once()

class FakePlugin:
	"""A PluginAsync that awaits a long sleep."""
	def __init__(self, entered: threading.Event):
		self.entered = entered
	@property
	def id(self) -> str:
		return "slow"
	@property
	def name(self) -> str:
		return "slow"
	async def task_async(self, context, track, done: threading.Event):
		self.entered.set()
		await asyncio.sleep(60)
		return None

class FakeTrack:
	plugin_name = "slow"
	title = "slow track"
	content = None

class PlaylistLayerRobustness(unittest.TestCase):
	def _layer(self, playlists, plugin: PluginAsync|None = None) -> PlaylistLayer:
		router = MessageRouter()
		layer = PlaylistLayer("pl", router)
		layer.cm = MagicMock()
		layer.cm.create_plugin.return_value = plugin
		layer.plugin_info = [{"info": {"id": "slow"}}]
		layer.datasources = MagicMock()
		layer.timebase = ConstantTimeOfDay(now())
		layer.timer = MagicMock()
		layer.playlists = playlists
		layer.state = "loaded"
		layer.task_pool = AsyncHttpWorkerPool()
		layer.task_pool.start()
		self.addCleanup(layer.task_pool.shutdown)
		return layer

	def test_task_stop_returns_promptly_for_a_sleeping_plugin(self):
		entered = threading.Event()
		pl = MagicMock()
		pl.name = "p"
		pl.items = [FakeTrack()]
		layer = self._layer([{"info": pl}], FakePlugin(entered))
		self.assertTrue(layer._run_layer_task(layer.playlists, now()))
		self.assertTrue(entered.wait(3), "plugin never started")
		t0 = time.monotonic()
		layer._task_stop()
		elapsed = time.monotonic() - t0
		self.assertLess(elapsed, 0.5, f"cancel took {elapsed:.2f}s")
		self.assertIsNone(layer.layer_task)

	def test_layer_coroutine_failure_is_reported_and_playback_restarts_with_backoff(self):
		# a playlist entry whose info is None raises outside the per-track try
		layer = self._layer([{"info": None}])
		layer.BACKOFF_INITIAL_SECONDS = 0.2
		telemetry: list[Telemetry] = []
		tsink = MagicMock()
		tsink.accept.side_effect = lambda m: telemetry.append(m)
		layer.router.addRoute(Route("telemetry", [tsink]))
		layer.start()
		try:
			layer.accept(StartPlayback(now()))
			time.sleep(1.6)
		finally:
			layer.accept(QuitMessage(now()))
			layer.join(timeout=5)
		errors = [t for t in telemetry if t.values.get("state") == "error"]
		self.assertGreaterEqual(len(errors), 2, "the layer did not restart after the failure")
		self.assertLess(len(errors), 12, "the restart is not backing off")
		self.assertFalse(layer.is_alive())

class TelemetrySinkTests(unittest.TestCase):
	def test_queue_is_bounded_and_keeps_newest(self):
		sink = TelemetrySink()
		limit = sink.MAX_MESSAGES
		for ix in range(5000):
			sink.accept(Telemetry(now(), "n", {"i": ix}))
		self.assertLessEqual(len(sink), limit)
		first = sink.receive()
		self.assertIsNotNone(first)
		self.assertEqual(first.values["i"], 5000 - limit)
		count = 1
		while sink.receive() is not None:
			count += 1
		self.assertEqual(count, limit)
		self.assertIsNone(sink.receive())

	def test_concurrent_accept(self):
		sink = TelemetrySink()
		def push():
			for ix in range(2000):
				sink.accept(Telemetry(now(), "n", {"i": ix}))
		threads = [threading.Thread(target=push) for _ in range(4)]
		for t in threads: t.start()
		for t in threads: t.join()
		self.assertLessEqual(len(sink), sink.MAX_MESSAGES)

class PoolRobustness(unittest.TestCase):
	def test_http_pool_start_fails_clearly_when_client_constructor_raises(self):
		pool = AsyncHttpWorkerPool()
		with patch.object(ahwp_module.httpx, "AsyncClient", side_effect=RuntimeError("client-ctor")):
			with self.assertRaises(RuntimeError) as cm:
				run_bounded(lambda: pool.start(), 5)
		self.assertIn("client-ctor", str(cm.exception))

	def test_http_pool_shutdown_completes_when_aclose_raises(self):
		class BadClient:
			def __init__(self, *a, **k): pass
			async def aclose(self):
				raise RuntimeError("aclose-failed")
		pool = AsyncHttpWorkerPool()
		with patch.object(ahwp_module.httpx, "AsyncClient", BadClient):
			pool.start()
			run_bounded(lambda: pool.shutdown(), 4)
		self.assertFalse(pool.thread.is_alive())

	def test_worker_pool_shutdown_does_not_wait_forever_for_a_blocked_loop(self):
		pool = AsyncWorkerPool()
		pool.SHUTDOWN_JOIN_TIMEOUT = 0.3
		pool.start()
		started = threading.Event()
		async def blocker():
			started.set()
			time.sleep(1.5)	# a synchronous call: blocks the loop
		pool.submit(blocker())
		self.assertTrue(started.wait(2))
		t0 = time.monotonic()
		pool.shutdown()
		self.assertLess(time.monotonic() - t0, 1.0)

	def test_worker_pool_shutdown_before_start_is_safe(self):
		pool = AsyncWorkerPool()
		run_bounded(lambda: pool.shutdown(), 3)

class SlowDisplay(DisplayBase):
	def __init__(self, delay: float):
		super().__init__("slow")
		self.delay = delay
		self.rendered = 0
	def initialize(self, cm):
		return (8, 8)
	def shutdown(self):
		pass
	def render(self, img, id, title=None):
		time.sleep(self.delay)
		self.rendered += 1

class FakePackage:
	version = 1
	def render(self):
		return Image.new("RGB", (8, 8)), "title"

class FakeCompositor:
	def __init__(self):
		self.calls = 0
	def commit(self):
		self.calls += 1
		return FakePackage()

class DisplayLoopTests(unittest.TestCase):
	def test_render_does_not_block_the_loop_and_quit_is_fast(self):
		d = Display("d", MessageRouter())
		pool = AsyncWorkerPool()
		pool.start()
		d.task_pool = pool
		disp = SlowDisplay(1.0)
		donev = threading.Event()
		ticks: list[float] = []
		renderq: dict[str, Any] = {}
		async def setup():
			renderq["q"] = asyncio.Queue()
			async def ticker():
				while True:
					ticks.append(time.monotonic())
					await asyncio.sleep(0.05)
			renderq["ticker"] = asyncio.ensure_future(ticker())
			await renderq["q"].put(BasicMessage(now()))
		pool.submit(setup()).result(2)
		fut = pool.submit(d._task_render_and_display(renderq["q"], FakeCompositor(), disp, None, donev))
		time.sleep(0.5)	# the render (1s) is under way
		during = [t for t in ticks]
		self.assertGreaterEqual(len(during), 6, f"the loop only ticked {len(during)} times during the render")
		d.task_render = (fut, donev)
		t0 = time.monotonic()
		d.quitMsg(QuitMessage(now()))
		self.assertLess(time.monotonic() - t0, 1.0)
		self.assertTrue(donev.is_set())

	def test_an_image_identical_to_the_one_shown_is_not_drawn_again(self):
		from ..task import display as display_module
		colors = ["black", "black", "white", "white", "black"]
		class Packages:
			def __init__(self):
				self.i = 0
			def commit(self):
				color = colors[self.i]
				self.i += 1
				class P:
					version = 1
					def render(self_):
						return Image.new("RGB", (8, 8), color), "title"
				return P()
		d = Display("d", MessageRouter())
		pool = AsyncWorkerPool()
		pool.start()
		d.task_pool = pool
		disp = SlowDisplay(0.0)
		donev = threading.Event()
		real_sleep = asyncio.sleep
		async def quick_sleep(delay, *a, **k):
			await real_sleep(0)
		q: dict[str, Any] = {}
		async def setup():
			q["q"] = asyncio.Queue()
			for _ in colors:
				await q["q"].put(BasicMessage(now()))
		pool.submit(setup()).result(2)
		with patch.object(display_module.asyncio, "sleep", quick_sleep):
			fut = pool.submit(d._task_render_and_display(q["q"], Packages(), disp, None, donev))
			deadline = time.monotonic() + 3
			while time.monotonic() < deadline and not q["q"].empty():
				time.sleep(0.01)
			time.sleep(0.2)
		d.task_render = (fut, donev)
		d.quitMsg(QuitMessage(now()))
		# black, (black again: skipped), white, (white again: skipped), black
		self.assertEqual(disp.rendered, 3)

	def test_blocked_pool_does_not_freeze_display_image(self):
		d = Display("d", MessageRouter())
		d.RESULT_TIMEOUT_SECONDS = 0.2
		d.cm = fake_cm()
		d.display = MagicMock()
		d.commitq = MagicMock()
		d.resolution = (8, 8)
		pool = MagicMock()
		never = Future()
		pool.submit.return_value = never
		d.task_pool = pool
		def go():
			d._display_image(DisplayImage(now(), "t", Image.new("RGB", (8, 8))))
		with capture_logs() as cap:
			run_bounded(go, 3)
		self.assertTrue(any("timed out" in m.lower() for lvl, m in cap.messages), cap.messages)

	def test_blocked_pool_does_not_freeze_priority_image(self):
		from datetime import timedelta
		d = Display("d", MessageRouter())
		d.RESULT_TIMEOUT_SECONDS = 0.2
		d.cm = fake_cm()
		d.display = MagicMock()
		d.priorityq = MagicMock()
		pool = MagicMock()
		pool.submit.return_value = Future()
		d.task_pool = pool
		with capture_logs() as cap:
			run_bounded(lambda: d._priority_image(PriorityImage(now(), "t", Image.new("RGB", (8, 8)), timedelta(seconds=1))), 3)
		self.assertTrue(any("timed out" in m.lower() for lvl, m in cap.messages), cap.messages)

	def test_cancelled_commit_timer_is_logged_as_cancelled(self):
		d = Display("d", MessageRouter())
		pool = AsyncWorkerPool()
		pool.start()
		self.addCleanup(pool.shutdown)
		donev = threading.Event()
		holder: dict[str, Any] = {}
		async def mk():
			holder["c"] = asyncio.Queue()
			holder["r"] = asyncio.Queue()
		pool.submit(mk()).result(2)
		fut = pool.submit(d._task_commit_timer(holder["c"], holder["r"], ConstantTimeOfDay(now()), donev))
		time.sleep(0.2)
		with capture_logs() as cap:
			fut.cancel()
			self.assertTrue(donev.wait(2))
			time.sleep(0.1)
		self.assertTrue(any("cancelled" in m for lvl, m in cap.messages), cap.messages)

	def test_commit_timer_does_not_spin_on_a_persistent_error(self):
		d = Display("d", MessageRouter())
		d.ERROR_BACKOFF_SECONDS = 0.1
		pool = AsyncWorkerPool()
		pool.start()
		self.addCleanup(pool.shutdown)
		calls = {"n": 0}
		class BadQueue:
			async def get(self):
				calls["n"] += 1
				if calls["n"] == 1:
					return BasicMessage(now())
				raise RuntimeError("queue-broken")
			def task_done(self):
				pass
		donev = threading.Event()
		fut = pool.submit(d._task_commit_timer(BadQueue(), MagicMock(), ConstantTimeOfDay(now()), donev))
		with capture_logs():
			time.sleep(0.5)
			fut.cancel()
			donev.wait(2)
		self.assertLess(calls["n"], 30, f"{calls['n']} attempts in 0.5s: hot loop")

class ApplicationStopTests(unittest.TestCase):
	def test_handle_stop_skips_threads_that_never_started(self):
		app = Application("a")
		started = RecordingTask("started")
		started.start()
		app.timer_layer = started	# type: ignore[assignment]
		app.playlist_layer = RecordingTask("never-playlist")	# type: ignore[assignment]
		app.display = RecordingTask("never-display")	# type: ignore[assignment]
		run_bounded(lambda: app._handleStop(now()), 5)
		started.join(timeout=3)
		self.assertFalse(started.is_alive(), "the started task was not stopped")

	def test_handle_stop_continues_after_a_failing_join(self):
		app = Application("a")
		bad = MagicMock()
		bad.is_alive.return_value = False
		bad.ident = 1
		bad.join.side_effect = RuntimeError("join-failed")
		app.playlist_layer = bad
		display = RecordingTask("display")
		display.start()
		app.display = display	# type: ignore[assignment]
		run_bounded(lambda: app._handleStop(now()), 5)
		display.join(timeout=3)
		self.assertFalse(display.is_alive())

class RouterTests(unittest.TestCase):
	def test_send_to_stopped_task_is_not_an_error(self):
		task = RecordingTask("t")
		task.start()
		task.accept(QuitMessage(now()))
		task.join(timeout=3)
		router = MessageRouter()
		router.addRoute(Route("r", [task]))
		with capture_logs() as cap:
			router.send("r", BasicMessage(now()))
		self.assertEqual([m for lvl, m in cap.messages if lvl >= logging.ERROR], [])

class MockDisplayTests(unittest.TestCase):
	def _display(self, folder, clean: bool = False) -> MockDisplay:
		md = MockDisplay("mock")
		md.display_settings = {"mock.outputFolder": folder, "mock.cleanOutputFolder": clean}
		md.output_folder = folder
		return md

	def _initialized(self, **settings) -> MockDisplay:
		md = MockDisplay("mock")
		md.initialize(fake_cm(**{"mock.resolution": [8, 8], **settings}))
		return md

	def test_empty_output_folder_is_inside_the_system_temp_directory(self):
		expected = os.path.join(tempfile.gettempdir(), "eink-billboard-mock")
		self.assertEqual(self._initialized().output_folder, expected)
		self.assertEqual(self._initialized(**{"mock.outputFolder": "  "}).output_folder, expected)

	def test_relative_output_folder_is_inside_the_system_temp_directory(self):
		self.assertEqual(self._initialized(**{"mock.outputFolder": "frames"}).output_folder, os.path.join(tempfile.gettempdir(), "frames"))

	def test_absolute_output_folder_is_used_as_is(self):
		with tempfile.TemporaryDirectory() as other:
			self.assertEqual(self._initialized(**{"mock.outputFolder": other}).output_folder, os.path.normpath(other))

	@unittest.skipIf(os.name == "nt", "a Windows drive path is a real path on Windows")
	def test_windows_drive_path_is_not_a_literal_folder_name_elsewhere(self):
		md = self._initialized(**{"mock.outputFolder": "c:\\Temp\\mock"})
		self.assertEqual(md.output_folder, os.path.join(tempfile.gettempdir(), "eink-billboard-mock"))

	def test_render_writes_only_inside_the_resolved_folder(self):
		from PIL import Image
		with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as cwd:
			before = os.getcwd()
			os.chdir(cwd)
			try:
				md = self._initialized(**{"mock.outputFolder": os.path.join(out, "frames")})
				md.render(Image.new("RGB", (8, 8)), 1, "t")
			finally:
				os.chdir(before)
			self.assertEqual(len(os.listdir(os.path.join(out, "frames"))), 1)
			self.assertEqual(os.listdir(cwd), [])

	def test_factory_default_is_platform_neutral(self):
		import json
		path = os.path.join(os.path.dirname(__file__), "..", "storage", "schemas", "display.json")
		with open(path, encoding="utf-8") as f:
			folder = json.load(f)["default"]["mock.outputFolder"]
		self.assertEqual(folder, "eink-billboard-mock")

	def test_clean_only_removes_files_the_display_created(self):
		with tempfile.TemporaryDirectory() as tmp:
			os.makedirs(os.path.join(tmp, "keepdir"))
			with open(os.path.join(tmp, "keepdir", "inner.txt"), "w") as f: f.write("x")
			with open(os.path.join(tmp, "notes.txt"), "w") as f: f.write("x")
			with open(os.path.join(tmp, "photo.png"), "w") as f: f.write("x")
			with open(os.path.join(tmp, "0007_20200101_000000_old.png"), "w") as f: f.write("x")
			md = self._display(tmp, True)
			md.render(Image.new("RGB", (4, 4)), 1, "new")
			names = sorted(os.listdir(tmp))
			self.assertIn("keepdir", names)
			self.assertIn("notes.txt", names)
			self.assertIn("photo.png", names)
			self.assertNotIn("0007_20200101_000000_old.png", names)
			self.assertTrue(os.path.exists(os.path.join(tmp, "keepdir", "inner.txt")))
			self.assertEqual(len([n for n in names if n.startswith("0001_")]), 1)

	def test_long_titles_do_not_exceed_the_file_name_limit(self):
		with tempfile.TemporaryDirectory() as tmp:
			md = self._display(tmp)
			for title in ("a" * 400, "é" * 300, "日" * 200):
				md.render(Image.new("RGB", (4, 4)), 2, title)
			files = [n for n in os.listdir(tmp) if n.startswith("0002_")]
			self.assertGreaterEqual(len(files), 1)
			for n in files:
				self.assertLessEqual(len(n.encode("utf-8")), 255)

class TkinterWindowTests(unittest.TestCase):
	def test_shutdown_is_safe_when_initialize_never_ran_or_failed(self):
		from ..display.tkinter_window import TkinterWindow
		w = TkinterWindow("tk")
		run_bounded(lambda: w.shutdown(), 3)
		w2 = TkinterWindow("tk")
		with patch("python.display.tkinter_window.tk.Tk", side_effect=RuntimeError("no display")):
			with self.assertRaises(Exception):
				run_bounded(lambda: w2.initialize(fake_cm(**{"mock.resolution": [8, 8]})), 3)
		run_bounded(lambda: w2.shutdown(), 3)

	def test_render_is_marshalled_onto_the_tk_thread(self):
		from ..display.tkinter_window import TkinterWindow
		w = TkinterWindow("tk")
		w.display_settings = {}
		w.root = MagicMock()
		w.image_label = MagicMock()
		with patch("python.display.tkinter_window.ImageTk") as imagetk:
			w.render(Image.new("RGB", (4, 4)), 1, "x")
			# nothing touched Tk from this (the calling) thread
			w.image_label.config.assert_not_called()
			imagetk.PhotoImage.assert_not_called()
			w.root.update.assert_not_called()
			# the Tk thread drains the queue from its mainloop
			w._drain()
			w.image_label.config.assert_called_once()
			imagetk.PhotoImage.assert_called_once()
		w.root.update.assert_not_called()

	def test_shutdown_posts_destroy_to_the_tk_thread(self):
		from ..display.tkinter_window import TkinterWindow
		w = TkinterWindow("tk")
		root = MagicMock()
		w.root = root
		gate = threading.Event()
		# a stand-in Tk thread that only drains the queue
		def tk_main():
			while not gate.is_set():
				w._drain()
				time.sleep(0.01)
		w.tkthread = threading.Thread(target=tk_main, daemon=True)
		w.tkthread.start()
		def stop_when_destroyed():
			while not root.destroy.called:
				time.sleep(0.01)
			gate.set()
		threading.Thread(target=stop_when_destroyed, daemon=True).start()
		run_bounded(lambda: w.shutdown(), 5)
		root.destroy.assert_called_once()
		self.assertIsNone(w.root)

class EntryPointTests(unittest.TestCase):
	def setUp(self):
		self.main = importlib.import_module("python.eink-billboard")

	def test_default_app_path_does_not_depend_on_the_working_directory(self):
		expected = os.path.join(REPO_ROOT, "app", "dist")
		old = os.getcwd()
		with tempfile.TemporaryDirectory() as tmp:
			os.chdir(tmp)
			try:
				args = self.main.parse_args([])
			finally:
				os.chdir(old)
		self.assertEqual(os.path.normcase(args.app), os.path.normcase(expected))

	def test_explicit_app_path_is_relative_to_the_working_directory(self):
		with tempfile.TemporaryDirectory() as tmp:
			old = os.getcwd()
			os.chdir(tmp)
			try:
				args = self.main.parse_args(["--app", "bundle"])
				expected = os.path.abspath("bundle")
			finally:
				os.chdir(old)
		self.assertEqual(args.app, expected)

	def test_storage_help_matches_the_behaviour(self):
		import contextlib, io
		out = io.StringIO()
		with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
			self.main.parse_args(["--help"])
		text = " ".join(out.getvalue().split())
		self.assertNotIn("PY file", text)
		self.assertIn("working directory", text)

class UtilsTests(unittest.TestCase):
	def test_dead_helpers_are_gone(self):
		from ..utils import utils
		for name in ("get_ip_address", "parse_form", "is_connected", "handle_request_files"):
			self.assertFalse(hasattr(utils, name), name)

if __name__ == "__main__":
	unittest.main()
