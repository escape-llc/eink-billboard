from concurrent.futures import Future
from datetime import datetime
import logging
import threading
from typing import Any, Any, NotRequired, ReadOnly, TypedDict, cast

from python.model.schedule_loader import ScheduleLoaderDict
from python.task.async_http_worker_pool import AsyncHttpWorkerPool

from ..datasources.data_source import DataSourceManager
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import RenderScheduleDict, TimerTaskItem, Playlist, render_task_schedule_at
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PluginAsync, PluginExecutionContext
from ..task.basic_task import DispatcherTask
from ..task.display import DisplaySettings
from ..task.messages import AsyncTaskCompleted, AsyncTaskCompleted, BasicMessage, QuitMessage, Telemetry
from ..task.protocols import IProvideTimer, IRequireShutdown, MessageSink
from ..task.configure_event import ConfigureEvent
from ..task.playlist_layer import NextTrack, StartPlayback
from ..task.message_router import MessageRouter
from ..task.timer import IProvideTimer, TimerThreadService

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
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager|None = None
		self.tasks: list[ScheduleLoaderDict] = []
		self.plugin_info = None
		self.datasources: DataSourceManager|None = None
		self.timer: IProvideTimer|None = None
		self.dimensions:tuple[int,int] = (800,480)
		self.task_pool: AsyncHttpWorkerPool|None = None
		self.layer_task: tuple[Future, threading.Event] | None = None
		self.shutdownlist: list[IRequireShutdown] = []
		self.timebase: TimeOfDay|None = None
		self.state = 'uninitialized'
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
		return root
	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
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
				self.datasources = DataSourceManager(None, datasources)
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
	def _start_playback(self, msg: StartPlayback):
		self.logger.info(f"'{self.name}' StartPlayback {self.state}")
		if self.state != 'loaded':
			self.logger.error(f"Cannot start playback, state is '{self.state}'")
			return
		if len(self.tasks) == 0:
			self.logger.error(f"No tasks available to run.")
			return
		if self.timer is None:
			self.logger.error(f"Timer service is not available.")
			return
		self._run_layer_task(self.tasks, msg.timestamp)
	async def _layer_task(self, isp: IServiceProvider, tasks: list[ScheduleLoaderDict], donev: threading.Event) -> BasicMessage|None:
		try:
			tod = isp.required(TimeOfDay)
			timer = isp.required(IProvideTimer)
			enabled_task_items = self._get_enabled_tasks(tasks)
			# startup tasks loop
			initial_playlist:Playlist|None = self._startup_playlist(enabled_task_items)
			if initial_playlist is None:
				self.logger.info(f"No startup playlist.")
			else:
				for index, item in enumerate(initial_playlist.items):
					track = cast(TimerTaskItem, item)
					plugin_eval = self._evaluate_plugin(track)
					plugin:PluginAsync = cast(PluginAsync, plugin_eval.get("plugin", None))
					if plugin is None:
						self.logger.error(f"Cannot start startup task, plugin '{track.task.plugin_name}' for task '{track.task.title}' is not available.")
						continue
					try:
						self.logger.info(f"Starting startup task '{track.title}' using plugin '{track.task.plugin_name}'.")
						donev = threading.Event()
						context = PluginExecutionContext(isp, self.dimensions, tod.current_time())
						plugin_result = await plugin.task_async(context, track, donev)
						self.state = 'playing'
						telemetry = {
							"state": self.state,
							"current_playlist": initial_playlist,
							"current_track": track,
							"current_track_index": index,
							"schedule_ts": None
						}
						self.logger.info(f"Startup task '{track.title}' completed with result: {plugin_result}")
						self.router.send("telemetry", Telemetry(tod.current_time(), "timer_layer", telemetry))
					except Exception as e:
						self.state = 'error'
						self._error_with_telemetry(f"Error during startup task '{track.title}': {e}", tod.current_time())
				pass
			# timer tasks loop
			reftime = tod.current_time()
			rendered_schedule = self._next_scheduled_playlist(reftime, enabled_task_items)
			for sched in rendered_schedule:
				sched_ts = datetime.fromisoformat(sched["scheduled_time"])
				delta =  sched_ts - reftime
				if delta.total_seconds() < 0:
					self.logger.warning(f"Skipping past scheduled task '{sched['id']}' at {sched_ts} (scheduled time is in the past).")
					continue
				matching_items = [item for item in rendered_schedule if item["scheduled_time"] == sched["scheduled_time"]]
				self.logger.info(f"Waiting for {len(matching_items)} scheduled task(s) at {sched_ts} (in {delta}).")
				self.state = 'waiting'
				telemetry2 = {
					"state": self.state,
					"schedule_ts": sched_ts
				}
				self.router.send("telemetry", Telemetry(reftime, "timer_layer", cast(dict[str,Any], telemetry2)))
				await timer.sleep(delta)
				actual = tod.current_time()
				self.logger.info(f"Scheduled task time reached: {sched_ts}, actual: {actual}. Starting {len(matching_items)} task(s).")
				# find the corresponding task items for this schedule timestamp
				for match in matching_items:
					task_item = next((t for t in enabled_task_items if t.id == match["id"]), None)
					if task_item is None:
						self.logger.error(f"No task item found for scheduled task id '{match['id']}' at {sched_ts}.")
						continue
					plugin_eval = self._evaluate_plugin(task_item)
					plugin:PluginAsync = cast(PluginAsync, plugin_eval.get("plugin", None))
					if plugin is None:
						self.logger.error(f"Cannot start scheduled task, plugin '{task_item.task.plugin_name}' for task '{task_item.task.title}' is not available.")
						continue
					try:
						self.logger.info(f"Starting scheduled task '{task_item.title}' using plugin '{task_item.task.plugin_name}'.")
						donev = threading.Event()
						context = PluginExecutionContext(isp, self.dimensions, tod.current_time())
						plugin_result = await plugin.task_async(context, task_item, donev)
						self.state = 'playing'
						self.logger.info(f"Scheduled task '{task_item.title}' completed with result: {plugin_result}")
						telemetry: TelemetryDict = {
							"state": self.state,
							"current_playlist": None,
							"current_track": task_item,
							"current_track_index": -1,
							"schedule_ts": sched_ts
						}
						self.router.send("telemetry", Telemetry(tod.current_time(), "timer_layer", cast(dict[str,Any], telemetry)))
					except Exception as e:
						self.state = 'error'
						self._error_with_telemetry(f"Error during scheduled task '{task_item.title}': {e}", tod.current_time())
				pass
			return None
		finally:
			donev.set()
		pass
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
		else:
			self.logger.info(f"Plugin task completed.")
			rmsg = msg.fut.result()
			self.logger.info(f"Plugin task result: {rmsg}")
			if rmsg is not None:
				# handle any messages returned by the plugin task if needed
				self.accept(rmsg)
			else:
				self.logger.info(f"Plugin task returned no message, forcing NextTrack.")
				self.accept(NextTrack(msg.timestamp))
		if msg.token == "layer_task":
			self.layer_task = None
		pass
	def _error_with_telemetry(self, emsg:str, msg_ts:datetime):
		self.logger.error(emsg, exc_info=True)
		self.router.send("telemetry", Telemetry(msg_ts, "timer_layer", {
			"state": "error",
			"message": emsg,
			'current_playlist': None,
			'current_track_index': None,
			'current_track': None,
			'schedule_ts': None
		}))
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
	def _next_scheduled_playlist(self, now: datetime, enabled_task_items: list[TimerTaskItem]) -> list[RenderScheduleDict]:
		scheduled: list[RenderScheduleDict] = []
		for item in enabled_task_items:
			try:
				tdid = render_task_schedule_at(now, item, "schedule", scheduled)
			except Exception as e:
				self.logger.debug(f"Skipping task '{getattr(item, 'name', None)}' while computing next schedule: {e}")
		# Sort by datetime
		scheduled.sort(key=lambda pair: pair["scheduled_time"])
		return scheduled
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting playback.")
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