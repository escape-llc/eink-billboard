from asyncio import CancelledError
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
import logging
import threading
from typing import Any, NotRequired, ReadOnly, TypedDict, cast

from .display_messages import DisplaySettings
from .messages import AsyncTaskCompleted, BasicMessage, QuitMessage, Telemetry
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
		if self.state != 'loaded':
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
						donev = threading.Event()
						ctx = PluginExecutionContext(isp, self.dimensions, tod.current_time())
						msg = await plugin.task_async(ctx, track, donev)
						self.logger.info(f"Plugin '{plugin.name}' for track '{track.title}' completed with message: {msg}")
						self.state = 'playing'
						telemetry: TelemetryDict = {
							"state": self.state,
							'current_playlist_index': plindex,
							'current_playlist': playlist,
							'current_track_index': tkindex,
							'current_track': track,
						}
						self.router.send("telemetry", Telemetry(tod.current_time(), "playlist_layer", cast(dict[str,Any], telemetry)))
					except Exception as e:
						self.state = "error"
						self._error_with_telemetry(f"Error invoke start with plugin '{plugin.name}' track '{track.title}': {e}", tod.current_time())
			return None
		except CancelledError as ce:
			self.logger.info(f"'{self.name}' Layer task cancelled.")
			# TODO we could save state here for next time
			raise
		finally:
			donev.set()
			self.logger.info(f"'{self.name}' Layer task ended.")
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
			rmsg = msg.fut.result()
			self.logger.info(f"Layer task result: {rmsg}")
			if rmsg is not None:
				# handle any messages returned by the layer task if needed
				self.accept(rmsg)
			else:
				self.logger.info(f"Layer task returned no message, forcing StartPlayback.")
				self.accept(StartPlayback(msg.timestamp))
		if msg.token == "layer_task":
			self.layer_task = None
		pass
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