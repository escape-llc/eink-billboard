from ..model.hash_manager import HashManager
from ..task.messages import ConfigurationWatcherEvent, MessageSink

class HashManagerEvictionSink(MessageSink):
	def __init__(self, hm: HashManager):
		if hm is None:
			raise ValueError("HashManager cannot be None")
		self.hm = hm
	def accept(self, message: ConfigurationWatcherEvent):
		if message.type in ["modified", "deleted", "moved"]:
			self.hm.evict(message.path)

