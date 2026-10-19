import os
import threading
from datetime import datetime, timedelta
from typing import Callable

from .messages import ConfigurationChanged, ConfigurationWatcherEvent, InputEvent, SetupCodeChanged, SetupDone, StartEvent, StartOptions, StopEvent, QuitMessage, Telemetry, TransportCommand
from .configure_event import ConfigureEvent, ConfigureOptions, ConfigureNotify
from .protocols import MessageSink, IProvideTimer
from .device_io import DeviceIO
from .display import Display
from ..device.bindings import action_for
from ..device.buttons import LABELS
from ..device.pins import Panel
from ..display.mock_display import MockDisplay
from .basic_task import DispatcherTask, QuitMessage
from .message_router import MessageRouter, Route
from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..task.display_messages import DisplaySettings, PriorityImage, PriorityRevoke
from ..model.theme import current_inputs
from ..utils.error_image import WebAddress, render_error_image
from ..task.playlist_layer import NextTrack, PlaylistLayer, ResumePlayback, StopPlayback
from ..task.timer import IProvideTimer
from ..task.timer_layer import TimerLayer

SETUP_TITLE = "Set up this device"
# the setup page has no end of its own: it comes down when the device is claimed (`PriorityRevoke`), so it holds the panel until then
SETUP_HOLD = timedelta(days=3650)

