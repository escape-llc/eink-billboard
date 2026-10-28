from concurrent.futures import Future
import threading
from typing import Any, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from PIL import Image

from ..model.service_container import IServiceProvider

@dataclass(frozen=True, slots=True)
class BasicMessage:
	"""Base class for all messages."""
	timestamp: datetime
	def __post_init__(self):
		# 1. Directly access the class's raw annotations to avoid get_type_hints failure
		ann = self.__class__.__annotations__
		for field_name, expected_type in ann.items():
			val = getattr(self, field_name)
			# 2. Universal None Guard: Check for "Optional" by string or type
			type_str = str(expected_type)
			is_optional = "None" in type_str or "Optional" in type_str
			if val is None:
				if not is_optional:
					raise ValueError(f"Field '{field_name}' cannot be None")
				continue
			# 3. Structural Validation (The Fix for 'datetime' vs 'datetime')
			# Instead of isinstance, we check if the object has the core attributes of the type
			if "timedelta" in type_str.lower():
				# Duck-typing: If it has 'days' and 'seconds', it's a timedelta object
				if not (hasattr(val, "days") and hasattr(val, "seconds")):
					raise TypeError(f"Field '{field_name}' must be a timedelta object")
			elif "datetime" in type_str.lower():
				# Duck-typing: If it has 'year' and 'strftime', it's a datetime object
				if not (hasattr(val, "year") and hasattr(val, "strftime")):
					raise TypeError(f"Field '{field_name}' must be a datetime object")
			
			elif "int" in type_str.lower():
				if not isinstance(val, int):
					raise TypeError(f"Field '{field_name}' must be an int")

@dataclass(frozen=True, slots=True)
class QuitMessage(BasicMessage):
	"""Message to signal the thread to quit."""
	pass

@dataclass(frozen=True, slots=True)
class MessageWithContent[T](BasicMessage):
	"""Message to execute a command with content."""
	content: T

@dataclass(frozen=True, slots=True)
class StartOptions:
	"""Options for starting the application."""
	basePath: str|None = None
	storagePath: str|None = None
	hardReset: bool = False
@dataclass(frozen=True, slots=True)
class StartEvent(BasicMessage):
	"""Event to start the application with given options and timer task."""
	options: StartOptions
	root: IServiceProvider

@dataclass(frozen=True, slots=True)
class StopEvent(BasicMessage):
	"""Event to stop the application."""
	pass

@dataclass(frozen=True, slots=True)
class FutureCompleted(BasicMessage):
	plugin_name: str
	token: str
	result: Any|None = None
	error: Any|None = None

@dataclass(frozen=True, slots=True)
class AsyncTaskCompleted(BasicMessage):
	token: str
	fut: Future
	donev: threading.Event

@dataclass(frozen=True, slots=True)
class Telemetry(BasicMessage):
	name: str
	values: Mapping[str,Any]

@dataclass(frozen=True, slots=True)
class ConfigurationWatcherEvent(BasicMessage):
	type: str
	path: str

@dataclass(frozen=True, slots=True)
class SetupDone(BasicMessage):
	"""The device was claimed (the web app set its password): the setup page comes down and the layers may start."""

@dataclass(frozen=True, slots=True)
class ClockCheck(BasicMessage):
	"""The Application's own: time to look again whether the clock is set, while the layers wait for it (#785)."""

@dataclass(frozen=True, slots=True)
class TransportCommand(BasicMessage):
	"""A viewer's play, stop or next (the web app, later a button on the device), for the Application to forward to the playlist layer."""
	command: str

@dataclass(frozen=True, slots=True)
class InputEvent(BasicMessage):
	"""
	Something that happened at an input connected to the device (a button pressed). A device puts it on the `DeviceIO` task's queue from its own thread; `DeviceIO` forwards it on the
	`device-input` route, and the Application gives it a meaning (its bindings: `python/device/bindings.py`). `source` is the device (`buttons`), `name` which input of it (`next`),
	`gesture` what was done (`press`, `long-press`).
	"""
	source: str
	name: str
	gesture: str

@dataclass(frozen=True, slots=True)
class PushedImage(BasicMessage):
	"""
	An image someone pushed through the API (`POST /api/display/message` or `/image`), already made and fitted to the panel, for the Application to put on the display as a priority image
	for `duration`. `title` is what the panel's telemetry calls it, and what takes it down again (`PriorityRevoke`).
	"""
	title: str
	img: Image.Image
	duration: timedelta

@dataclass(frozen=True, slots=True)
class ReloadDevices(BasicMessage):
	"""The DeviceIO task's own request (after it coalesced a burst of ConfigurationChanged) to read the devices' settings again and open what they say."""

@dataclass(frozen=True, slots=True)
class SetupCodeChanged(BasicMessage):
	"""The setup code was replaced (too many wrong ones): the setup page on the panel shows the new one."""

@dataclass(frozen=True, slots=True)
class ConfigurationChanged(BasicMessage):
	"""
	Sent by the application to every task when something under the storage root changed (after the watcher's debounce).
	`area` is where: schedules, settings, schemas, plugins, datasources or other; `type` and `path` are the watcher's.
	"""
	area: str
	type: str
	path: str

@dataclass(frozen=True, slots=True)
class RestoreBegin(BasicMessage):
	"""
	A restore of a backup is about to write many files (`Application.begin_restore`, from the web app's thread). The Application answers on `reply`: None when it may go ahead (it
	then holds back every per-file notification until the restore is over), or our words for why not (the device is not claimed, a restore is already running).
	"""
	reply: Future

@dataclass(frozen=True, slots=True)
class RestoreEnd(BasicMessage):
	"""The restore wrote its files (`ok`: all of them, or none: a failed one was put back); `count` is how many. The Application settles after the files' own change events have passed."""
	ok: bool
	count: int

@dataclass(frozen=True, slots=True)
class RestoreSettled(BasicMessage):
	"""The Application's own: the quiet after a restore (`quiet`), its limit (`cap`) or the lease on a restore that never ended (`lease`) has passed. `generation` tells a late one from an old restore."""
	generation: int
	reason: str

@dataclass(frozen=True, slots=True)
class ReloadSchedules(BasicMessage):
	"""A layer's own request (after it coalesced a burst of ConfigurationChanged) to re-read the schedules and re-plan."""
	pass

@dataclass(frozen=True, slots=True)
class RunTask(BasicMessage):
	"""Run a timer task now, by its id (a button, the web app's Run now): sent to the timer layer, which runs it whatever its trigger says."""
	task_id: str

@dataclass(frozen=True, slots=True)
class RunTrigger(BasicMessage):
	"""A button's task (the Devices settings' Trigger Task) to run now: this plugin with this content, for the timer layer. `title` names the button, for the panel's origin line and the telemetry."""
	title: str
	plugin_name: str
	content: dict

@dataclass(frozen=True, slots=True)
class TimerExpired[T](BasicMessage):
	token: str
	state: T
