from typing import Any, Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime

from ..model.configuration_manager import ConfigurationManager
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
			if "datetime" in type_str.lower():
				# Duck-typing: If it has 'year' and 'strftime', it's a datetime object
				if not (hasattr(val, "year") and hasattr(val, "strftime")):
					raise TypeError(f"Field '{field_name}' must be a datetime object")
			
			elif "int" in type_str.lower():
				if not isinstance(val, int):
					raise TypeError(f"Field '{field_name}' must be an int")


@runtime_checkable
class MessageSink(Protocol):
	"""Ability to accept messages."""
	def accept(self, msg: BasicMessage):
		pass

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
class ConfigureOptions:
	"""Options for configuring tasks."""
	cm: ConfigurationManager
	isp: IServiceProvider

@dataclass(frozen=True, slots=True)
class ConfigureEvent(MessageWithContent[ConfigureOptions]):
	"""Event to configure tasks with given options."""
	token: str
	notifyTo: MessageSink|None = None
	def notify(self, error: bool = False, content = None):
		if self.notifyTo is not None:
			self.notifyTo.accept(ConfigureNotify(self.timestamp, self.token, error, content))

@dataclass(frozen=True, slots=True)
class ConfigureNotify(BasicMessage):
	token: str
	error: bool
	content: Any|None = None

@dataclass(frozen=True, slots=True)
class FutureCompleted(BasicMessage):
	plugin_name: str
	token: str
	result: Any|None = None
	error: Any|None = None

@dataclass(frozen=True, slots=True)
class PluginReceive(BasicMessage):
	pass

@dataclass(frozen=True, slots=True)
class Telemetry(BasicMessage):
	name: str
	values: dict[str,Any]

@dataclass(frozen=True, slots=True)
class ConfigurationWatcherEvent(BasicMessage):
	type: str
	path: str
