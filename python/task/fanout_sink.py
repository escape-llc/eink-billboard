import logging
from .messages import BasicMessage
from .protocols import MessageSink

logger = logging.getLogger(__name__)

class FanoutSink(MessageSink):
	"""Offers every message to its sinks in the order they were added; one that fails does not keep the others from hearing it."""
	def __init__(self, *sinks: MessageSink):
		self._sinks: list[MessageSink] = list(sinks)
	def add(self, sink: MessageSink) -> None:
		self._sinks.append(sink)
	def accept(self, msg: BasicMessage):
		for sink in list(self._sinks):
			try:
				sink.accept(msg)
			except Exception as e:
				logger.error(f"{type(sink).__name__} failed to accept {type(msg).__name__}: {e}", exc_info=True)
