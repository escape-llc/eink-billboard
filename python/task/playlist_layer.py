import asyncio
from asyncio import CancelledError
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import threading
from typing import Any, Mapping, NotRequired, ReadOnly, TypedDict, cast

from .display_messages import DisplaySettings
from .coalescer import Coalescer
from .messages import AsyncTaskCompleted, BasicMessage, ConfigurationChanged, QuitMessage, ReloadSchedules, Telemetry
from .configure_event import ConfigureEvent
from .message_router import MessageRouter
from .protocols import IProvideTimer, MessageSink
from .basic_task import DispatcherTask
from ..datasources.data_source import DataSourceManager
from ..model.schedule_loader import ScheduleLoaderDict
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..model.schedule import Playlist, PlaylistSchedule
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..plugins.plugin_base import PluginAsync, PluginExecutionContext
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..task.timer import IProvideTimer, TimerThreadService
from ..task.protocols import IRequireShutdown

@dataclass(frozen=True, slots=True)
class LayerControlMessage(BasicMessage):
	pass
@dataclass(frozen=True, slots=True)
class StartPlayback(LayerControlMessage):
	pass
@dataclass(frozen=True, slots=True)
class NextTrack(LayerControlMessage):
	pass

class TelemetryDict(TypedDict):
	state: ReadOnly[str]
	current_playlist_index: ReadOnly[int]
	current_playlist: ReadOnly[Playlist]
	current_track_index: ReadOnly[int]
	current_track: ReadOnly[PlaylistSchedule]

class StoppedTelemetryDict(TypedDict):
	state: ReadOnly[str]
	current_playlist_index: ReadOnly[int]
	current_playlist: ReadOnly[None]
	current_track_index: ReadOnly[int]
	current_track: ReadOnly[None]

class PlaylistStateDict(TypedDict):
	current_playlist_index: int
	current_playlist: Playlist
	current_track_index: int
	current_track: PlaylistSchedule

class EvaluatePluginDict(TypedDict):
	plugin: ReadOnly[PluginAsync|None]
	track: ReadOnly[PlaylistSchedule]
	error: NotRequired[str]

class PlaylistLayer(DispatcherTask):
	# a pass in which no track succeeded waits before the next pass: doubling from the first value up to the second
	BACKOFF_INITIAL_SECONDS = 1.0
	BACKOFF_MAX_SECONDS = 60.0
	# a burst of schedule file changes (an editor saving several tracks) is one reload, this long after the last change
	RELOAD_DELAY_SECONDS = 2.0
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager|None = None
		self.playlists = []
		self.plugin_info = None
		self.datasources: DataSourceManager|None = None
		self.timer: IProvideTimer|None = None
		self.dimensions:tuple[int,int] = (800,480)
		self.task_pool: AsyncHttpWorkerPool|None = None
		self.layer_task: tuple[Future, threading.Event] | None = None
		self.timebase: TimeOfDay|None = None
		self.shutdownlist: list[IRequireShutdown] = []
		self.state = 'uninitialized'
		self._backoff = 0.0
		self._restart_timer: threading.Timer|None = None
		self._reload = Coalescer(self.RELOAD_DELAY_SECONDS, self._request_reload)
		self.logger = logging.getLogger(__name__)
	def _evaluate_plugin(self, track: PlaylistSchedule) -> EvaluatePluginDict:
		if self.cm is None:
			errormsg = "ConfigurationManager is not set."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		if self.plugin_info is None:
			errormsg = "Plugin info is not loaded."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		pinfo = next((px for px in self.plugin_info if px["info"]["id"] == track.plugin_name), None)
		if pinfo is None:
			errormsg = f"Plugin info for '{track.plugin_name}' not found."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		plugin = self.cm.create_plugin(pinfo)
		if plugin is not None:
