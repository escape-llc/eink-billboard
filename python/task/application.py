import os
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from .messages import ClockCheck, ConfigurationChanged, ConfigurationWatcherEvent, InputEvent, PushedImage, RestoreBegin, RestoreEnd, RestoreSettled, SetupCodeChanged, SetupDone, StartEvent, StartOptions, StopEvent, QuitMessage, RunTask, RunTrigger, Telemetry, TransportCommand
from .configure_event import ConfigureEvent, ConfigureOptions, ConfigureNotify
from .coalescer import Coalescer
from .protocols import MessageSink, IProvideTimer
from .telemetry_hub import COMPONENTS, ours
from .device_io import DeviceIO
from .display import Display
from PIL import Image

from ..device.bindings import row_for, row_with_pin
from ..device.buttons import input_label
from ..device.pins import Panel
from ..display.mock_display import MockDisplay
from .basic_task import DispatcherTask, handles
from .message_router import MessageRouter, Route
from ..model.changed_paths import EVERYTHING, changed_paths
from ..model.clock_sync import ClockSync, ClockState
from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.time_of_day import TimeOfDay
from ..task.display_messages import DisplaySettings, PriorityImage, PriorityRevoke
from ..model.theme import current_inputs
from ..utils.error_image import WebAddress, render_error_image
from ..task.playlist_layer import NextTrack, PlaylistLayer, ResumePlayback, StopPlayback
from ..task.timer_layer import TimerLayer

SETUP_TITLE = "Set up this device"
# the setup page has no end of its own: it comes down when the device is claimed (`PriorityRevoke`), so it holds the panel until then
SETUP_HOLD = timedelta(days=3650)
# the setup page says whose project the device runs (#824): the one page every new owner sees
SETUP_CREDIT = "eInk Billboard · escape-technology-llc.com"

# what a viewer may ask of the playlist layer (TransportCommand.command), and the message each becomes
TRANSPORT_COMMANDS = ("play", "stop", "next")

# pushed messages (the API): how many may wait or show at once, and how long after its time a message still counts as one of them (it may have waited behind others)
MAX_PUSHED_ACTIVE = 20
PUSHED_SLACK = timedelta(minutes=5)
# the commit timer's wait (Display) before a page is taken, and so the least a pushed message waits
COMMIT_SECONDS = 2.0

# a restore (#368): the Application holds back the per-file change notifications from `RestoreBegin` until the files' own change events have stopped coming
# a route that dies before it says it is done must not leave the notifications held for ever: the lease ends the restore
RESTORE_LEASE_SECONDS = 120.0
# the watcher reports a file a debounce (1 s, or the poll interval) after it was written: settled when none has come for this long, and at the latest after the cap
RESTORE_QUIET_SECONDS = 3.0
RESTORE_CAP_SECONDS = 15.0
# how long a route waits for the Application to say it may begin
RESTORE_BEGIN_WAIT_SECONDS = 5.0

# the layers wait for the clock to be set (#785): how often the Application looks, and how long it waits before it starts them anyway (a Pi with no network never syncs)
CLOCK_POLL_SECONDS = 5.0
CLOCK_WAIT_SECONDS = 120.0

class PushRefused(Exception):
	"""A pushed message that cannot be taken, with the HTTP status the route answers with and our own words for the sender."""
	def __init__(self, status: int, message: str):
		super().__init__(message)
		self.status = status
		self.message = message

