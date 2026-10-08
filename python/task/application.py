import threading
from datetime import datetime

from .messages import ConfigurationChanged, ConfigurationWatcherEvent, StartEvent, StartOptions, StopEvent, QuitMessage
from .configure_event import ConfigureEvent, ConfigureOptions, ConfigureNotify
from .protocols import MessageSink, IProvideTimer
from .display import Display
from .basic_task import DispatcherTask, QuitMessage
from .message_router import MessageRouter, Route
from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..task.display_messages import DisplaySettings
from ..task.playlist_layer import PlaylistLayer
from ..task.timer import IProvideTimer
from ..task.timer_layer import TimerLayer

class Application(DispatcherTask):
	def __init__(self, name = None, sink: MessageSink|None = None):
		super().__init__(name)
		self.sink = sink
		# app_started: StartEvent was processed successfully
		self.app_started = threading.Event()
		# app_stopped: StartEvent failed OR StopEvent processed OR QuitMessage w/o StopEvent processed
		self.app_stopped = threading.Event()
		self.cm:ConfigurationManager|None = None
		self.router:MessageRouter|None = None
		self.display:Display|None = None
		self.playlist_layer:PlaylistLayer|None = None
		self.timer_layer:TimerLayer|None = None
		self.root_container: IServiceProvider|None = None

	def _start_event(self, msg: StartEvent):
		try:
			self._handleStart(msg.options, msg.root, msg.timestamp)
			self.logger.info(f"'{self.name}' started.")
			self.app_started.set()
		except Exception as e:
			self.logger.error(f"Failed to start '{self.name}': {e}", exc_info=True)
			self.app_stopped.set()
	def _configuration_watcher_event(self, msg: ConfigurationWatcherEvent):
		"""The watcher saw a file change: tell every task where (the cache was already evicted by the sink before this one)."""
		if self.router is None or self.cm is None:
			return
		area = self.cm.area_of(msg.path)
		self.logger.info(f"'{self.name}' configuration changed: {area} ({msg.type})")
		self.router.send("configuration", ConfigurationChanged(msg.timestamp, area, msg.type, msg.path))
	def _stop_event(self, msg: StopEvent):
		try:
			self._handleStop(msg.timestamp)
		except Exception as e:
			self.logger.error(f"Failed to stop '{self.name}': {e}", exc_info=True)
		finally:
			self.app_stopped.set()
			self.logger.info(f"'{self.name}' stopped.")
	def _display_settings(self, msg: DisplaySettings):
		# STEP 3 configure scheduler (it also receives DisplaySettings)
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		# set by the start event, which comes before this one
		assert self.root_container is not None and self.cm is not None and self.playlist_layer is not None and self.timer_layer is not None
		# populate root containers
		plcontainer = ServiceContainer()
		tlcontainer = ServiceContainer()
		tod = self.root_container.get_service(TimeOfDay)
		if tod:
			plcontainer.add_service(TimeOfDay, tod)
			tlcontainer.add_service(TimeOfDay, tod)
		ipt = self.root_container.get_service(IProvideTimer)
		if ipt:
			plcontainer.add_service(IProvideTimer, ipt)
			tlcontainer.add_service(IProvideTimer, ipt)
		configs = ConfigureEvent(msg.timestamp, ConfigureOptions(cm=self.cm, isp=plcontainer), "playlist-layer", self)
		self.playlist_layer.accept(configs)
		configt = ConfigureEvent(msg.timestamp, ConfigureOptions(cm=self.cm, isp=tlcontainer), "timer-layer", self)
		self.timer_layer.accept(configt)
	def _configure_notify(self, msg: ConfigureNotify):
		# STEP 4 playback started if layer configured successfully
		self.logger.info(f"'{self.name}' ConfigureNotify {msg.token} {msg.error} {msg.content}.")
		if msg.error == True and self.sink:
			self.sink.accept(msg)

		if msg.token == "playlist-layer":
			if msg.error == False:
				self.logger.info(f"'{self.name}' playlist-layer configured successfully.")
			else:
				self.logger.error(f"'{self.name}' Cannot configure playlist-layer")
				self.logger.error(f"{msg.content}")
		if msg.token == "timer-layer":
			if msg.error == False:
				self.logger.info(f"'{self.name}' timer-layer configured successfully.")
			else:
				self.logger.error(f"'{self.name}' Cannot start the timer; timer-layer failed to initialize")
				self.logger.error(f"{msg.content}")
	def quitMsg(self, msg: QuitMessage):
		self.logger.info(f"'{self.name}' quitting.")
		if self.app_started.is_set() and not self.stopped.is_set():
			try:
				self._handleStop(msg.timestamp)
				self.logger.info(f"'{self.name}' stopped during quit.")
			except Exception as e:
				self.logger.error(f"Failed to stop '{self.name}' during quit: {e}", exc_info=True)
			finally:
				self.app_stopped.set()
				super().quitMsg(msg)
		else:
			super().quitMsg(msg)
	def _handleStart(self, options: StartOptions, root: IServiceProvider, timestamp_ts: datetime):
		if options is not None:
			self.logger.info(f"'{self.name}' basePath: {options.basePath}, storagePath: {options.storagePath}")
		self.root_container = root
		#self.cm = ConfigurationManager(
		#	source_path=options.basePath if options is not None else None,
		#	storage_path=options.storagePath if options is not None else None
		#	)
		self.cm = root.required(ConfigurationManager)
		if options is not None and options.hardReset:
			self.logger.info(f"'{self.name}' hard reset configuration.")
			self.cm.hard_reset()
		else:
			self.cm.ensure_folders()
		self.logger.info(f"'{self.name}' start tasks.")
		# STEP 0 assemble tasks and routes
		self.router = MessageRouter()
		self.display = Display("Display", self.router)
		self.playlist_layer = PlaylistLayer("PlaylistLayer", self.router)
		self.timer_layer = TimerLayer("TimerLayer", self.router)
		self.router.addRoute(Route("display", [self.display]))
		self.router.addRoute(Route("playlist-layer", [self.playlist_layer]))
		self.router.addRoute(Route("timer-layer", [self.timer_layer]))
		self.router.addRoute(Route("display-settings", [self, self.playlist_layer, self.timer_layer]))
		# every task hears about changes to the configuration files
		self.router.addRoute(Route("configuration", [self.display, self.playlist_layer, self.timer_layer]))
		if self.sink is not None:
			self.router.addRoute(Route('telemetry', [self.sink]))
		# STEP 1 configure the Display task
		dpcontainer = ServiceContainer()
		tod = self.root_container.get_service(TimeOfDay)
		if tod:
			dpcontainer.add_service(TimeOfDay, tod)
		ipt = self.root_container.get_service(IProvideTimer)
		if ipt:
			dpcontainer.add_service(IProvideTimer, ipt)
		configd = ConfigureEvent(timestamp_ts, ConfigureOptions(cm=self.cm, isp=dpcontainer), "display", self)
		self.display.accept(configd)
		# start tasks
		self.display.start()
		self.playlist_layer.start()
		self.timer_layer.start()
	JOIN_TIMEOUT_SECONDS = 15.0
	def _join_task(self, name: str, task: threading.Thread|None):
		"""Joins a task thread; a thread that never started (or fails to join) must not stop the cleanup of the others."""
		if task is None:
			return
		if task.ident is None:
			self.logger.info(f"{name} was never started")
			return
		try:
			task.join(timeout=self.JOIN_TIMEOUT_SECONDS)
			if task.is_alive():
				self.logger.warning(f"{name} did not stop within {self.JOIN_TIMEOUT_SECONDS:g}s")
			else:
				self.logger.info(f"{name} stopped")
		except Exception as e:
			self.logger.error(f"Failed to join {name}: {e}", exc_info=True)
	def _handleStop(self, timestamp: datetime):
		for task in (self.timer_layer, self.playlist_layer):
			if task is not None and task.is_alive():
				try:
					task.accept(QuitMessage(timestamp))
				except Exception as e:
					self.logger.error(f"Failed to send Quit to '{task.name}': {e}")
		self._join_task("PlaylistLayer", self.playlist_layer)
		self._join_task("TimerLayer", self.timer_layer)
		if self.display is not None:
			if self.display.is_alive():
				try:
					self.display.accept(QuitMessage(timestamp))
				except Exception as e:
					self.logger.error(f"Failed to send Quit to '{self.display.name}': {e}")
			self._join_task("Display", self.display)
