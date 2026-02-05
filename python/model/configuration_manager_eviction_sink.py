from .configuration_manager import ConfigurationManager
from ..task.messages import BasicMessage, ConfigurationWatcherEvent, MessageSink

class ConfigurationManagerEvictionSink(MessageSink):
	def __init__(self, cm: ConfigurationManager):
		if cm is None:
			raise ValueError("ConfigurationManager cannot be None")
		self._cm = cm
	def accept(self, message: BasicMessage):
		if isinstance(message, ConfigurationWatcherEvent):
			self._cm.watch(message.type, message.path)