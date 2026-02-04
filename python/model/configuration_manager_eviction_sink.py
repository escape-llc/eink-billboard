from .configuration_manager import ConfigurationManager
from ..task.messages import ConfigurationWatcherEvent, MessageSink

class ConfigurationManagerEvictionSink(MessageSink):
	def __init__(self, cm: ConfigurationManager):
		if cm is None:
			raise ValueError("ConfigurationManager cannot be None")
		self.cm = cm
	def accept(self, message: ConfigurationWatcherEvent):
		if message.type in ["modified", "deleted", "moved"]:
			self.cm.evict(message.path)