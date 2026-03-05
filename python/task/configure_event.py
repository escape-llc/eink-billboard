from dataclasses import dataclass
from typing import Any

from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider
from ..task.messages import BasicMessage, MessageWithContent
from ..task.protocols import MessageSink

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