# what a viewer may ask of the playlist layer (TransportCommand.command), and the message each becomes
TRANSPORT_COMMANDS = ("play", "stop", "next")

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
		# the task that owns the GPIO, I2C and SPI lines that are not the panel's (python/task/device_io.py)
		self.device_io:DeviceIO|None = None
		self.playlist_layer:PlaylistLayer|None = None
		self.timer_layer:TimerLayer|None = None
		self.root_container: IServiceProvider|None = None
		# lines for a page on the panel while the device is not set up yet (None: nothing to say); see eink-billboard.py
		self.setup_notice: Callable[[], list[str]|None]|None = None
		# an unclaimed device does not play: the layers' configuration waits here until the device is claimed (None: nothing is held)
		self._held: tuple[ConfigureEvent, ConfigureEvent]|None = None
		self._panel: tuple[int, int]|None = None

	def _start_event(self, msg: StartEvent):
		try:
			self._handleStart(msg.options, msg.root, msg.timestamp)
			self.logger.info(f"'{self.name}' started.")
			self.app_started.set()
		except Exception as e:
			self.report_failure("The application could not start", e)
			self.app_stopped.set()
	def _configuration_watcher_event(self, msg: ConfigurationWatcherEvent):
		"""The watcher saw a file change: tell every task where (the cache was already evicted by the sink before this one)."""
		if self.router is None or self.cm is None:
			return
		area = self.cm.area_of(msg.path)
		if area == "state":
			# what the device itself keeps between runs (the panel's last refresh): written after every refresh, nobody's settings, nobody needs to hear of it
			self.logger.debug(f"'{self.name}' the device's own state was saved ({msg.type})")
			return
		self.logger.info(f"'{self.name}' configuration changed: {area} ({msg.type})")
		self.router.send("configuration", ConfigurationChanged(msg.timestamp, area, msg.type, msg.path))
		# the area only: a path in the storage folder is the device's business
		self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "config-changed", "area": area, "message": f"The {area} changed." }))
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
		web = self.root_container.get_service(WebAddress)
		if web:
			plcontainer.add_service(WebAddress, web)
			tlcontainer.add_service(WebAddress, web)
		configs = ConfigureEvent(msg.timestamp, ConfigureOptions(cm=self.cm, isp=plcontainer), "playlist-layer", self)
		configt = ConfigureEvent(msg.timestamp, ConfigureOptions(cm=self.cm, isp=tlcontainer), "timer-layer", self)
		self._panel = (msg.width, msg.height)
		# the devices start now, claimed or not: a press while the device is unclaimed is dropped by `_transport_command`
		self._start_devices(msg.timestamp, msg.name, msg.width, msg.height)
		if self._unclaimed():
			# the tracks do not go into play mode until the owner has claimed the device: the panel holds the setup page, and the layers start when it is claimed
			self._held = (configs, configt)
			self.logger.info(f"'{self.name}' the device is not claimed: the layers wait for it.")
			self._show_setup_notice(msg.width, msg.height, msg.timestamp)
			return
		self._start_layers(configs, configt)
	def _start_devices(self, timestamp: datetime, display_type: str, width: int, height: int):
		"""Configure the DeviceIO task, which opens what the `devices` settings name; it is given the panel's kind and size, so it keeps off the panel's lines. (Plain parameters: a helper whose only parameter is a message type becomes that message's handler.)"""
		if self.cm is None or self.device_io is None:
			# not started the usual way (a test builds the Application piece by piece): nothing to configure
			return
		container = ServiceContainer()
		container.add_service(Panel, Panel(display_type, width, height))
		tod = self.root_container.get_service(TimeOfDay) if self.root_container is not None else None
		if tod:
			container.add_service(TimeOfDay, tod)
		self.device_io.accept(ConfigureEvent(timestamp, ConfigureOptions(cm=self.cm, isp=container), "device-io", self))
	def _input_event(self, msg: InputEvent):
		"""Something happened at a device (a button pressed): what it means is decided here, by the bindings."""
		action = action_for(msg.source, msg.name, msg.gesture)
		if action is None or self.router is None:
			return
		if action == "toggle":
			action = "play" if self.playback_stopped else "stop"
		label = LABELS.get(msg.name, msg.name)
		self.logger.info(f"'{self.name}' input: {label} {msg.gesture}: {action}")
		self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "input", "source": msg.source, "input": msg.name, "gesture": msg.gesture, "action": action,
			"message": f"The {label} was pressed: {action}." if msg.gesture == "press" else f"The {label}: {msg.gesture}: {action}." }))
		self._transport_command(TransportCommand(msg.timestamp, action))
	def _unclaimed(self) -> bool:
		try:
			return bool(self.setup_notice()) if self.setup_notice is not None else False
		except Exception as e:
			self.report_failure("Could not tell whether the device is claimed", e)
			return False
	def _start_layers(self, configs: ConfigureEvent, configt: ConfigureEvent):
		assert self.playlist_layer is not None and self.timer_layer is not None
		self.playlist_layer.accept(configs)
		self.timer_layer.accept(configt)
	def _show_setup_notice(self, width: int, height: int, timestamp: datetime):
		"""A device nobody has claimed shows how to claim it on its own panel for a while: whoever can see it is the owner."""
		try:
			lines = self.setup_notice() if self.setup_notice is not None else None
			if not lines or self.cm is None:
				return
			# the lines say where to open the web app and the code: not an error, so no "cannot show this" and no hint about the settings
			image = render_error_image(self.cm.static_manager(), (width, height), SETUP_TITLE, lines, current_inputs(self.cm.settings_manager()), heading="EINK BILLBOARD", hint=False)
			self.router.send("display", PriorityImage(timestamp, SETUP_TITLE, image, SETUP_HOLD))  # type: ignore[union-attr]
			shown_on = self.display.display if self.display is not None else None
			if isinstance(shown_on, MockDisplay):
				self.logger.warning(f"The mock display has no panel to read the setup code from: it is in the log line 'This device is not set up yet', and the page is saved in {shown_on.output_folder}")
		except Exception as e:
			self.report_failure("Could not show the setup page", e)
	def _now(self) -> datetime:
		tod = self.root_container.get_service(TimeOfDay) if self.root_container is not None else None
		return tod.current_time() if tod else datetime.now().astimezone()
	def setup_done(self) -> None:
		"""The device was claimed (called from the web app's thread): the application's own thread takes the setup page down and starts the layers."""
		try:
			self.accept(SetupDone(self._now()))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the device was claimed.")
	def setup_code_changed(self) -> None:
		"""The setup code was replaced (called from the web app's thread)."""
		try:
			self.accept(SetupCodeChanged(self._now()))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the setup code changed.")
	def _setup_done(self, msg: SetupDone):
		if self.router is None:
			return
		self.router.send("display", PriorityRevoke(msg.timestamp, SETUP_TITLE))
		held, self._held = self._held, None
		if held is not None:
			self.logger.info(f"'{self.name}' the device was claimed: the layers start.")
			self._start_layers(*held)
	def transport(self, command: str) -> bool:
		"""A viewer's play, stop or next (called from the web app's thread, later from a button): the application's own thread forwards it. False: it is not a command, or the application has stopped."""
		if command not in TRANSPORT_COMMANDS:
			return False
		try:
			self.accept(TransportCommand(self._now(), command))
			return True
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the transport command '{command}'.")
			return False
	@property
	def playback_stopped(self) -> bool:
		"""Whether the playlist layer is stopped by a transport command (what the play/stop button shows)."""
		return self.playlist_layer is not None and self.playlist_layer.halted
	def _transport_command(self, msg: TransportCommand):
		"""The first hop of a transport command: it goes to the playlist layer only (the timer layer keeps running), and not at all while the device waits to be claimed."""
		if self.router is None:
			return
		if self._held is not None:
			self.logger.info(f"'{self.name}' the device is not claimed: transport command '{msg.command}' ignored.")
			return
		forwarded = { "play": ResumePlayback, "stop": StopPlayback, "next": NextTrack }.get(msg.command)
		if forwarded is None:
			self.logger.warning(f"'{self.name}' unknown transport command '{msg.command}'.")
			return
		self.logger.info(f"'{self.name}' transport: {msg.command}")
		self.router.send("playlist-layer", forwarded(msg.timestamp))
	def _setup_code_changed(self, msg: SetupCodeChanged):
		"""The page on the panel must not show a code that no longer works: take it down and put the new one up."""
		if self.router is None or self._held is None or self._panel is None:
			return
		self.router.send("display", PriorityRevoke(msg.timestamp, SETUP_TITLE))
		self._show_setup_notice(self._panel[0], self._panel[1], msg.timestamp)
	def _configure_notify(self, msg: ConfigureNotify):
		# STEP 4 playback started if layer configured successfully
		self.logger.info(f"'{self.name}' ConfigureNotify {msg.token} {msg.error} {msg.content}.")
		# the hub keeps every outcome for GET /api/status; only a failure becomes an event
		# not `if self.sink`: a hub with no events yet is falsy (it has a length)
		if self.sink is not None:
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
			# EINK_KEEP_SCHEMAS=1: the browser tests patch the storage's schemas with fields of their own
			if os.environ.get("EINK_KEEP_SCHEMAS") != "1":
				self.cm.refresh_schemas()
			# the settings a stored document lacks, from the (refreshed) schemas and the descriptors
			self.cm.upgrade_settings()
		self.logger.info(f"'{self.name}' start tasks.")
		# STEP 0 assemble tasks and routes
		self.router = MessageRouter()
		self.display = Display("Display", self.router)
		self.playlist_layer = PlaylistLayer("PlaylistLayer", self.router)
		self.timer_layer = TimerLayer("TimerLayer", self.router)
		self.device_io = DeviceIO("DeviceIO", self.router)
		self.router.addRoute(Route("display", [self.display]))
		self.router.addRoute(Route("playlist-layer", [self.playlist_layer]))
		self.router.addRoute(Route("timer-layer", [self.timer_layer]))
		self.router.addRoute(Route("display-settings", [self, self.playlist_layer, self.timer_layer]))
		# what the devices report (a button pressed): the Application gives it a meaning
		self.router.addRoute(Route("device-input", [self]))
		# every task hears about changes to the configuration files
		self.router.addRoute(Route("configuration", [self.display, self.playlist_layer, self.timer_layer, self.device_io]))
		if self.sink is not None:
			self.router.addRoute(Route('telemetry', [self.sink]))
			# the tasks report what they swallow to keep running (the router itself straight to the hub: it sends under its own lock)
			self.router.failure_sink = self.sink.accept
		for task in (self, self.display, self.playlist_layer, self.timer_layer, self.device_io):
			task.failure_sink = lambda telemetry: self.router.send("telemetry", telemetry)  # type: ignore[union-attr]
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
		self.device_io.start()
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
		# the devices first: nothing is listened to while the rest is taken down
		if self.device_io is not None:
			if self.device_io.is_alive():
				try:
					self.device_io.accept(QuitMessage(timestamp))
				except Exception as e:
					self.logger.error(f"Failed to send Quit to '{self.device_io.name}': {e}")
			self._join_task("DeviceIO", self.device_io)
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
