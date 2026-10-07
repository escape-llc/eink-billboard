import collections
import threading
from .messages import BasicMessage
from .protocols import MessageSink

class TelemetrySink(MessageSink):
	"""Collects telemetry for the host; bounded, so an unread sink cannot grow without limit (the oldest messages are dropped)."""
	MAX_MESSAGES = 1000

	def __init__(self, max_messages: int|None = None):
		self.max_messages = max_messages if max_messages is not None else self.MAX_MESSAGES
		self._lock = threading.Lock()
		self.msg_queue: collections.deque[BasicMessage] = collections.deque(maxlen=self.max_messages)

	def __len__(self) -> int:
		with self._lock:
			return len(self.msg_queue)

	def receive(self) -> BasicMessage|None:
		"""Returns the oldest retained message, or None when there is none."""
		with self._lock:
			return self.msg_queue.popleft() if self.msg_queue else None

	def accept(self, msg: BasicMessage):
		with self._lock:
			# a full deque drops its oldest entry
			self.msg_queue.append(msg)
