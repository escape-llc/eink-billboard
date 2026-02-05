from .configuration_manager import ConfigurationManager
from ..task.messages import BasicMessage, ConfigurationWatcherEvent, MessageSink

class ConfigurationManagerEvictionSink(MessageSink):
	def __init__(self, cm: ConfigurationManager):
		if cm is None:
			raise ValueError("ConfigurationManager cannot be None")
		self._cm = cm
	def accept(self, msg: BasicMessage):
		if isinstance(msg, ConfigurationWatcherEvent):
			self._cm.watch(msg.type, msg.path)