#						self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
			if isinstance(plugin, PluginAsync):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{track.plugin_name}' is not a valid PluginAsync instance."
				self.logger.error(errormsg)
				return { "plugin": plugin, "track": track, "error": errormsg }
		else:
			errormsg = f"Plugin '{track.plugin_name}' is not available."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
	def _create_container(self) -> ServiceContainer:
		if self.cm is None or self.datasources is None or self.router is None or self.timer is None or self.timebase is None:
			raise ValueError("Cannot create context, one or more required components are not set.")
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
		return root
	def _error_with_telemetry(self, emsg:str, msg_ts:datetime):
		self.logger.error(emsg, exc_info=True)
		self.router.send("telemetry", Telemetry(msg_ts, "playlist_layer", {
			"state": "error",
			"message": emsg,
			'current_playlist_index': 0,
			'current_playlist': None,
			'current_track_index': 0,
			'current_track': None,
		}))
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded' and self.state != 'stopped':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.playlists) == 0:
			self.logger.error(f"No playlists available to play.")
			return
		self._run_layer_task(self.playlists, msg.timestamp)
	async def _layer_task(self, isp: IServiceProvider, playlists: list[ScheduleLoaderDict], donev: threading.Event) -> BasicMessage|None:
		self.logger.info(f"'{self.name}' Layer task started.")
		try:
			tod = isp.required(TimeOfDay)
			succeeded = 0
			for plindex, plinfo in enumerate(playlists):
				playlist:Playlist = cast(Playlist, plinfo.get("info"))
				self.logger.info(f"Loaded playlist '{playlist.name}' with {len(playlist.items)} items.")
				for tkindex, item in enumerate(playlist.items):
					track:PlaylistSchedule = cast(PlaylistSchedule, item)
					self.logger.info(f"Track '{track.title}' with plugin '{track.plugin_name}' and content {track.content}")
					plugin_eval = self._evaluate_plugin(track)
					plugin:PluginAsync = cast(PluginAsync, plugin_eval.get("plugin", None))
					if plugin is None:
						self.logger.error(f"Plugin '{track.plugin_name}' for track '{track.title}' is not available, skipping track.")
						continue
					try:
						# the per-track event is its own: `donev` is the layer task's, set in the finally below, and waited on by _task_stop
						track_done = threading.Event()
						ctx = PluginExecutionContext(isp, self.dimensions, tod.current_time())
						msg = await plugin.task_async(ctx, track, track_done)
						self.logger.info(f"Plugin '{plugin.name}' for track '{track.title}' completed with message: {msg}")
						succeeded += 1
						self._backoff = 0.0
						self.state = 'playing'
						telemetry: TelemetryDict = {
							"state": self.state,
							'current_playlist_index': plindex,
							'current_playlist': playlist,
							'current_track_index': tkindex,
							'current_track': track,
						}
						self.router.send("telemetry", Telemetry(tod.current_time(), "playlist_layer", cast(Mapping[str,Any], telemetry)))
					except Exception as e:
						self.state = "error"
						self._error_with_telemetry(f"Error invoke start with plugin '{plugin.name}' track '{track.title}': {e}", tod.current_time())
			if succeeded == 0:
				# nothing played (every track failed, or there were none); do not let the next pass start at once
				self._next_backoff()
				self.logger.warning(f"'{self.name}' no track succeeded in this pass, waiting {self._backoff:g}s before the next one.")
				await asyncio.sleep(self._backoff)
			return None
		except CancelledError as ce:
			self.logger.info(f"'{self.name}' Layer task cancelled.")
			# TODO we could save state here for next time
			raise
		finally:
			donev.set()
			self.logger.info(f"'{self.name}' Layer task ended.")
	def _next_backoff(self) -> float:
		"""Doubles the wait before the next pass, from BACKOFF_INITIAL_SECONDS up to BACKOFF_MAX_SECONDS."""
		self._backoff = self.BACKOFF_INITIAL_SECONDS if self._backoff <= 0 else min(self._backoff * 2, self.BACKOFF_MAX_SECONDS)
		return self._backoff
	def _task_stop(self):
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
	def _run_layer_task(self, playlists: list[ScheduleLoaderDict], timestamp: datetime):
		if self.task_pool is None:
			self.logger.error(f"No task pool available to invoke plugin start.")
			return False
		try:
			donev = threading.Event()
			def submit_callback(fut):
				if not self.is_stopped():
					self.accept(AsyncTaskCompleted(timestamp, "layer_task", fut, donev))
			sc = self._create_container()
			fut = self.task_pool.submit(self._layer_task, sc, playlists, donev, callback=submit_callback)
			self.layer_task = (fut, donev)
			return True
		except Exception as e:
			self.state = "error"
			self._error_with_telemetry(f"Error invoke start layer task: {e}", timestamp)
			return False
	def _async_task_completed(self, msg: AsyncTaskCompleted):
		if not msg.fut.done():
			self.logger.info(f"Layer task still running, cancel...")
			msg.fut.cancel()
			self.logger.info(f"Waiting for layer task to complete...")
			msg.donev.wait(timeout=2.0)
		else:
			self.logger.info(f"Layer task completed.")
			if msg.fut.cancelled():
				# stopped on purpose (_task_stop); whoever cancelled it decides what happens next
				self.logger.info(f"Layer task was cancelled.")
				self._clear_layer_task(msg.token, msg.donev)
				return
			try:
				rmsg = msg.fut.result()
			except Exception as e:
				self._layer_task_failed(msg, e)
				return
			self.logger.info(f"Layer task result: {rmsg}")
			if rmsg is not None:
				# handle any messages returned by the layer task if needed
				self.accept(rmsg)
			else:
				self.logger.info(f"Layer task returned no message, forcing StartPlayback.")
				self.state = 'stopped'
				telemetry: StoppedTelemetryDict = {
					"state": self.state,
					'current_playlist_index': -1,
					'current_playlist': None,
					'current_track_index': -1,
					'current_track': None,
				}
				self.router.send("telemetry", Telemetry(msg.timestamp, "playlist_layer", cast(Mapping[str,Any], telemetry)))
				self.accept(StartPlayback(msg.timestamp))
		self._clear_layer_task(msg.token, msg.donev)
	# (token, donev) and not the message: a one-argument method annotated with a message class is registered as that message's handler
	def _clear_layer_task(self, token: str, donev: threading.Event):
		if token == "layer_task" and (self.layer_task is None or self.layer_task[1] is donev):
			self.layer_task = None
	def _layer_task_failed(self, msg: AsyncTaskCompleted, e: BaseException):
		"""The layer coroutine raised (outside the per-track handling): report it and start the pass again after a backoff, so it cannot spin."""
		self._clear_layer_task(msg.token, msg.donev)
		self.state = 'stopped'
		self._error_with_telemetry(f"Layer task failed: {e}", msg.timestamp)
		delay = self._next_backoff()
		self.logger.warning(f"'{self.name}' restarting playback in {delay:g}s.")
		self._cancel_restart()
		timer = threading.Timer(delay, self._restart_playback, args=(msg.timestamp,))
		timer.daemon = True
		self._restart_timer = timer
		timer.start()
	def _restart_playback(self, timestamp: datetime):
		if self.is_stopped():
			return
		try:
			self.accept(StartPlayback(self.timebase.current_time() if self.timebase is not None else timestamp))
		except ValueError:
			# the task stopped in the meantime
			self.logger.debug(f"'{self.name}' stopped before the restart.")
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
	def _signature(playlists: list[ScheduleLoaderDict]) -> str:
		return json.dumps([p["info"].to_dict() for p in playlists if p.get("info") is not None], sort_keys=True, default=str)
	def _reload_schedules(self, msg: ReloadSchedules):
		"""Re-read the schedules and start the playlists again from the top. A schedule that does not load keeps the one in use."""
		if self.cm is None or self.timebase is None or self.state == 'uninitialized':
			return
		try:
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
		except Exception as e:
			self.logger.warning(f"'{self.name}' the changed schedules do not load, keeping the ones in use: {e}")
			self._error_with_telemetry(f"The changed schedules do not load: {e}", msg.timestamp)
			return
		new_playlists = schedule_info.get("playlists", [])
		if self._signature(new_playlists) == self._signature(self.playlists):
			self.logger.info(f"'{self.name}' schedules changed, playlists are the same.")
			return
		self.logger.info(f"'{self.name}' playlists changed, starting them again.")
		self._cancel_restart()
		self._task_stop()
		self.playlists = new_playlists
		self._backoff = 0.0
		self.state = 'loaded'
		self.accept(StartPlayback(self.timebase.current_time()))
	def _cancel_restart(self):
		timer = self._restart_timer
		self._restart_timer = None
		if timer is not None:
			timer.cancel()
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		try:
			# validate the schedule before allocating resources
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.playlists = schedule_info.get("playlists", [])

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
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.dimensions = (msg.width, msg.height)
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting playback.")
		self._reload.cancel()
		self._cancel_restart()
		try:
			if self.layer_task is not None:
				try:
					self._task_stop()
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