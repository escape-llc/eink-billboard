from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging

from .future_source import FutureSource, SubmitFuture
from ..datasources.data_source import DataSourceManager
from ..model.schedule import MasterSchedule, Playlist, PlaylistBase
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import BasicExecutionContext2, PluginBase, PluginProtocol
from ..task.timer import TimerService
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from .display import DisplaySettings
from .messages import ConfigureEvent, ExecuteMessage, FutureCompleted, MessageSink, PluginReceive, QuitMessage, Telemetry
from .message_router import MessageRouter
from .basic_task import BasicTask, DispatcherTask

class PlaylistLayerMessage(ExecuteMessage):
	def __init__(self, timestamp=None):
		super().__init__(timestamp)
class StartPlayback(PlaylistLayerMessage):
	def __init__(self, timestamp=None):
		super().__init__(timestamp)
class NextTrack(PlaylistLayerMessage):
	def __init__(self, timestamp=None):
		super().__init__(timestamp)

class PlaylistLayer(DispatcherTask):
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		self._register_handler(ConfigureEvent, self._configure_event)
		self._register_handler(DisplaySettings, self._display_settings)
		self._register_handler(StartPlayback, self._start_playback)
		self._register_handler(NextTrack, self._next_track)
		self._register_handler(FutureCompleted, self._future_completed)
		self._register_handler(PluginReceive, self._plugin_receive)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager = None
		self.playlists = []
		self.master_schedule:MasterSchedule = None
		self.plugin_info = None
		self.datasources: DataSourceManager = None
		self.timer: TimerService = None
		self.dimensions = [800,480]
		self.playlist_state = None
		self.active_plugin: PluginProtocol = None
		self.active_context: BasicExecutionContext2 = None
		self.future_source: FutureSource = None
		self.state = 'uninitialized'
		self.logger = logging.getLogger(__name__)
	def _evaluate_plugin(self, track:PlaylistBase):
		pinfo = next((px for px in self.plugin_info if px["info"]["id"] == track.plugin_name), None)
		if pinfo is None:
			errormsg = f"Plugin info for '{track.plugin_name}' not found."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		plugin = self.cm.create_plugin(pinfo)
		if plugin is not None:
