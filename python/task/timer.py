from abc import ABC, abstractmethod
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import timedelta
import threading
import logging

from .protocols import CreateTimerResult, IProvideTimer, IRequireShutdown
from .messages import BasicMessage, MessageSink
from .timer_tick import TickMessage

class Timer(ABC):
	def __init__(self, tick: TickMessage, delta: timedelta):
		self.tick = tick
		self.delta = delta
		self.expiration_time = tick.tick_ts + delta
		self.triggered = False
	def trigger(self, tick: TickMessage) -> bool:
		if self.triggered:
			return True
		if tick.tick_ts >= self.expiration_time:
			try:
				self.timer_expired()
				return True
			finally:
				self.triggered = True
		return False
	def was_triggered(self) -> bool:
		return self.triggered
	@abstractmethod
	def timer_expired(self):
		pass

class TimerService(IProvideTimer, IRequireShutdown):
	def __init__(self, es: Executor|None = None):
		self._es = es if es is not None else ThreadPoolExecutor(max_workers=4)
		self.logger = logging.getLogger(__name__)
	def create_timer(self, deltatime: timedelta, sink: MessageSink|None, completed: BasicMessage) -> CreateTimerResult:
		"""
		Creates a timer that waits for deltatime and then sends the completed message to the sink.
		Returns a tuple of (future, cancel_function). The future completes with the completed message when the timer expires, or None if cancelled.
		"""
		stopped = threading.Event()
		def fx() -> BasicMessage|None:
			try:
				self.logger.debug(f"Sleep {deltatime}")
				timeout = stopped.wait(deltatime.total_seconds())
				self.logger.debug(f"Stopped {timeout}")
				if not timeout:
					if sink is not None:
						self.logger.debug(f"sending message {completed}")
						sink.accept(completed)
					return completed
				else:
					return None
			except Exception as ex:
				self.logger.error(f"Timer exception: {ex}")
		def cancel() -> None:
			self.logger.debug("Timer cancel requested.")
			stopped.set()
		future = self._es.submit(fx)
		return (future, cancel)
	def shutdown(self):
		if self._es is not None:
			self._es.shutdown(wait=True, cancel_futures=True)