@dataclass(frozen=True)
class Pushed:
	"""What a push got: the id that takes it down again, the title it goes by on the panel and the telemetry (made unique among the messages that are about), and roughly how soon it can show."""
	id: str
	title: str
	starts_in_seconds: int

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
		# messages pushed through the API that are still about: id -> (title, the monotonic time after which it is surely over); the web app's threads and this one use it
		self._pushed: dict[str, tuple[str, float]] = {}
		self._pushed_lock = threading.Lock()
		# the task that owns the GPIO, I2C and SPI lines that are not the panel's (python/task/device_io.py)
		self.device_io:DeviceIO|None = None
		self.playlist_layer:PlaylistLayer|None = None
		self.timer_layer:TimerLayer|None = None
		self.root_container: IServiceProvider|None = None
		# lines for a page on the panel while the device is not set up yet (None: nothing to say); see eink-billboard.py
		self.setup_notice: Callable[[], list[str]|None]|None = None
		# the address the setup page's QR code opens (the web app's claim route with the setup code), set with `setup_notice`
		self.setup_claim_url: Callable[[], str|None]|None = None
		# an unclaimed device does not play: the layers' configuration waits here until the device is claimed (None: nothing is held)
		self._held: tuple[ConfigureEvent, ConfigureEvent]|None = None
		# a claimed device whose clock is not set yet: the layers' configuration waits here for it, at most `clock_wait_seconds` (None: nothing is held)
		self._clock_held: tuple[ConfigureEvent, ConfigureEvent]|None = None
		self._clock_deadline = 0.0
		self._clock_timer: Coalescer|None = None
		self.clock_poll_seconds = CLOCK_POLL_SECONDS
		self.clock_wait_seconds = CLOCK_WAIT_SECONDS
		# the parts that said they are configured (COMPONENTS): all of them is "running"
		self._up: set[str] = set()
		self._panel: tuple[int, int]|None = None
		# a restore of a backup: `idle`, `restoring` (files are being written) or `draining` (written; waiting for the watcher's events to pass). Only this thread changes it.
		self._restore_state = "idle"
		self._restore_generation = 0
		self._restore_absorbed = 0
		self._restore_result: tuple[bool, int] = (True, 0)
		self._restore_timers: list[Coalescer] = []
		self.restore_lease_seconds = RESTORE_LEASE_SECONDS
		self.restore_quiet_seconds = RESTORE_QUIET_SECONDS
		self.restore_cap_seconds = RESTORE_CAP_SECONDS

	@handles(StartEvent)
	def _start_event(self, msg: StartEvent):
		try:
			self._handleStart(msg.options, msg.root, msg.timestamp)
			self.logger.info(f"'{self.name}' started.")
			self.app_started.set()
		except Exception as e:
			self.report_failure("The application could not start", e)
			self.app_stopped.set()
	@handles(ConfigurationWatcherEvent)
	def _configuration_watcher_event(self, msg: ConfigurationWatcherEvent):
		"""The watcher saw a file change: tell every task where (the cache was already evicted by the sink before this one)."""
		if self.router is None or self.cm is None:
			return
		area = self.cm.area_of(msg.path)
		if area in ("state", "tls"):
			# what the device itself keeps between runs (the panel's last refresh, its own TLS certificate): nobody's settings, nobody needs to hear of it
			self.logger.debug(f"'{self.name}' the device's own state was saved ({msg.type})")
			return
		if self._restore_state != "idle":
			# a restore is writing many files: nobody hears of them one by one (the layers would reload against a half-written storage), the end says it all once
			self._restore_absorbed += 1
			if self._restore_state == "draining" and self._restore_timers:
				self._restore_timers[1].trigger()
			return
		self.logger.info(f"'{self.name}' configuration changed: {area} ({msg.type})")
		self.router.send("configuration", ConfigurationChanged(msg.timestamp, area, msg.type, msg.path))
		# the area and the API routes whose answers may differ now (a page asks for them again), never the file: a path in the storage folder is the device's business
		self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "config-changed", "area": area, "changed": self._changed_paths(msg.path), "message": f"The {area} changed." }))
	def _changed_paths(self, path: str|bytes) -> list[str]:
		"""What the change means to a page that keeps the API's answers; when that cannot be worked out, everything (a page asks again rather than show an old answer)."""
		try:
			return changed_paths(self.cm, path) if self.cm is not None else [EVERYTHING]
		except Exception as e:
			self.report_failure("The routes a change of the storage affects could not be worked out", e)
			return [EVERYTHING]
	@handles(StopEvent)
	def _stop_event(self, msg: StopEvent):
		try:
			self._handleStop(msg.timestamp)
		except Exception as e:
			self.logger.error(f"Failed to stop '{self.name}': {e}", exc_info=True)
		finally:
			self.app_stopped.set()
			self.logger.info(f"'{self.name}' stopped.")
	@handles(DisplaySettings)
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
			self._startup(msg.timestamp, "waiting-for-setup", "The device is not set up yet: the playlist and the timer tasks start once it is claimed.")
			self._show_setup_notice(msg.width, msg.height, msg.timestamp)
			return
		self._start_when_clock_set(msg.timestamp, configs, configt)
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
	@handles(InputEvent)
	def _input_event(self, msg: InputEvent):
		"""Something happened at a device (a button pressed): what it means is decided here, by the bindings."""
		if self.router is None or self.cm is None:
			return
		# what a button does is what the GPIO settings say now (read each time: a change applies at once)
		_, devices = self.cm.settings_manager().open("devices").get()
		row = row_for(msg.source, msg.name, msg.gesture, devices if isinstance(devices, dict) else None)
		if row is None:
			return
		action = row["action"]
		if action == "task":
			label = input_label(msg.name)
			self.logger.info(f"'{self.name}' input: {label} {msg.gesture}: run its task")
			self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "input", "source": msg.source, "input": msg.name, "gesture": msg.gesture, "action": action,
				"message": f"The {label} was pressed: run its task." }))
			self._run_trigger_row(msg.timestamp, row)
			return
		if action == "toggle":
			action = "play" if self.playback_stopped else "stop"
		label = input_label(msg.name)
		self.logger.info(f"'{self.name}' input: {label} {msg.gesture}: {action}")
		self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "input", "source": msg.source, "input": msg.name, "gesture": msg.gesture, "action": action,
			"message": f"The {label} was pressed: {action}." }))
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
	def _layers_held(self) -> bool:
		"""The layers are not started yet: they wait for the device to be claimed, or for the clock."""
		return self._held is not None or self._clock_held is not None
	def _clock_state(self) -> ClockState:
		clock = self.root_container.get_service(ClockSync) if self.root_container is not None else None
		if clock is None:
			return "unknown"
		try:
			return clock.state()
		except Exception as e:
			self.report_failure("Could not tell whether the clock is set", e)
			return "unknown"
	def _start_when_clock_set(self, timestamp: datetime, configs: ConfigureEvent, configt: ConfigureEvent):
		"""
		Start the layers once the clock is set (#785): a page drawn on a boot's stale time is wrong, and the timers would count from it.
		A clock nothing says is wrong (`unknown`: no timesyncd) starts them at once; one not set yet holds them, looked at every `clock_poll_seconds`, at most `clock_wait_seconds`.
		"""
		state = self._clock_state()
		if state != "unsynced":
			if state == "synced":
				self._startup(timestamp, "clock-ready", "The clock is set.")
			self._start_layers(configs, configt)
			return
		self._clock_held = (configs, configt)
		self._clock_deadline = time.monotonic() + self.clock_wait_seconds
		self.logger.info(f"'{self.name}' the clock is not set yet: the layers wait for it, at most {self.clock_wait_seconds:g}s.")
		self._startup(timestamp, "waiting-for-clock", "The clock is not set yet: the playlist and the timer tasks start once it is.")
		self._clock_timer = Coalescer(self.clock_poll_seconds, self._clock_fire)
		self._clock_timer.trigger()
	def _clock_fire(self) -> None:
		try:
			self.accept(ClockCheck(self._now()))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped while it waited for the clock.")
	@handles(ClockCheck)
	def _clock_check(self, msg: ClockCheck):
		if self._clock_held is None:
			return
		state = self._clock_state()
		if state == "unsynced" and time.monotonic() < self._clock_deadline:
			if self._clock_timer is not None:
				self._clock_timer.trigger()
			return
		held, self._clock_held = self._clock_held, None
		self._end_clock_wait()
		if state == "unsynced":
			self.logger.warning(f"'{self.name}' the clock was not set in {self.clock_wait_seconds:g}s: the layers start anyway.")
			self._startup(msg.timestamp, "clock-unsure", f"The clock was not set in {self.clock_wait_seconds / 60:g} minutes: the playlist and the timer tasks start anyway, and what shows the time may be wrong until it is.")
		else:
			self.logger.info(f"'{self.name}' the clock is set: the layers start.")
			self._startup(msg.timestamp, "clock-ready", "The clock is set: the playlist and the timer tasks start.")
		self._start_layers(*held)
	def _end_clock_wait(self):
		if self._clock_timer is not None:
			self._clock_timer.cancel()
			self._clock_timer = None
	def _show_setup_notice(self, width: int, height: int, timestamp: datetime):
		"""A device nobody has claimed shows how to claim it on its own panel for a while: whoever can see it is the owner."""
		try:
			lines = self.setup_notice() if self.setup_notice is not None else None
			if not lines or self.cm is None:
				return
			# the lines say where to open the web app and the code: not an error, so no "cannot show this" and no hint about the settings
			image = render_error_image(self.cm.static_manager(), (width, height), SETUP_TITLE, lines, current_inputs(self.cm.settings_manager()), heading="EINK BILLBOARD", hint=False,
				qr=self.setup_claim_url() if self.setup_claim_url is not None else None, credit=SETUP_CREDIT)
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
	@handles(SetupDone)
	def _setup_done(self, msg: SetupDone):
		if self.router is None:
			return
		self.router.send("display", PriorityRevoke(msg.timestamp, SETUP_TITLE))
		held, self._held = self._held, None
		if held is not None:
			self.logger.info(f"'{self.name}' the device was claimed: the layers start.")
			self._startup(msg.timestamp, "set-up", "The device was set up: the playlist and the timer tasks start.")
			self._start_when_clock_set(msg.timestamp, *held)
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
	def _run_trigger_row(self, timestamp: datetime, row: Mapping[str, Any]) -> bool:
		"""Send a button's task to the timer layer: not while the device waits to be claimed, and not for a row with no task set up."""
		content = row.get("content")
		if self.router is None or self._layers_held() or not isinstance(content, dict):
			return False
		self.router.send("timer-layer", RunTrigger(timestamp, f"Button on pin {row.get('pin')}", "priority-update", content))
		return True
	def run_trigger(self, pin: int) -> str:
		"""
		The web app's Run now for the button on `pin` (called from the web app's thread): the task its saved row carries runs as if the button was pressed.
		`ok` or the reason it did not, in our words.
		"""
		if self.router is None or self.cm is None or self._unclaimed() or self._layers_held():
			return "The device is not ready: it is still starting, waiting for its clock to be set, or has not been claimed yet."
		_, devices = self.cm.settings_manager().open("devices").get()
		row = row_with_pin(devices if isinstance(devices, dict) else None, pin)
		if row is None or row.get("action") != "task":
			return "That button does not run a task: save it as a task first."
		try:
			return "ok" if self._run_trigger_row(self._now(), row) else "The task has no settings yet."
		except ValueError:
			return "The device is stopping."
	def run_task(self, task_id: str) -> bool:
		"""Run a timer task now (the web app's Run now, later a button): the timer layer finds it by id and runs it, whatever its trigger. False: the device is not claimed, its layers wait for the clock, or it has stopped."""
		if self.router is None or self._unclaimed() or self._layers_held():
			return False
		try:
			self.router.send("timer-layer", RunTask(self._now(), task_id))
			return True
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the task run.")
			return False
	def content_size(self) -> tuple[int, int]:
		"""The (width, height) an image must have to be shown as it is: the panel's size, swapped for a portrait display (the Display task turns every image, see `target_dimensions`). Raises `PushRefused` while the device is starting."""
		if self._panel is None or self.cm is None:
			raise PushRefused(503, "The device is still starting.")
		width, height = self._panel
		_, settings = self.cm.settings_manager().open("display").get()
		return (height, width) if (settings or {}).get("orientation") == "portrait" else (width, height)
	def push_image(self, title: str, image: Image.Image, minutes: int) -> Pushed:
		"""
		Show `image` over everything for `minutes` (the web API's push; called from its threads, the Application's own thread does the sending). The title is made unique among the messages
		that are about, since a title is what takes a priority image down. Raises `PushRefused`: not claimed yet (storage and panel are the owner's), too many waiting, or stopping.
		"""
		if self.router is None or self._panel is None:
			raise PushRefused(503, "The device is still starting.")
		if self._unclaimed():
			raise PushRefused(403, "This device has not been claimed yet: enter the setup code (on the panel and in the log) in the web app first.")
		now = time.monotonic()
		with self._pushed_lock:
			self._pushed = { key: entry for key, entry in self._pushed.items() if entry[1] > now }
			if len(self._pushed) >= MAX_PUSHED_ACTIVE:
				raise PushRefused(429, f"{MAX_PUSHED_ACTIVE} messages are already waiting or showing: wait for some to finish, or delete them.")
			taken = { entry[0] for entry in self._pushed.values() }
			unique, number = title, 1
			while unique in taken:
				number += 1
				unique = f"{title} ({number})"
			message_id = uuid.uuid4().hex
			self._pushed[message_id] = (unique, now + minutes * 60 + PUSHED_SLACK.total_seconds())
		try:
			self.accept(PushedImage(self._now(), unique, image, timedelta(minutes=minutes)))
		except ValueError:
			with self._pushed_lock:
				self._pushed.pop(message_id, None)
			raise PushRefused(503, "The device is shutting down.") from None
		shown_on = self.display.display if self.display is not None else None
		rest = shown_on.ready_in() if shown_on is not None else 0.0
		return Pushed(message_id, unique, round(rest + COMMIT_SECONDS))
	def revoke_pushed(self, message_id: str) -> bool:
		"""Take a pushed message down (showing, or still waiting). False when there is no such message (never made, or it is over)."""
		with self._pushed_lock:
			entry = self._pushed.pop(message_id, None)
		if entry is None or self.router is None:
			return False
		self.router.send("display", PriorityRevoke(self._now(), entry[0]))
		return True
	@handles(PushedImage)
	def _pushed_image(self, msg: PushedImage):
		"""A pushed image on the application's own thread: on to the display as a priority image, marked as the API's."""
		if self.router is None:
			return
		self.logger.info(f"'{self.name}' pushed: '{msg.title}' for {msg.duration}")
		self.router.send("telemetry", Telemetry(msg.timestamp, "application", { "kind": "pushed", "title": msg.title, "minutes": round(msg.duration.total_seconds() / 60), "message": f"A message was pushed: '{msg.title}'." }))
		self.router.send("display", PriorityImage(msg.timestamp, msg.title, msg.img, msg.duration, origin={ "kind": "api", "title": msg.title, "plugin": "Push API" }))
	@property
	def playback_stopped(self) -> bool:
		"""Whether the playlist layer is stopped by a transport command (what the play/stop button shows)."""
		return self.playlist_layer is not None and self.playlist_layer.halted
	@property
	def playback_position(self) -> tuple[str, str]|None:
		"""The playlist and the track the playlist layer is on, by id (None before its first track)."""
		position = self.playlist_layer.position if self.playlist_layer is not None else None
		return (position.playlist_id, position.track_id) if position is not None else None
	@handles(TransportCommand)
	def _transport_command(self, msg: TransportCommand):
		"""The first hop of a transport command: it goes to the playlist layer only (the timer layer keeps running), and not at all while the device waits to be claimed."""
		if self.router is None:
			return
		if self._layers_held():
			self.logger.info(f"'{self.name}' the layers have not started (not claimed, or the clock is not set): transport command '{msg.command}' ignored.")
			return
		forwarded = { "play": ResumePlayback, "stop": StopPlayback, "next": NextTrack }.get(msg.command)
		if forwarded is None:
			self.logger.warning(f"'{self.name}' unknown transport command '{msg.command}'.")
			return
		self.logger.info(f"'{self.name}' transport: {msg.command}")
		self.router.send("playlist-layer", forwarded(msg.timestamp))
	def claimed(self) -> bool:
		"""Whether the device may be changed by its owner: not waiting for the setup code. Called from the web app's threads."""
		return not self._unclaimed()
	def begin_restore(self) -> str|None:
		"""
		Say that a restore of a backup is about to write files (called from the web app's thread; `end_restore` must follow, in a `finally`). None: go ahead; every change notification is held back
		from now until the restore is over. Otherwise our words for why not: not claimed, one already running, the device busy or stopping.
		"""
		reply: Future = Future()
		try:
			self.accept(RestoreBegin(self._now(), reply))
		except ValueError:
			return "The device is shutting down."
		try:
			return reply.result(timeout=RESTORE_BEGIN_WAIT_SECONDS)
		except FutureTimeoutError:
			# a begin that was never answered must not start later, with nobody to end it
			reply.cancel()
			return "The device is busy: try again in a moment."
	def end_restore(self, ok: bool, count: int) -> None:
		"""The restore wrote its files (`ok`) or put them back (not `ok`); `count` is how many files. Not waited for: the Application settles when the files' change events have passed."""
		try:
			self.accept(RestoreEnd(self._now(), ok, count))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the restore ended.")
	def _restore_timer(self, reason: str) -> Callable[[], None]:
		generation = self._restore_generation
		def fire() -> None:
			try:
				self.accept(RestoreSettled(self._now(), generation, reason))
			except ValueError:
				self.logger.debug(f"'{self.name}' stopped before the restore settled.")
		return fire
	@handles(RestoreBegin)
	def _restore_begin(self, msg: RestoreBegin):
		if not msg.reply.set_running_or_notify_cancel():
			return
		if self._unclaimed():
			msg.reply.set_result("This device has not been claimed yet: enter the setup code (on the panel and in the log) in the web app first.")
			return
		if self._restore_state != "idle":
			msg.reply.set_result("A restore is already running.")
			return
		self._restore_state = "restoring"
		self._restore_generation += 1
		self._restore_absorbed = 0
		# [lease, quiet, cap]: the lease runs now, the other two once the files are written
		self._restore_timers = [Coalescer(self.restore_lease_seconds, self._restore_timer("lease")), Coalescer(self.restore_quiet_seconds, self._restore_timer("quiet")), Coalescer(self.restore_cap_seconds, self._restore_timer("cap"))]
		self._restore_timers[0].trigger()
		self.logger.info(f"'{self.name}' a restore begins: change notifications are held back.")
		msg.reply.set_result(None)
	@handles(RestoreEnd)
	def _restore_end(self, msg: RestoreEnd):
		if self._restore_state != "restoring":
			self.logger.warning(f"'{self.name}' a restore ended that was not running.")
			return
		self._restore_state = "draining"
		self._restore_result = (msg.ok, msg.count)
		self._restore_timers[0].cancel()
		if self.cm is not None:
			self.cm.evict_all()
		# the watcher's events for the files just written arrive a debounce later: settled when none has come for the quiet time, or at the cap
		self._restore_timers[1].trigger()
		self._restore_timers[2].trigger()
	@handles(RestoreSettled)
	def _restore_settled(self, msg: RestoreSettled):
		if msg.generation != self._restore_generation or self._restore_state == "idle":
			return
		if self._restore_state == "restoring":
			if msg.reason != "lease":
				return
			self.logger.warning(f"'{self.name}' a restore did not end in {self.restore_lease_seconds:g}s: the lease ended it.")
			self._restore_result = (False, 0)
		elif msg.reason == "lease":
			return
		self._finish_restore(msg.timestamp)
	def _finish_restore(self, timestamp: datetime):
		"""One notice for the whole restore: every task reads what it needs again, and the viewer hears of it once. An edit made meanwhile is covered by it, never lost."""
		for timer in self._restore_timers:
			timer.cancel()
		self._restore_timers = []
		self._restore_state = "idle"
		ok, count = self._restore_result
		absorbed, self._restore_absorbed = self._restore_absorbed, 0
		if self.cm is not None:
			self.cm.evict_all()
		self.logger.info(f"'{self.name}' the restore is over ({count} files, {absorbed} change events held back).")
		if self.router is None:
			return
		self.router.send("configuration", ConfigurationChanged(timestamp, "restore", "restore", ""))
		self.router.send("telemetry", Telemetry(timestamp, "application", { "kind": "restore", "ok": ok, "files": count, "changed": [EVERYTHING],
			"message": f"A backup was restored: {count} files." if ok else "A backup could not be restored." }))
	def _end_restore_state(self):
		"""A quit clears a restore in progress: no timer outlives the task, and nothing stays held back."""
		for timer in self._restore_timers:
			timer.cancel()
		self._restore_timers = []
		self._restore_state = "idle"
	@handles(SetupCodeChanged)
	def _setup_code_changed(self, msg: SetupCodeChanged):
		"""The page on the panel must not show a code that no longer works: take it down and put the new one up."""
		if self.router is None or self._held is None or self._panel is None:
			return
		self.router.send("display", PriorityRevoke(msg.timestamp, SETUP_TITLE))
		self._show_setup_notice(self._panel[0], self._panel[1], msg.timestamp)
	def _startup(self, timestamp: datetime, kind: str, message: str, **values: Any) -> None:
		"""Say a step of the start on the telemetry (to the hub, as the configure notices go: the router may not be there yet)."""
		if self.sink is not None:
			self.sink.accept(Telemetry(timestamp, "application", { "kind": kind, "message": message, **values }))
	@handles(ConfigureNotify)
	def _configure_notify(self, msg: ConfigureNotify):
		# STEP 4 playback started if layer configured successfully
		self.logger.info(f"'{self.name}' ConfigureNotify {msg.token} {msg.error} {msg.content}.")
		# the hub keeps every outcome for GET /api/status, and the start says each one (the header's status is asked again on them, #520)
		# not `if self.sink`: a hub with no events yet is falsy (it has a length)
		if self.sink is not None:
			self.sink.accept(msg)
		if msg.token in COMPONENTS:
			if msg.error:
				self._up.discard(msg.token)
				self._startup(msg.timestamp, "configure-failed", f"'{msg.token}' could not be configured{ours(msg.content)}.", component=msg.token)
			else:
				self._up.add(msg.token)
				self._startup(msg.timestamp, "configured", f"'{msg.token}' is running.", component=msg.token)
				if self._up == set(COMPONENTS):
					self._startup(msg.timestamp, "running", "The device is running.")

		if msg.token == "playlist-layer":
			if not msg.error:
				self.logger.info(f"'{self.name}' playlist-layer configured successfully.")
			else:
				self.logger.error(f"'{self.name}' Cannot configure playlist-layer")
				self.logger.error(f"{msg.content}")
		if msg.token == "timer-layer":
			if not msg.error:
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
		if self.cm.upgrade_problems:
			# written by a newer version of the app (a downgrade) or not upgradable: left as they are, and said once (the names only)
			self.report_failure(f"These stored settings could not be brought up to this version and are left as they are: {', '.join(self.cm.upgrade_problems)}")
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
		self._end_restore_state()
		self._end_clock_wait()
		self._clock_held = None
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
