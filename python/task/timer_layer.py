import asyncio
import json
from concurrent.futures import CancelledError, Future
from datetime import datetime, timedelta
import logging
import threading
from typing import Any, Any, Mapping, NotRequired, ReadOnly, TypedDict, cast

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import CollectInfoDict, ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import TimerTaskItem, Playlist, generate_schedule, instant, next_day_start
from ..model.schedule_loader import ScheduleLoaderDict
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PluginAsync, PluginExecutionContext
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..task.basic_task import DispatcherTask
from ..task.display_messages import DisplaySettings, OverlayDefinition, OverlayImage, OverlayRevoke, OverlayZones, PriorityImage
from ..task.coalescer import Coalescer
from ..task.messages import AsyncTaskCompleted, BasicMessage, ConfigurationChanged, QuitMessage, ReloadSchedules, Telemetry
from ..task.protocols import IProvideTimer, IRequireShutdown, MessageSink
from ..task.configure_event import ConfigureEvent
from ..task.playlist_layer import NextTrack, StartPlayback
from ..task.message_router import MessageRouter
from ..task.timer import IProvideTimer, TimerThreadService
from ..model.theme import ThemeInputs, current_inputs
from ..utils.error_image import render_error_image, safe_reason

class PlaylistStateDict(TypedDict):
	current_playlist: Playlist
	current_track_index: int
	current_track: TimerTaskItem
	schedule_ts: datetime|None

class EvaluatePluginDict(TypedDict):
	plugin: ReadOnly[PluginAsync|None]
	track: ReadOnly[TimerTaskItem]
	error: NotRequired[str]

class TelemetryDict(TypedDict):
	state: ReadOnly[str]
	current_playlist: ReadOnly[Playlist|None]
	current_track: ReadOnly[TimerTaskItem]
	current_track_index: ReadOnly[int]
	schedule_ts: ReadOnly[datetime|None]

class TimerLayer(DispatcherTask):
	# An entry that is reached later than its time (an earlier task was still running) is run late when it is at most
	# this late at that moment, in order; one that is later than that is skipped with a warning.
	LATE_GRACE = timedelta(minutes=5)
	# after the layer task failed, wait this long (real seconds) before starting it again
	RESTART_DELAY_SECONDS = 30.0
	# a burst of schedule file changes (an editor saving several tasks) is one reload, this long after the last change
	RELOAD_DELAY_SECONDS = 2.0
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager|None = None
		self.tasks: list[ScheduleLoaderDict] = []
		self.plugin_info: list[CollectInfoDict]|None = None
		self.datasources: DataSourceManager|None = None
		self.timer: IProvideTimer|None = None
		self.dimensions:tuple[int,int] = (800,480)
		# the zones the display announced, for overlay plugins and overlay errors
		self.overlay_zones = OverlayZones([])
		self.task_pool: AsyncHttpWorkerPool|None = None
		self.layer_task: tuple[Future, threading.Event] | None = None
		self.shutdownlist: list[IRequireShutdown] = []
		self.timebase: TimeOfDay|None = None
		self.state = 'uninitialized'
		self.startup_done = False
		self._restart_timer: threading.Timer|None = None
		self._reload = Coalescer(self.RELOAD_DELAY_SECONDS, self._request_reload)
		self.logger = logging.getLogger(__name__)
	def _evaluate_plugin(self, track:TimerTaskItem) -> EvaluatePluginDict:
		if self.cm is None:
			errormsg = "Configuration manager is not set."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		if self.plugin_info is None:
			errormsg = "Plugin info is not loaded."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		piname = track.task.plugin_name
		pinfo = next((px for px in self.plugin_info if px["info"]["id"] == piname), None)
		if pinfo is None:
			errormsg = f"Plugin info for '{piname}' not found."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		plugin = self.cm.create_plugin(pinfo)
		if plugin is not None:
