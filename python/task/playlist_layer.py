from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import NotRequired, ReadOnly, TypedDict, cast

from .future_source import FutureSource, SubmitFuture
from .display import DisplaySettings
from .messages import BasicMessage, ConfigureEvent, FutureCompleted, MessageSink, PluginReceive, QuitMessage, Telemetry, TimerExpired
from .message_router import MessageRouter
from .basic_task import DispatcherTask
from ..datasources.data_source import DataSourceManager
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..model.schedule import Playlist, PlaylistSchedule, ScheduleItemBase
from ..model.service_container import ServiceContainer
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..plugins.plugin_base import PluginExecutionContext, PluginProtocol
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

class EvaluatePluginDict(TypedDict):
	plugin: ReadOnly[PluginProtocol|None]
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
		self.playlist_state = None
		self.active_plugin: PluginProtocol|None = None
		self.active_context: PluginExecutionContext|None = None
		self.future_source: SubmitFuture|None = None
		self.timebase: TimeOfDay|None = None
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
			if isinstance(plugin, PluginProtocol):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{track.plugin_name}' is not a valid PluginProtocol instance."
				self.logger.error(errormsg)
				return { "plugin": plugin, "track": track, "error": errormsg }
		else:
			errormsg = f"Plugin '{track.plugin_name}' is not available."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
	def _create_context(self):
		if self.cm is None or self.datasources is None or self.router is None or self.timer is None or self.future_source is None or self.timebase is None:
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
		root.add_service(SubmitFuture, self.future_source)
		root.add_service(TimeOfDay, self.timebase)
		root.add_service(MessageSink, self)
		return PluginExecutionContext(root, self.dimensions, self.timebase.current_time())
	def _plugin_receive_send(self, active_plugin: PluginProtocol|None, msg: BasicMessage):
		if self.state != 'playing':
			self.logger.error(f"Cannot handle PluginReceive message, state is '{self.state}'")
			return
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to handle PluginReceive message.")
			return
		if active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		current_track:ScheduleItemBase = cast(ScheduleItemBase, self.playlist_state.get('current_track'))
		try:
			self.active_context.update_timestamp(msg.timestamp)
			active_plugin.receive(self.active_context, current_track, msg)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke receive PluginReceive with plugin '{active_plugin.name}' track '{current_track.title}': {e}", exc_info=True)
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.playlists) == 0:
			self.logger.error(f"No playlists available to play.")
			return
		# Start playback logic here
		current_playlist:Playlist = cast(Playlist, self.playlists[0].get("info"))
		current_track:ScheduleItemBase|None = current_playlist.items[0] if len(current_playlist.items) > 0 else None
		if current_track is None:
			self.logger.error(f"Current playlist '{current_playlist.name}' has no tracks.")
			return
		plugin_eval = self._evaluate_plugin(cast(PlaylistSchedule, current_track))
		active_plugin:PluginProtocol = cast(PluginProtocol, plugin_eval.get("plugin", None))
		if active_plugin is None:
			self.logger.error(f"Cannot start playback, plugin '{current_track.plugin_name}' for track '{current_track.title}' is not available.")
			return
		self.active_plugin = active_plugin
		self.active_context = self._create_context()
		self.playlist_state = {
			'current_playlist_index': 0,
			'current_playlist': current_playlist,
			'current_track_index': 0,
			'current_track': current_track,
		}
		try:
			self.active_context.update_timestamp(msg.timestamp)
			self.active_plugin.start(self.active_context, current_track)
			self.state = 'playing'
			self.logger.info(f"'{self.name}' Playback started.")
			self.router.send("telemetry", Telemetry(msg.timestamp, "playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
		except Exception as e:
			self.logger.error(f"Error starting playback with plugin '{self.active_plugin.name}' for track '{current_track.title}': {e}", exc_info=True)
			self.state = 'error'
	def _plugin_receive(self, msg: PluginReceive):
		self._plugin_receive_send(self.active_plugin, msg)
	def _future_completed(self, msg: FutureCompleted):
		self._plugin_receive_send(self.active_plugin, msg)
	def _timer_expired(self, msg: TimerExpired):
		self._plugin_receive_send(self.active_plugin, msg)
	def _plugin_stop(self, timestamp:datetime):
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to invoke.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		current_track:ScheduleItemBase = cast(ScheduleItemBase, self.playlist_state.get('current_track'))
		try:
			self.active_context.update_timestamp(timestamp)
			self.active_plugin.stop(self.active_context, current_track)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"'{self.name}' Error invoke stop with plugin '{self.active_plugin.name}' track '{current_track.title}': {e}", exc_info=True)
	def _plugin_start(self, timestamp:datetime):
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to invoke.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		current_track:ScheduleItemBase = cast(ScheduleItemBase, self.playlist_state.get('current_track'))
		try:
			self.active_context.update_timestamp(timestamp)
			self.active_plugin.start(self.active_context, current_track)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke start with plugin '{self.active_plugin.name}' track '{current_track.title}': {e}", exc_info=True)
	def _next_track(self, msg: NextTrack):
		# Logic to move to the next track in the playlist
		self.logger.info(f"'{self.name}' NextTrack")
		if self.active_plugin is not None:
			self.logger.info(f"Stopping current plugin '{self.active_plugin.name}'")
			self._plugin_stop(msg.timestamp)
			self.active_plugin = None
			self.active_context = None
		# start next track logic
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to move to next track.")
			return
		current_track_index = cast(int, self.playlist_state.get('current_track_index'))
		current_playlist:Playlist = cast(Playlist, self.playlist_state.get('current_playlist'))
		if current_track_index + 1 < len(current_playlist.items):
			# Move to next track in the same playlist
			next_track_index = current_track_index + 1
			next_track:ScheduleItemBase = current_playlist.items[next_track_index]
			plugin_eval = self._evaluate_plugin(cast(PlaylistSchedule, next_track))
			active_plugin:PluginProtocol = cast(PluginProtocol, plugin_eval.get("plugin", None))
			if active_plugin is None:
				self.logger.error(f"Cannot start next track, plugin '{next_track.plugin_name}' for track '{next_track.title}' is not available.")
				return
			self.active_plugin = active_plugin
			self.active_context = self._create_context()
			self.playlist_state['current_track_index'] = next_track_index
			self.playlist_state['current_track'] = next_track
			self._plugin_start(msg.timestamp)
			self.router.send("telemetry", Telemetry(msg.timestamp, "playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
		else:
			self.logger.info(f"End of playlist '{current_playlist.name}' reached.")
			current_playlist_index = cast(int, self.playlist_state.get('current_playlist_index'))
			next_playlist_index = (current_playlist_index + 1) % len(self.playlists)
			next_playlist:Playlist = cast(Playlist, self.playlists[next_playlist_index].get("info", None))
			next_track_index = 0
			next_track:ScheduleItemBase = next_playlist.items[next_track_index]
			plugin_eval = self._evaluate_plugin(cast(PlaylistSchedule, next_track))
			active_plugin:PluginProtocol = cast(PluginProtocol, plugin_eval.get("plugin", None))
			if active_plugin is None:
				self.logger.error(f"Cannot start next track, plugin '{next_track.plugin_name}' for track '{next_track.title}' is not available.")
				return
			self.active_plugin = active_plugin
			self.active_context = self._create_context()
			self.playlist_state['current_playlist_index'] = next_playlist_index
			self.playlist_state['current_playlist'] = next_playlist
			self.playlist_state['current_track_index'] = next_track_index
			self.playlist_state['current_track'] = next_track
			self._plugin_start(msg.timestamp)
			self.router.send("telemetry", Telemetry(msg.timestamp, "playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
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
			dsm = msg.content.isp.get_service(DataSourceManager)
			if dsm is None:
				datasource_info = self.cm.enum_datasources()
				datasources = self.cm.load_datasources(datasource_info)
				self.logger.info(f"Datasources loaded: {list(datasources.keys())}")
				self.datasources = DataSourceManager(None, datasources)
			else:
				self.datasources = dsm
			sf = msg.content.isp.get_service(SubmitFuture)
			self.future_source = sf if sf is not None else FutureSource("playlist_layer", self, ThreadPoolExecutor(thread_name_prefix="PlaylistLayer"))

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
			if self.active_plugin is not None:
				try:
					self._plugin_stop(msg.timestamp)
				except Exception as e:
					self.logger.error(f"'{self.name}' Error stopping active plugin during quit: {e}", exc_info=True)
				finally:
					self.active_plugin = None
					self.active_context = None
					self.playlist_state = None
					self.state = 'stopped'
			# TODO need to track whether WE CREATED this thing, or got it from outside
			if self.timer is not None:
				if isinstance(self.timer, IRequireShutdown):
					self.timer.shutdown()
				self.timer = None
			if self.datasources is not None:
				self.datasources.shutdown()
				self.datasources = None
			# TODO need to track whether WE CREATED this thing, or got it from outside
			if self.future_source is not None:
				if isinstance(self.future_source, IRequireShutdown):
					self.future_source.shutdown()
				self.future_source = None
		except Exception as e:
			self.logger.error(f"'{self.name}' quit.unexpected: {e}", exc_info=True)
		finally:
			super().quitMsg(msg)
		pass