from abc import ABC, abstractmethod
import asyncio
from concurrent.futures import Future
from datetime import datetime, timedelta
import threading
import logging
from typing import Callable

from ..model.time_of_day import TimeOfDay
from .protocols import CreateTimerResult, IProvideTimer
from .messages import MessageSink, TimerExpired
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

class TimerThreadService(IProvideTimer):
	def __init__(self, timebase: TimeOfDay, duration: Callable[[timedelta], float] = lambda dt: dt.total_seconds()):
		if timebase is None:
			raise ValueError("timebase cannot be None")
		if duration is None:
			raise ValueError("duration cannot be None")
		self.timebase = timebase
		self.duration = duration
		self.logger = logging.getLogger(__name__)
	def delta_for(self, deltatime: timedelta) -> timedelta:
		return timedelta(seconds=self.duration(deltatime))
	async def sleep(self, deltatime: timedelta) -> None:
		if deltatime is None:
			raise ValueError("deltatime cannot be None")
		if deltatime.total_seconds() < 0:
			raise ValueError("deltatime cannot be negative")
		dur = self.duration(deltatime)
		self.logger.debug(f"Sleeping for {deltatime} ({dur})")
		await asyncio.sleep(dur)
	def create_timer[T](self, deltatime: timedelta, sink: MessageSink|None, token: str, state: T) -> CreateTimerResult[T]:
		if deltatime is None:
			raise ValueError("deltatime cannot be None")
		if deltatime.total_seconds() < 0:
			raise ValueError("deltatime cannot be negative")
		if token is None:
			raise ValueError("token cannot be None")
		def __timer_expired(fut: Future, sink: MessageSink|None, token:str, state: T):
			# CRITICAL: Check if the future is already cancelled or finished
			if fut.cancelled() or fut.done():
					self.logger.debug(f"'{token}' Timer expired but future is already done/cancelled.")
					return
			self.logger.debug(f"'{token}' Timer expired {deltatime}, state {state}")
			msg = TimerExpired(self.timebase.current_time(), token, state)
			# resolve the Future before sending to sink
			try:
				fut.set_result(msg)
			except Exception as ex:
				self.logger.error(f"'{token}' Failed to set result: {ex}")
			try:
				if sink is not None:
					sink.accept(msg)
			except Exception as ex:
				self.logger.error(f"'{token}' Failed to send message to sink: {ex}")
		fut = Future()
		timer = threading.Timer(self.duration(deltatime), __timer_expired, args=(fut, sink, token, state))
		def __cancel_all():
			self.logger.debug(f"'{token}' Cancel requested")
			timer.cancel()
			if not fut.done():
				fut.set_result(None)
		timer.start()
		return (fut, __cancel_all)
	pass
