
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging

from python.model.service_container import ServiceContainer

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import MasterSchedule, TimerTaskItem, TimerTasks, generate_schedule
from ..plugins.plugin_base import BasicExecutionContext2, PluginBase, PluginProtocol
from ..task.basic_task import DispatcherTask
from ..task.display import DisplaySettings
from ..task.messages import BasicMessage, ConfigureEvent, MessageSink, QuitMessage, Telemetry
from ..task.playlist_layer import StartPlayback
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
		current_schedule:TimerTasks = self.tasks[0].get("info")
		# TODO find first ENABLED item
		current_track:TimerTaskItem = current_schedule.items[0] if len(current_schedule.items) > 0 else None
		if current_track is None:
			self.logger.error(f"Current schedule '{current_schedule.name}' has no tasks.")
			return
		gx = generate_schedule(msg.timestamp, current_track.trigger)
		target_timestamp = next(gx, None)
		if target_timestamp is None:
			self.logger.error(f"Current task '{current_track.name}' has no valid trigger for time {msg.timestamp}.")
			return
		self.logger.info(f"Next scheduled time for task '{current_track.name}' is {target_timestamp}.")
		plugin_eval = self._evaluate_plugin(current_track)
		active_plugin:PluginProtocol = plugin_eval.get("plugin", None)
		if active_plugin is None:
			self.logger.error(f"Cannot start playback, plugin '{current_track.task.plugin_name}' for task '{current_track.task.title}' is not available.")
			return
		self.active_plugin = active_plugin
		self.active_context = self._create_context()
		self.playlist_state = {
			'current_schedule_index': 0,
			'current_schedule': current_schedule,
			'current_track_index': 0,
			'current_track': current_track,
			'schedule_ts': target_timestamp
		}
		try:
			self.active_plugin.start(self.active_context, current_track)
			self.state = 'playing'
			self.logger.info(f"'{self.name}' Playback started.")
			# set a timer for the scheduled time
			self.timer_state = self.timer.create_timer(target_timestamp - msg.timestamp, self, TimerExpired(target_timestamp))
			self.router.send("telemetry", Telemetry("timer_layer", {
				"state": self.state,
				"current_schedule_index": self.playlist_state["current_schedule_index"],
				"current_track_index": self.playlist_state["current_track_index"],
				"schedule_ts": self.playlist_state["schedule_ts"]
			}))
		except Exception as e:
			self.logger.error(f"Error starting playback with plugin '{current_track.plugin_name}' for track '{current_track.title}': {e}", exc_info=True)
			self.state = 'error'
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