#				self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
			if isinstance(plugin, PluginAsync):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{piname}' is not a PluginAsync instance."
				self.logger.error(errormsg)
				return { "plugin": plugin, "track": track, "error": errormsg }
		else:
			errormsg = f"Plugin '{piname}' is not available."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
	def _create_container(self):
		if self.cm is None or self.datasources is None or self.router is None or self.timer is None or self.timebase is None:
			raise ValueError("Cannot create context, one or more required components are None.")
		root = ServiceContainer()
		scm = self.cm.settings_manager()
		stm = self.cm.static_manager()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(StaticConfigurationManager, stm)
		root.add_service(SettingsConfigurationManager, scm)
		root.add_service(DataSourceManager, self.datasources)
		root.add_service(MessageRouter, self.router)
		root.add_service(IProvideTimer, self.timer)
		root.add_service(TimeOfDay, self.timebase)
		root.add_service(MessageSink, self)
		root.add_service(OverlayZones, self.overlay_zones)
		return root
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		self.startup_done = False
		try:
			# validate the schedule before allocating resources
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.tasks = schedule_info.get("tasks", [])

			plugin_info = self.cm.enum_plugins()
			self.plugin_info = plugin_info

			tod = msg.content.isp.get_service(TimeOfDay)
			self.timebase = tod if tod is not None else SystemTimeOfDay()

			ts = msg.content.isp.get_service(IProvideTimer)
			self.timer = ts if ts is not None else TimerThreadService(self.timebase)
			if ts is None and isinstance(self.timer, IRequireShutdown):
				self.shutdownlist.append(self.timer)

			dsm = msg.content.isp.get_service(DataSourceManager)
			if dsm is None:
				datasource_info = self.cm.enum_datasources()
				datasources = self.cm.load_datasources(datasource_info)
				self.logger.info(f"Datasources loaded: {list(datasources.keys())}")
				self.datasources = DataSourceManager(datasources)
			else:
				self.datasources = dsm
			if dsm is None and isinstance(self.datasources, IRequireShutdown):
				self.shutdownlist.append(self.datasources)

			ahwp = msg.content.isp.get_service(AsyncHttpWorkerPool)
			self.task_pool = ahwp if ahwp is not None else AsyncHttpWorkerPool()
			if ahwp is None and isinstance(self.task_pool, IRequireShutdown):
				self.shutdownlist.append(self.task_pool)
				self.task_pool.start()

			self.logger.info(f"schedule loaded")
			self.state = 'loaded'
			msg.notify()
			self.accept(StartPlayback(self.timebase.current_time()))
		except Exception as e:
			self.logger.error(f"Failed to load/validate schedules: {e}", exc_info=True)
			self.state = 'error'
			msg.notify(True, e)
			self._error_with_telemetry(f"ConfigureEvent failed: {e}", msg.timestamp)
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.dimensions = (msg.width, msg.height)
		self.overlay_zones = OverlayZones(msg.overlays)
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.tasks) == 0:
			# nothing scheduled is valid (every timer task document may have been deleted); a later reload can bring tasks
			self.logger.info(f"No timer task documents: nothing is scheduled.")
			return
		if self.timer is None:
			self.logger.error(f"Timer service is not available.")
			return
		self._run_layer_task(self.tasks, msg.timestamp)
	def _theme(self) -> ThemeInputs:
		"""The device theme now, for the error page (the factory theme when there is no configuration)."""
		return current_inputs(self.cm.settings_manager() if self.cm is not None else None)
	def _overlay_zone(self, item: TimerTaskItem) -> OverlayDefinition|None:
		"""The zone of an overlay task (its plugin has the "layer-overlay" feature and its settings name a zone the display has), else None."""
		info = next((px["info"] for px in (self.plugin_info or []) if px["info"].get("id") == item.task.plugin_name), None)
		if info is None or "layer-overlay" not in (info.get("features") or []):
			return None
		content = item.task.content if isinstance(item.task.content, dict) else {}
		zone = content.get("zone")
		return self.overlay_zones.get(zone) if isinstance(zone, str) else None
	async def _show_error(self, item: TimerTaskItem, reason: str, ts: datetime) -> None:
		"""
		A task that failed shows an error page where it would have shown its image, as the message it would have sent:
		an overlay task in its zone, as an overlay (until the task succeeds, or is disabled or removed); any other task full screen,
		for its `slideMinutes` (one minute if it has none), as the interstitial does.
		"""
		try:
			stm = self.cm.static_manager() if self.cm is not None else None
			zone = self._overlay_zone(item)
			if zone is not None:
				image = await asyncio.to_thread(render_error_image, stm, zone.dimensions, item.title, [reason], self._theme(), True)
				self.router.send("display", OverlayImage(ts, item.id, zone.name, f"Error: {item.title}", image))
				return
			image = await asyncio.to_thread(render_error_image, stm, self.dimensions, item.title, [reason], self._theme())
			content = item.task.content if isinstance(item.task.content, dict) else {}
			minutes = content.get("slideMinutes")
			duration = timedelta(minutes=float(minutes) if isinstance(minutes, (int, float)) and minutes > 0 else 1.0)
			self.router.send("display", PriorityImage(ts, f"Error: {item.title}", image, duration))
		except Exception as e:
			self.logger.error(f"Could not show the error page for task '{item.title}': {type(e).__name__}")
	async def _run_task_item(self, isp: IServiceProvider, tod: TimeOfDay, item: TimerTaskItem, kind: str, index: int, playlist: Playlist|None, sched_ts: datetime|None):
		"""Run one task item's plugin and report telemetry. Failures are reported, never raised (the layer keeps going)."""
		plugin_eval = self._evaluate_plugin(item)
		plugin = cast(PluginAsync|None, plugin_eval.get("plugin", None))
		if plugin is None:
			self.logger.error(f"Cannot start {kind} task, plugin '{item.task.plugin_name}' for task '{item.title}' is not available.")
			await self._show_error(item, f"Plugin '{item.task.plugin_name}' is not available", tod.current_time())
			return
		try:
			self.logger.info(f"Starting {kind} task '{item.title}' using plugin '{item.task.plugin_name}'.")
			# this task's own event: the one passed to the layer task is the layer's, and is set when the layer ends
			task_done = threading.Event()
			context = PluginExecutionContext(isp, self.dimensions, tod.current_time())
			plugin_result = await plugin.task_async(context, item, task_done)
			self.state = 'playing'
			self.logger.info(f"{kind.capitalize()} task '{item.title}' completed with result: {plugin_result}")
			telemetry: TelemetryDict = {
				"state": self.state,
				"current_playlist": playlist,
				"current_track": item,
				"current_track_index": index,
				"schedule_ts": sched_ts
			}
			self.router.send("telemetry", Telemetry(tod.current_time(), "timer_layer", cast(Mapping[str,Any], telemetry)))
		except Exception as e:
			self.state = 'error'
			self._error_with_telemetry(f"Error during {kind} task '{item.title}': {e}", tod.current_time())
			await self._show_error(item, safe_reason(e), tod.current_time())
	async def _layer_task(self, isp: IServiceProvider, tasks: list[ScheduleLoaderDict], donev: threading.Event) -> BasicMessage|None:
		"""
		Runs until it is cancelled: the startup tasks once, then each local day's schedule in turn.
		When a day's entries are exhausted it waits for the next midnight and renders that day. Entries are run in time order;
		one that was missed while an earlier task ran is run late if it is within LATE_GRACE, else skipped with a warning.
		"""
		try:
			tod = isp.required(TimeOfDay)
			timer = isp.required(IProvideTimer)
			enabled_task_items = self._get_enabled_tasks(tasks)
			# the day to render first starts now, before the startup tasks (which may take a while)
			cursor = tod.current_time()
			# startup tasks loop, once per start-up (a restart after an error does not repeat them)
			initial_playlist:Playlist|None = self._startup_playlist(enabled_task_items)
			if self.startup_done:
				pass
			elif initial_playlist is None:
				self.logger.info(f"No startup playlist.")
			else:
				self.startup_done = True
				for index, item in enumerate(initial_playlist.items):
					await self._run_task_item(isp, tod, cast(TimerTaskItem, item), "startup", index, initial_playlist, None)
			self.startup_done = True
			# daily loop
			while True:
				rendered_schedule = self._next_scheduled_playlist(cursor, enabled_task_items)
				for sched_ts, task_item in rendered_schedule:
					now = tod.current_time()
					delta = timedelta(seconds=instant(sched_ts) - instant(now))
					if delta.total_seconds() > 0:
						matching = [x for ts, x in rendered_schedule if instant(ts) == instant(sched_ts)]
						self.logger.info(f"Waiting for {len(matching)} scheduled task(s) at {sched_ts} (in {delta}).")
						self.state = 'waiting'
						telemetry2 = {
							"state": self.state,
							"schedule_ts": sched_ts,
							"now": now,
							"delta": delta,
						}
						self.router.send("telemetry", Telemetry(now, "timer_layer", cast(Mapping[str,Any], telemetry2)))
						await timer.sleep(delta)
						self.logger.info(f"Scheduled task time reached: {sched_ts}, actual: {tod.current_time()}.")
					elif -delta > self.LATE_GRACE:
						self.logger.warning(f"Skipping scheduled task '{task_item.title}' ({task_item.id}) at {sched_ts}: it is {-delta} late, more than {self.LATE_GRACE}.")
						continue
					else:
						self.logger.info(f"Running scheduled task '{task_item.title}' ({task_item.id}) {-delta} late.")
					await self._run_task_item(isp, tod, task_item, "scheduled", -1, None, sched_ts)
				# this day is done: continue with the next local day, starting at its midnight
				cursor = next_day_start(cursor)
				now = tod.current_time()
				delta = timedelta(seconds=instant(cursor) - instant(now))
				if delta.total_seconds() > 0:
					self.logger.info(f"No more scheduled tasks for the day, waiting for {cursor} (in {delta}).")
					self.state = 'waiting'
					await timer.sleep(delta)
				else:
					# catching up after a long task or a clock jump: still give other tasks (and cancellation) a turn
					await asyncio.sleep(0)
		finally:
			donev.set()
	def _run_layer_task(self, tasks: list[ScheduleLoaderDict], timestamp: datetime):
		if self.task_pool is None:
			self.logger.error(f"No task pool available to invoke plugin start.")
			return False
		try:
			donev = threading.Event()
			def submit_callback(fut):
				if not self.is_stopped():
					self.accept(AsyncTaskCompleted(timestamp, "layer_task", fut, donev))
			sc = self._create_container()
			fut = self.task_pool.submit(self._layer_task, sc, tasks, donev, callback=submit_callback)
			self.layer_task = (fut, donev)
			return True
		except Exception as e:
			self.state = "error"
			self._error_with_telemetry(f"Error invoke start layer task: {e}", timestamp)
			return False
	def _layer_stop(self):
		if self.layer_task is None:
			return
		fut, donev = self.layer_task
		if not fut.done():
			self.logger.info(f"Layer task still running, cancel...")
			fut.cancel()
			self.logger.info(f"Waiting for layer task to complete...")
			donev.wait(timeout=2.0)
		else:
			self.logger.info(f"Layer task completed.")
		self.layer_task = None
	def _async_task_completed(self, msg: AsyncTaskCompleted):
		if not msg.fut.done():
			self.logger.info(f"Plugin task still running, cancel...")
			msg.fut.cancel()
			self.logger.info(f"Waiting for plugin task to complete...")
			msg.donev.wait(timeout=2.0)
			return
		# only the layer task this message is about: a reload may have started its replacement already
		if msg.token == "layer_task" and (self.layer_task is None or self.layer_task[1] is msg.donev):
			self.layer_task = None
		if msg.fut.cancelled():
			self.logger.info(f"Plugin task was cancelled.")
			return
		try:
			rmsg = msg.fut.result()
		except CancelledError:
			self.logger.info(f"Plugin task was cancelled.")
			return
		except Exception as e:
			# the layer task died; keep the display alive by starting it again after a pause
			self.state = 'error'
			self.logger.error(f"Layer task failed: {type(e).__name__}: {e}", exc_info=(type(e), e, e.__traceback__))
			self._error_with_telemetry(f"Layer task failed: {e}", msg.timestamp, log=False)
			self._schedule_restart(msg.timestamp)
			return
		self.logger.info(f"Plugin task result: {rmsg}")
		if rmsg is not None:
			# handle any messages returned by the plugin task if needed
			self.accept(rmsg)
		elif msg.token == "layer_task":
			# the layer task only ends by being cancelled; if it returned, start it again
			self.logger.warning(f"Layer task ended unexpectedly, restarting.")
			self._schedule_restart(msg.timestamp)
	def _configuration_changed(self, msg: ConfigurationChanged):
		if msg.area == "schedules" and self.cm is not None and self.timebase is not None and not self.is_stopped():
			self._reload.trigger()
	def _request_reload(self):
		"""On the coalescer's thread: hand the work to the task's own thread."""
		if self.is_stopped() or self.timebase is None:
			return
		try:
			self.accept(ReloadSchedules(self.timebase.current_time()))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the reload.")
	@staticmethod
	def _signature(tasks: list[ScheduleLoaderDict]) -> str:
		return json.dumps([t["info"].to_dict() for t in tasks if t.get("info") is not None], sort_keys=True, default=str)
	def _reload_schedules(self, msg: ReloadSchedules):
		"""Re-read the schedules and re-plan. Startup tasks do not run again. A schedule that does not load keeps the one in use."""
		if self.cm is None or self.timebase is None or self.state in ('uninitialized', 'stopped'):
			return
		try:
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
		except Exception as e:
			self.logger.warning(f"'{self.name}' the changed schedules do not load, keeping the ones in use: {e}")
			self._error_with_telemetry(f"The changed schedules do not load: {e}", msg.timestamp, log=False)
			return
		new_tasks = schedule_info.get("tasks", [])
		if self._signature(new_tasks) == self._signature(self.tasks):
			self.logger.info(f"'{self.name}' schedules changed, timer tasks are the same.")
			return
		self.logger.info(f"'{self.name}' timer tasks changed, re-planning.")
		# a task that is gone or disabled takes its overlay with it (a revoke for a task that has none does nothing)
		kept = { item.id for item in self._get_enabled_tasks(new_tasks) }
		for item in self._get_enabled_tasks(self.tasks):
			if item.id not in kept:
				self.router.send("display", OverlayRevoke(msg.timestamp, item.id))
		if self._restart_timer is not None:
			self._restart_timer.cancel()
			self._restart_timer = None
		self._layer_stop()
		self.tasks = new_tasks
		self.state = 'loaded'
		self.accept(StartPlayback(self.timebase.current_time()))
	def _schedule_restart(self, timestamp: datetime):
		"""Send StartPlayback to ourselves after RESTART_DELAY_SECONDS (real time), unless we have been stopped meanwhile."""
		def restart():
			if self.is_stopped():
				return
			try:
				self.state = 'loaded'
				self.accept(StartPlayback(self.timebase.current_time() if self.timebase is not None else timestamp))
			except Exception as e:
				self.logger.error(f"'{self.name}' restart failed: {e}")
		if self._restart_timer is not None:
			self._restart_timer.cancel()
		self.state = 'loaded'
		self._restart_timer = threading.Timer(self.RESTART_DELAY_SECONDS, restart)
		self._restart_timer.daemon = True
		self._restart_timer.start()
	def _error_with_telemetry(self, emsg:str, msg_ts:datetime, log: bool = True):
		if log:
			self.logger.error(emsg, exc_info=True)
		self.router.send("telemetry", Telemetry(msg_ts, "timer_layer", cast(Mapping[str,Any], {
			"state": "error",
			"message": emsg,
			'current_playlist': None,
			'current_track_index': None,
			'current_track': None,
			'schedule_ts': None
		})))
	def _get_enabled_tasks(self, tasks:list[ScheduleLoaderDict]) -> list[TimerTaskItem]:
		task_items: list[TimerTaskItem] = []
		for sched in tasks:
			info = sched.get("info") if isinstance(sched, dict) else getattr(sched, 'info', None)
			if info is None:
				continue
			# If info is a TimerTasks instance, it has an .items attribute
			items = getattr(info, 'items', None)
			if items:
				task_items.extend(items)
		# Filter only enabled tasks into a separate list
		enabled_task_items: list[TimerTaskItem] = [t for t in task_items if getattr(t, 'enabled', False)]
		return enabled_task_items
	def _startup_playlist(self, enabled_task_items: list[TimerTaskItem]) -> Playlist|None:
		startup_task_items: list[TimerTaskItem] = [
			t for t in enabled_task_items
			if getattr(t, 'trigger', {}).get("on_startup", None) is True
		]
		if len(startup_task_items) == 0:
			return None
		startup_playlist = Playlist("startup", "Startup Tasks", items=startup_task_items)
		return startup_playlist
	def _next_scheduled_playlist(self, now: datetime, enabled_task_items: list[TimerTaskItem]) -> list[tuple[datetime, TimerTaskItem]]:
		"""The (time, item) entries of `now`'s local day from `now` on, in time order. Items with a malformed trigger are skipped with a warning."""
		scheduled: list[tuple[datetime, TimerTaskItem]] = []
		for item in enabled_task_items:
			problems = item.validate_trigger()
			if problems:
				self.logger.warning(f"Skipping task '{item.title}' ({item.id}) while computing the schedule: {'; '.join(problems)}")
				continue
			try:
				for trigger_ts in generate_schedule(now, item.trigger, include_now=True):
					scheduled.append((trigger_ts, item))
			except Exception as e:
				self.logger.warning(f"Skipping task '{item.title}' ({item.id}) while computing the schedule: {e}")
		# by absolute time (a stable sort keeps the schedule order for entries at the same time)
		scheduled.sort(key=lambda pair: instant(pair[0]))
		return scheduled
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting playback.")
		self._reload.cancel()
		if self._restart_timer is not None:
			self._restart_timer.cancel()
			self._restart_timer = None
		try:
			try:
				self._layer_stop()
			except Exception as e:
				self.logger.error(f"'{self.name}' Error stopping active plugin during quit: {e}", exc_info=True)
			self.state = 'stopped'
			# we tracked whether WE CREATED these things; shut them down
			for shutdown_item in self.shutdownlist:
				try:
					shutdown_item.shutdown()
				except Exception as e:
					self.logger.error(f"'{self.name}' Error during shutdown of {shutdown_item}: {e}", exc_info=True)
			self.shutdownlist.clear()
			if self.timer is not None:
				self.timer = None
			if self.datasources is not None:
				self.datasources = None
			if self.task_pool is not None:
				self.task_pool = None
		except Exception as e:
			self.logger.error(f"'{self.name}' quit.unexpected: {e}", exc_info=True)
		finally:
			super().quitMsg(msg)
		pass