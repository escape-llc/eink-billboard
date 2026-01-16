import threading
from datetime import datetime, timedelta

from python.model.service_container import IServiceProvider
from python.task.playlist_layer import PlaylistLayer
from python.task.timer_layer import TimerLayer

from ..model.configuration_manager import ConfigurationManager
from .messages import ConfigureNotify, MessageSink, StartEvent, StartOptions, StopEvent, QuitMessage, ConfigureOptions, ConfigureEvent
from .display import Display, DisplaySettings
from .basic_task import DispatcherTask, QuitMessage
from .message_router import MessageRouter, Route

class Application(DispatcherTask):
	def __init__(self, name = None, sink: MessageSink = None):
		super().__init__(name)
		self.sink = sink
		# app_started: StartEvent was processed successfully
		self.app_started = threading.Event()
		# app_stopped: StartEvent failed OR StopEvent processed OR QuitMessage w/o StopEvent processed
		self.app_stopped = threading.Event()
		self.cm:ConfigurationManager = None
		self.router:MessageRouter = None
		self.display:Display = None
		self.playlist_layer:PlaylistLayer = None
		self.timer_layer:TimerLayer = None
		self.root_container: IServiceProvider = None

	def _start_event(self, msg: StartEvent):
		try:
			self._handleStart(msg.options, msg.root, msg.timestamp)
			self.logger.info(f"'{self.name}' started.")
			self.app_started.set()
		except Exception as e:
			self.logger.error(f"Failed to start '{self.name}': {e}", exc_info=True)
			self.app_stopped.set()
	def _stop_event(self, msg: StopEvent):
		try:
			self._handleStop()
		except Exception as e:
			self.logger.error(f"Failed to stop '{self.name}': {e}", exc_info=True)
		finally:
			self.app_stopped.set()
			self.logger.info(f"'{self.name}' stopped.")
	def _display_settings(self, msg: DisplaySettings):
		# STEP 3 configure scheduler (it also receives DisplaySettings)
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		configs = ConfigureEvent("playlist-layer", ConfigureOptions(cm=self.cm.duplicate()), self, msg.timestamp)
		self.playlist_layer.send(configs)
		configt = ConfigureEvent("timer-layer", ConfigureOptions(cm=self.cm.duplicate()), self, msg.timestamp)
		self.timer_layer.send(configt)
	def _configure_notify(self, msg: ConfigureNotify):
		# STEP 4 start playback if layers configured successfully
		self.logger.info(f"'{self.name}' ConfigureNotify {msg.token} {msg.error} {msg.content}.")
		if msg.error == True and self.sink:
			self.sink.send(msg)

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
				self._handleStop()
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
		self.cm = ConfigurationManager(
			source_path=options.basePath if options is not None else None,
			storage_path=options.storagePath if options is not None else None
			)
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
		if self.sink is not None:
			self.router.addRoute(Route('telemetry', [self.sink]))
		# STEP 1 configure the Display task
		configd = ConfigureEvent("display", ConfigureOptions(cm=self.cm.duplicate()), self, timestamp_ts)
		self.display.send(configd)
		# start tasks
		self.display.start()
		self.playlist_layer.start()
		self.timer_layer.start()
	def _handleStop(self):
		if self.timer_layer.is_alive():
			self.timer_layer.send(QuitMessage())
			self.timer_layer.join()
			self.logger.info("TimerLayer stopped");
		if self.playlist_layer.is_alive():
			self.playlist_layer.send(QuitMessage())
			self.playlist_layer.join()
			self.logger.info("PlaylistLayer stopped");
		if self.display.is_alive():
			self.display.send(QuitMessage())
			self.display.join()
			self.logger.info("Display stopped");
