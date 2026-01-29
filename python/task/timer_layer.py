
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import MasterSchedule, PlaylistBase, TimerTaskItem, TimerTasks, generate_schedule, Playlist
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import BasicExecutionContext2, PluginProtocol
from ..task.basic_task import DispatcherTask
from ..task.display import DisplaySettings
from ..task.messages import BasicMessage, ConfigureEvent, FutureCompleted, MessageSink, PluginReceive, QuitMessage, Telemetry
from ..task.playlist_layer import NextTrack, StartPlayback
from ..task.future_source import FutureSource, SubmitFuture
from ..task.message_router import MessageRouter
from ..task.timer import IProvideTimer, TimerService

class TimerExpired(BasicMessage):
	def __init__(self, timestamp: datetime):
		super().__init__(timestamp)

class TimerLayer(DispatcherTask):
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager = None
		self.tasks: list[TimerTasks] = []
		self.master_schedule:MasterSchedule = None
		self.plugin_info = None
		self.datasources: DataSourceManager = None
		self.timer: IProvideTimer = None
		self.dimensions = [800,480]
		self.playlist_state = None
		self.active_plugin: PluginProtocol = None
		self.active_context: BasicExecutionContext2 = None
		self.future_source: SubmitFuture = None
		self.time_of_day: TimeOfDay = None
		self.state = 'uninitialized'
		self.logger = logging.getLogger(__name__)
	def _evaluate_plugin(self, track:TimerTaskItem):
		piname = track.task.plugin_name
		pinfo = next((px for px in self.plugin_info if px["info"]["id"] == piname), None)
		if pinfo is None:
			errormsg = f"Plugin info for '{piname}' not found."
			self.logger.error(errormsg)
			return { "plugin": None, "track": track, "error": errormsg }
		plugin = self.cm.create_plugin(pinfo)
		if plugin is not None:
