from typing import Protocol
from typing import Generic, TypeVar
from datetime import datetime

from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider

T = TypeVar('T')

class BasicMessage:
	"""Base class for all messages."""
	def __init__(self, timestamp: datetime = datetime.now()):
		self.timestamp = timestamp

class MessageSink(Protocol):
	"""Ability to accept messages."""
	def accept(self, msg: BasicMessage):
		pass

class QuitMessage(BasicMessage):
	"""Message to signal the thread to quit."""
	def __init__(self, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)

class MessageWithContent(BasicMessage, Generic[T]):
	"""Message to execute a command with content."""
	def __init__(self, content: T, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)
		self.content = content

class StartOptions:
	"""Options for starting the application."""
	def __init__(self, basePath: str = None, storagePath: str = None, hardReset: bool = False):
		self.basePath = basePath
		self.storagePath = storagePath
		self.hardReset = hardReset
class StartEvent(BasicMessage):
	"""Event to start the application with given options and timer task."""
	def __init__(self, options: StartOptions = None, root: IServiceProvider = None, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)
		self.options = options
		self.root = root

class StopEvent(BasicMessage):
	"""Event to stop the application."""
	def __init__(self, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)

class ConfigureOptions:
	"""Options for configuring tasks."""
	def __init__(self, cm: ConfigurationManager):
		if cm is None:
			raise ValueError("cm cannot be None")
		self.cm = cm
class ConfigureEvent(MessageWithContent[ConfigureOptions]):
	"""Event to configure tasks with given options."""
	def __init__(self, token: str, content = None, notifyTo: MessageSink = None, timestamp: datetime = datetime.now()):
		super().__init__(content, timestamp)
		self.token = token
		self.notifyTo = notifyTo
	def notify(self, error: bool = False, content = None):
		if self.notifyTo is not None:
			self.notifyTo.accept(ConfigureNotify(self.token, error, content))

class ConfigureNotify(BasicMessage):
	def __init__(self, token: str, error: bool = False, content = None, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)
		self.token = token
		self.error = error
		self.content = content

class FutureCompleted(BasicMessage):
	def __init__(self, plugin_name: str, token: str, result, error = None, timestamp: datetime = datetime.now()):
		super().__init__(timestamp)
		self.plugin_name = plugin_name
		self.token = token
		self.result = result
		self.error = error
		self.is_success = error is None
	def __repr__(self):
		return f" plugin_name='{self.plugin_name}' token='{self.token}' is_success={self.is_success} error={self.error} result={self.result}"

class PluginReceive(BasicMessage):
	def __init__(self, timestamp: datetime = None):
		super().__init__(timestamp)

class Telemetry(BasicMessage):
	def __init__(self, name: str, values: dict[str,any], timestamp: datetime = datetime.now()):
		super().__init__(timestamp)
		self._name = name
		self._values = values
	@property
	def name(self) -> str:
		return self._name
	@property
	def values(self) -> dict[str,any]:
		return self._values