#						self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
			if isinstance(plugin, PluginBase):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{track.plugin_name}' is not a valid PluginBase instance."
				self.logger.error(errormsg)
				return { "plugin": plugin, "track": track, "error": errormsg }
		else:
			errormsg = f"Plugin '{track.plugin_name}' is not available."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
	def _create_context(self):
		root = ServiceContainer()
		scm = self.cm.settings_manager()
		stm = self.cm.static_manager()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(StaticConfigurationManager, stm)
		root.add_service(SettingsConfigurationManager, scm)
		root.add_service(DataSourceManager, self.datasources)
		root.add_service(MessageRouter, self.router)
		root.add_service(TimerService, self.timer)
		root.add_service(SubmitFuture, self.future_source)
		root.add_service(MessageSink, self)
		return BasicExecutionContext2(root, self.dimensions, datetime.now())
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.playlists) == 0:
			self.logger.error(f"No playlists available to play.")
			return
		# Start playback logic here
		current_playlist:Playlist = self.playlists[0].get("info")
		current_track:PlaylistBase = current_playlist.items[0] if len(current_playlist.items) > 0 else None
		if current_track is None:
			self.logger.error(f"Current playlist '{current_playlist.name}' has no tracks.")
			return
		plugin_eval = self._evaluate_plugin(current_track)
		active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
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
			self.active_plugin.start(self.active_context, current_track)
			self.state = 'playing'
			self.logger.info(f"'{self.name}' Playback started.")
			self.router.send("telemetry", Telemetry("playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
		except Exception as e:
			self.logger.error(f"Error starting playback with plugin '{current_track.plugin_name}' for track '{current_track.title}': {e}", exc_info=True)
			self.state = 'error'
	def _plugin_receive(self, msg: PluginReceive):
		if self.state != 'playing':
			self.logger.error(f"Cannot handle PluginReceive message, state is '{self.state}'")
			return
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to handle PluginReceive message.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		try:
			current_track:PlaylistBase = self.playlist_state.get('current_track')
			self.active_plugin.receive(self.active_context, current_track, msg)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke receive PluginReceive with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}", exc_info=True)
	def _future_completed(self, msg: FutureCompleted):
		if self.state != 'playing':
			self.logger.error(f"Cannot handle FutureCompleted message, state is '{self.state}'")
			return
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to handle FutureCompleted message.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle FutureCompleted message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle FutureCompleted message.")
			return
		if self.active_plugin.name != msg.plugin_name:
			self.logger.error(f"Received FutureCompleted message for plugin '{msg.plugin_name}', but active plugin is '{self.active_plugin.name}'")
			return
		try:
			current_track:PlaylistBase = self.playlist_state.get('current_track')
			self.active_plugin.receive(self.active_context, current_track, msg)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke receive FutureCompleted with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}", exc_info=True)
	def _plugin_stop(self):
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to invoke.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		try:
			current_track:PlaylistBase = self.playlist_state.get('current_track')
			self.active_plugin.stop(self.active_context, current_track)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke stop with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}", exc_info=True)
	def _plugin_start(self):
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to invoke.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to handle PluginReceive message.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to handle PluginReceive message.")
			return
		try:
			current_track:PlaylistBase = self.playlist_state.get('current_track')
			self.active_plugin.start(self.active_context, current_track)
		except Exception as e:
			self.state = "error"
			self.logger.error(f"Error invoke start with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}", exc_info=True)
	def _next_track(self, msg: NextTrack):
		# Logic to move to the next track in the playlist
		self.logger.info(f"'{self.name}' NextTrack")
		if self.active_plugin is not None:
			self.logger.info(f"Stopping current plugin '{self.active_plugin.name}'")
			self._plugin_stop()
			self.active_plugin = None
			self.active_context = None
		# start next track logic
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to move to next track.")
			return
		current_track_index = self.playlist_state.get('current_track_index')
		current_playlist:Playlist = self.playlist_state.get('current_playlist')
		if current_track_index + 1 < len(current_playlist.items):
			# Move to next track in the same playlist
			next_track_index = current_track_index + 1
			next_track:PlaylistBase = current_playlist.items[next_track_index]
			plugin_eval = self._evaluate_plugin(next_track)
			active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
			if active_plugin is None:
				self.logger.error(f"Cannot start next track, plugin '{next_track.plugin_name}' for track '{next_track.title}' is not available.")
				return
			self.active_plugin = active_plugin
			self.active_context = self._create_context()
			self.playlist_state['current_track_index'] = next_track_index
			self.playlist_state['current_track'] = next_track
			self._plugin_start()
			self.router.send("telemetry", Telemetry("playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
		else:
			self.logger.info(f"End of playlist '{current_playlist.name}' reached.")
			current_playlist_index = self.playlist_state.get('current_playlist_index')
			next_playlist_index = (current_playlist_index + 1) % len(self.playlists)
			next_playlist:Playlist = self.playlists[next_playlist_index]
			next_track_index = 0
			next_track:PlaylistBase = next_playlist.items[next_track_index]
			plugin_eval = self._evaluate_plugin(next_track)
			active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
			if active_plugin is None:
				self.logger.error(f"Cannot start next track, plugin '{next_track.plugin_name}' for track '{next_track.title}' is not available.")
				return
			self.active_plugin = active_plugin
			self.active_context = self._create_context()
			self.playlist_state['current_playlist_index'] = next_playlist_index
			self.playlist_state['current_playlist'] = next_playlist
			self.playlist_state['current_track_index'] = next_track_index
			self.playlist_state['current_track'] = next_track
			self._plugin_start()
			self.router.send("telemetry", Telemetry("playlist_layer", {
				"state": self.state,
				"current_playlist_index": self.playlist_state["current_playlist_index"],
				"current_track_index": self.playlist_state["current_track_index"]
			}))
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		try:
			plugin_info = self.cm.enum_plugins()
			self.plugin_info = plugin_info
			datasource_info = self.cm.enum_datasources()
			datasources = self.cm.load_datasources(datasource_info)
			self.datasources = DataSourceManager(None, datasources)
			self.logger.info(f"Datasources loaded: {list(datasources.keys())}")
			self.future_source = FutureSource(self, ThreadPoolExecutor())
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.master_schedule = schedule_info.get("master", None)
			self.playlists = schedule_info.get("playlists", [])
			self.timer = TimerService(None)
			self.logger.info(f"schedule loaded")
			self.state = 'loaded'
			msg.notify()
			self.send(StartPlayback("SystemStart"))
		except Exception as e:
			self.logger.error(f"Failed to load/validate schedules: {e}", exc_info=True)
			self.state = 'error'
			msg.notify(True, e)
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.dimensions = [msg.width, msg.height]
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting playback.")
		try:
			if self.active_plugin is not None:
				try:
					self._plugin_stop()
				except Exception as e:
					self.logger.error(f"Error stopping active plugin during quit: {e}", exc_info=True)
				finally:
					self.active_plugin = None
					self.active_context = None
					self.playlist_state = None
					self.state = 'stopped'
			if self.timer is not None:
				self.timer.shutdown()
				self.timer = None
			if self.datasources is not None:
				self.datasources.shutdown()
				self.datasources = None
			if self.future_source is not None:
				self.future_source.shutdown()
				self.future_source = None
		except Exception as e:
			self.logger.error(f"quit.unexpected: {e}", exc_info=True)
		finally:
			super().quitMsg(msg)
		pass