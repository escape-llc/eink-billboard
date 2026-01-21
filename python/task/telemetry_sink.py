import queue
from .messages import BasicMessage, MessageSink

class TelemetrySink(MessageSink):
	def __init__(self):
		self.msg_queue = queue.Queue()

	def receive(self):
		try:
			return self.msg_queue.get_nowait()
		except queue.Empty as em:
			return None
		except Exception as e:
			return None

	def accept(self, msg: BasicMessage):
		try:
			self.msg_queue.put_nowait(msg)
		except Exception as e:
			pass