#				self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
			if isinstance(plugin, PluginProtocol):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{piname}' is not a PluginProtocol instance."
				self.logger.error(errormsg)
				return { "plugin": plugin, "track": track, "error": errormsg }
		else:
			errormsg = f"Plugin '{piname}' is not available."
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
		root.add_service(IProvideTimer, self.timer)
		root.add_service(SubmitFuture, self.future_source)
		root.add_service(TimeOfDay, self.time_of_day)
		root.add_service(MessageSink, self)
		return BasicExecutionContext2(root, self.dimensions, self.time_of_day.current_time())
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		try:
			# validate the schedule before allocating resources
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.master_schedule = schedule_info.get("master", None)
			self.tasks = schedule_info.get("tasks", [])

			plugin_info = self.cm.enum_plugins()
			self.plugin_info = plugin_info

			tod = msg.content.isp.get_service(TimeOfDay)
			self.time_of_day = tod if tod is not None else SystemTimeOfDay()
			ts = msg.content.isp.get_service(IProvideTimer)
			self.timer = ts if ts is not None else TimerService(ThreadPoolExecutor())
			dsm = msg.content.isp.get_service(DataSourceManager)
			if dsm is None:
				datasource_info = self.cm.enum_datasources()
				datasources = self.cm.load_datasources(datasource_info)
				self.logger.info(f"Datasources loaded: {list(datasources.keys())}")
				self.datasources = DataSourceManager(None, datasources)
			else:
				self.datasources = dsm
			sf = msg.content.isp.get_service(SubmitFuture)
			self.future_source = sf if sf is not None else FutureSource("timer_layer", self, ThreadPoolExecutor(thread_name_prefix="TimerLayer"))

			self.logger.info(f"schedule loaded")
			self.state = 'loaded'
			msg.notify()
			self.accept(StartPlayback(self.time_of_day.current_time()))
		except Exception as e:
			self.logger.error(f"Failed to load/validate schedules: {e}", exc_info=True)
			self.state = 'error'
			msg.notify(True, e)
			self._error_with_telemetry(f"ConfigureEvent failed: {e}", msg.timestamp)
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.dimensions = [msg.width, msg.height]
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
			emsg = f"Error invoke receive FutureCompleted with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}"
			self._error_with_telemetry(emsg, msg.timestamp)
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.tasks) == 0:
			self.logger.error(f"No tasks available to run.")
			return
		# Start playback logic here
		# use the playlist metaphor so it works like playlist layer
		# Create a flat list of TimerTaskItem from loaded tasks by selecting each entry's "info"
		# and collecting its `.items`. This produces a list[TimerTaskItem].
		enabled_task_items = self._get_enabled_tasks()

		target_timestamp:datetime|None = None
		initial_playlist:Playlist|None = self._startup_playlist(enabled_task_items)
		if initial_playlist is None:
			self.logger.info(f"No startup tasks found, proceeding to scheduled tasks.")
			(target_timestamp, initial_playlist) = self._next_scheduled_playlist(msg.timestamp, enabled_task_items)
		if initial_playlist is None:
			self.logger.info(f"No startup or scheduled playlist.")
			return
		# NextTrack: at end of playlist
		# TimerExpired: start playback of playlist from (5)
		# NextTrack: advance to next task in that playlist
		self.logger.info(f"{self.name}: starting playback: '{initial_playlist.name}'")
		current_track:PlaylistBase = initial_playlist.items[0] if len(initial_playlist.items) > 0 else None
		if current_track is None:
			self.logger.error(f"Cannot start playback, playlist '{initial_playlist.name}' has no items.")
			return
		plugin_eval = self._evaluate_plugin(current_track)
		active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
		if active_plugin is None:
			emsg = f"Cannot start playback, plugin '{current_track.task.plugin_name}' for task '{current_track.task.title}' is not available."
			self._error_with_telemetry(emsg, msg.timestamp)
			return
		self.active_plugin = active_plugin
		self.active_context = self._create_context()
		self.playlist_state = {
			'current_playlist': initial_playlist,
			'current_track_index': 0,
			'current_track': current_track,
			'schedule_ts': target_timestamp
		}
		if target_timestamp is not None:
			# set a timer for plugin start
			self.timer_state = self.timer.create_timer(target_timestamp - msg.timestamp, self, TimerExpired(target_timestamp))
			self.state = 'waiting'
		else:
			self.timer_state = None
			self._invoke_plugin_start(current_track, msg.timestamp)
	def _error_with_telemetry(self, emsg:str, msg_ts:datetime):
		self.logger.error(emsg, exc_info=True)
		self.router.send("telemetry", Telemetry("timer_layer", {
			"state": "error",
			"message": emsg,
			'current_playlist': None,
			'current_track_index': None,
			'current_track': None,
			'schedule_ts': None
		}, msg_ts))
	def _get_enabled_tasks(self):
		task_items: list[TimerTaskItem] = []
		for sched in self.tasks:
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
	def _invoke_plugin_start(self, current_track:PlaylistBase, msg_ts:datetime):
		try:
			self.active_plugin.start(self.active_context, current_track)
			self.logger.info(f"'{self.name}' Plugin started.")
			self.state = 'playing'
			self.router.send("telemetry", Telemetry("timer_layer", {
				"state": self.state,
				"current_playlist": self.playlist_state["current_playlist"],
				"current_track": self.playlist_state["current_track"],
				"current_track_index": self.playlist_state["current_track_index"],
				"schedule_ts": self.playlist_state["schedule_ts"]
			}, msg_ts))
		except Exception as e:
			self.state = 'error'
			emsg = f"Error starting playback with plugin '{current_track.task.plugin_name}' for track '{current_track.task.title}': {e}"
			self._error_with_telemetry(emsg, msg_ts)
		pass
	def _invoke_plugin_stop(self, msg_ts:datetime):
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to invoke.")
			return
		if self.active_plugin is None:
			self.logger.error(f"No active plugin to invoke.")
			return
		if self.active_context is None:
			self.logger.error(f"No active context to invoke.")
			return
		try:
			current_track:PlaylistBase = self.playlist_state.get('current_track')
			self.active_plugin.stop(self.active_context, current_track)
		except Exception as e:
			self.state = "error"
			emsg = f"Error invoke stop with plugin '{current_track.task.plugin_name}' track '{current_track.title}': {e}"
			self._error_with_telemetry(emsg, msg_ts)
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
			emsg = f"Error invoke receive PluginReceive with plugin '{current_track.plugin_name}' track '{current_track.title}': {e}"
			self._error_with_telemetry(emsg, msg.timestamp)
	def _next_scheduled_playlist(self, now: datetime, enabled_task_items: list[TimerTaskItem]) -> tuple[datetime,Playlist]|None:
		# Build list of (item, next_datetime) for each enabled task that has a next scheduled time
		scheduled: list[tuple[TimerTaskItem, datetime]] = []
		for item in enabled_task_items:
			try:
				gx = generate_schedule(now, getattr(item, 'trigger', {}))
				next_ts = next(gx, None)
				if next_ts is None:
					continue
				scheduled.append((item, next_ts))
			except Exception as e:
				self.logger.debug(f"Skipping task '{getattr(item, 'name', None)}' while computing next schedule: {e}")
		# No scheduled items
		if len(scheduled) == 0:
			return None
		# Sort by datetime
		scheduled.sort(key=lambda pair: pair[1])
		# Find earliest datetime and collect all items matching it
		earliest_ts = scheduled[0][1]
		earliest_items = [pair[0] for pair in scheduled if pair[1] == earliest_ts]
		# Build and return a Playlist from those items
		plist = Playlist("scheduled", f"Scheduled {earliest_ts.isoformat()}", items=earliest_items)
		return (earliest_ts, plist)
	def _next_track(self, msg: NextTrack):
		self.logger.info(f"'{self.name}' NextTrack {msg}")
		if self.active_plugin is not None:
			self.logger.info(f"{self.name}: Stopping current plugin '{self.active_plugin.name}'")
			self._invoke_plugin_stop(msg.timestamp)
			self.active_plugin = None
			self.active_context = None
		# start next track logic
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state to move to next track.")
			return
		current_track_index = self.playlist_state.get('current_track_index')
		current_playlist:Playlist = self.playlist_state.get('current_playlist', None)
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
			self._invoke_plugin_start(next_track, msg.timestamp)
		else:
			self.logger.info(f"End of playlist '{current_playlist.name}' reached.")
			enabled_task_items = self._get_enabled_tasks()
			(target_timestamp, next_playlist) = self._next_scheduled_playlist(msg.timestamp, enabled_task_items)
			if next_playlist is None:
				self.logger.info(f"No scheduled playlist found for next track after end of playlist.")
				self.state = 'stopped'
				self.playlist_state = None
				self.router.send("telemetry", Telemetry("timer_layer", {
					"state": self.state,
					"current_playlist": None,
					"current_track": None,
					"current_track_index": None,
					"schedule_ts": None
				}, msg.timestamp))
				return
			next_track_index = 0
			next_track:PlaylistBase = next_playlist.items[next_track_index]
			plugin_eval = self._evaluate_plugin(next_track)
			active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
			if active_plugin is None:
				self.logger.error(f"Cannot start next track, plugin '{next_track.plugin_name}' for track '{next_track.title}' is not available.")
				return
			self.active_plugin = active_plugin
			self.active_context = self._create_context()
			self.playlist_state['current_playlist'] = next_playlist
			self.playlist_state['current_track_index'] = next_track_index
			self.playlist_state['current_track'] = next_track
			self.playlist_state['schedule_ts'] = target_timestamp
			if self.timer_state is not None:
				self.logger.warning(f"Cancelling existing timer before setting new timer.")
				self.timer.cancel_timer(self.timer_state)
				self.timer_state = None
			self.timer_state = self.timer.create_timer(target_timestamp - msg.timestamp, self, TimerExpired(target_timestamp))
			self.state = 'waiting'
		pass
	def _timer_expired(self, msg: TimerExpired):
		self.logger.info(f"'{self.name}' TimerExpired at {msg.timestamp}.")
		if self.state != 'waiting':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if self.playlist_state is None:
			self.logger.error(f"No active playlist state on timer expired.")
			return
		# start the playlist
		current_playlist:Playlist = self.playlist_state.get('current_playlist', None)
		if current_playlist is None:
			self.logger.error(f"No active playlist on timer expired.")
			return
		iidx = self.playlist_state.get('current_track_index', 0)
		current_track:PlaylistBase = current_playlist.items[iidx] if len(current_playlist.items) > iidx else None
		if current_track is None:
			self.logger.error(f"Cannot start playback, playlist '{current_playlist.name}' has no items.")
			return
		self._invoke_plugin_start(current_track, msg.timestamp)
		pass
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting playback.")
		try:
			if self.active_plugin is not None:
				try:
					self._invoke_plugin_stop(msg.timestamp)
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