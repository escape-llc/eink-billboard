
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging

from python.model.service_container import ServiceContainer

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import MasterSchedule, PlaylistBase, TimerTaskItem, TimerTasks, generate_schedule, Playlist
from ..plugins.plugin_base import BasicExecutionContext2, PluginBase, PluginProtocol
from ..task.basic_task import DispatcherTask
from ..task.display import DisplaySettings
from ..task.messages import BasicMessage, ConfigureEvent, MessageSink, QuitMessage, Telemetry
from ..task.playlist_layer import NextTrack, StartPlayback
from ..task.future_source import FutureSource, SubmitFuture
from ..task.message_router import MessageRouter
from ..task.timer import TimerService

class TimerExpired(BasicMessage):
	def __init__(self, timestamp=None):
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
		self.timer: TimerService = None
		self.dimensions = [800,480]
		self.playlist_state = None
		self.active_plugin: PluginProtocol = None
		self.active_context: BasicExecutionContext2 = None
		self.future_source: FutureSource = None
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
#						self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
			if isinstance(plugin, PluginBase):
				return { "plugin": plugin, "track": track }
			else:
				errormsg = f"Plugin '{piname}' is not a valid PluginBase instance."
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
		root.add_service(TimerService, self.timer)
		root.add_service(SubmitFuture, self.future_source)
		root.add_service(MessageSink, self)
		return BasicExecutionContext2(root, self.dimensions, datetime.now())
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		try:
			plugin_info = self.cm.enum_plugins()
			self.plugin_info = plugin_info
			datasource_info = self.cm.enum_datasources()
			datasources = self.cm.load_datasources(datasource_info)
			self.datasources = DataSourceManager(None, datasources)
			self.logger.info(f"Datasources loaded: {list(datasources.keys())}")
			self.future_source = FutureSource("timer_layer", self, ThreadPoolExecutor())
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.master_schedule = schedule_info.get("master", None)
			self.tasks = schedule_info.get("tasks", [])
			self.timer = TimerService(None)
			self.logger.info(f"schedule loaded")
			self.state = 'loaded'
			msg.notify()
			self.send(StartPlayback(msg.timestamp))
		except Exception as e:
			self.logger.error(f"Failed to load/validate schedules: {e}", exc_info=True)
			self.state = 'error'
			msg.notify(True, e)
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.dimensions = [msg.width, msg.height]
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

		target_timestamp:datetime|None = None
		initial_playlist:Playlist|None = self._startup_playlist(enabled_task_items)
		if initial_playlist is None:
			self.logger.info(f"No startup tasks found, proceeding to scheduled tasks.")
			(target_timestamp, initial_playlist) = self._next_scheduled_playlist(msg.timestamp, enabled_task_items)
		if initial_playlist is None:
			self.logger.info(f"No startup or scheduled playlist.")
			return
		# 3. start playback of playlist from (2)
		# TODO if target_timestamp is not None, start timer for playlist start
		# NextTrack: at end of playlist
		# TimerExpired: start playback of playlist from (5)
		# NextTrack: advance to next task in that playlist
		self.logger.info(f"{self.name}: starting playback: '{initial_playlist.name}'")
		current_track:PlaylistBase = initial_playlist.items[0] if len(initial_playlist.items) > 0 else None
		plugin_eval = self._evaluate_plugin(current_track)
		active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
		if active_plugin is None:
			self.logger.error(f"Cannot start playback, plugin '{current_track.task.plugin_name}' for task '{current_track.task.title}' is not available.")
			return
		self.active_plugin = active_plugin
		self.active_context = self._create_context()
		self.playlist_state = {
			'current_playlist': initial_playlist,
			'current_track_index': 0,
			'current_track': current_track,
			'schedule_ts': target_timestamp
		}
		try:
			self.active_plugin.start(self.active_context, current_track)
			self.state = 'playing'
			self.logger.info(f"'{self.name}' Playback started.")
			if target_timestamp is not None:
				# set a timer for the scheduled time
				self.timer_state = self.timer.create_timer(target_timestamp - msg.timestamp, self, TimerExpired(target_timestamp))
			else:
				self.timer_state = None
			self.router.send("telemetry", Telemetry("timer_layer", {
				"state": self.state,
				"current_playlist": self.playlist_state["current_playlist"],
				"current_track": self.playlist_state["current_track"],
				"current_track_index": self.playlist_state["current_track_index"],
				"schedule_ts": self.playlist_state["schedule_ts"]
			}))
		except Exception as e:
			self.logger.error(f"Error starting playback with plugin '{current_track.task.plugin_name}' for track '{current_track.title}': {e}", exc_info=True)
			self.state = 'error'
	def _startup_playlist(self, enabled_task_items: list[TimerTaskItem]) -> Playlist|None:
		startup_task_items: list[TimerTaskItem] = [
			t for t in enabled_task_items
			if getattr(t, 'trigger', {}).get("on_startup", None) is True
		]
		if len(startup_task_items) == 0:
			return None
		startup_playlist = Playlist("startup", "Startup Tasks", items=startup_task_items)
		return startup_playlist
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
		# TODO advance to next task
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
#		current_playlist:Playlist = self.playlist_state.get('current_playlist')
		pass
	def _timer_expired(self, msg: TimerExpired):
		self.logger.info(f"'{self.name}' TimerExpired at {msg.timestamp}.")
		# TODO construct event and send to active plugin
		# TODO advance to next task
		pass
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