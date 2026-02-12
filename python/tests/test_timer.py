from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import unittest

from ..task.messages import BasicMessage, MessageSink
from ..task.timer_tick import TickMessage
from ..task.timer import Timer, TimerService

class TestTimer(Timer):
	def __init__(self, tick, delta):
		super().__init__(tick, delta)
		self.expired = False
	def timer_expired(self):
		self.expired = True

class ExceptionTimer(Timer):
	def __init__(self, tick, delta):
		super().__init__(tick, delta)
		self.expired = False
	def timer_expired(self):
		raise Exception("Timer deliberate exception for testing")

class TestTimerTick(unittest.TestCase):
	def test_timer_expires(self):
		initial_tick = TickMessage(datetime.now(), 0)
		timer = TestTimer(initial_tick, timedelta(seconds=2))
		self.assertFalse(timer.was_triggered())
		next_tick = TickMessage(initial_tick.tick_ts + timedelta(seconds=1), 1)
		self.assertFalse(timer.trigger(next_tick))
		next_tick = TickMessage(initial_tick.tick_ts + timedelta(seconds=2), 2)
		self.assertTrue(timer.trigger(next_tick))
		self.assertTrue(timer.was_triggered())
		self.assertTrue(timer.expired)
	def test_timer_throws(self):
		initial_tick = TickMessage(datetime.now(), 0)
		timer = ExceptionTimer(initial_tick, timedelta(seconds=2))
		self.assertFalse(timer.was_triggered())
		next_tick = TickMessage(initial_tick.tick_ts + timedelta(seconds=1), 1)
		self.assertFalse(timer.trigger(next_tick))
		next_tick = TickMessage(initial_tick.tick_ts + timedelta(seconds=2), 2)
		try:
			timer.trigger(next_tick)
		except Exception:
			self.assertTrue(timer.was_triggered())
			self.assertFalse(timer.expired)

class TestSink(MessageSink):
	def __init__(self):
		self.received = False
		self.message = None
	def accept(self, message: BasicMessage):
		self.received = True
		self.message = message

SLEEP_INTERVAL = 0.1
class TestTimerService(unittest.TestCase):
	def test_timer_service(self):
		sink = TestSink()
		timer_service = TimerService(ThreadPoolExecutor())
		execute_message = BasicMessage(datetime.now())
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), sink, execute_message)
		self.assertFalse(sink.received)
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(sink.received)
		self.assertTrue(timer_future.done())
		self.assertIs(timer_future.result(), execute_message)
		self.assertFalse(timer_future.cancelled())
		self.assertIs(sink.message, execute_message)
		timer_service.shutdown()
	def test_timer_service_no_sink(self):
		timer_service = TimerService(ThreadPoolExecutor())
		execute_message = BasicMessage(datetime.now())
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), None, execute_message)
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(timer_future.done())
		self.assertIs(timer_future.result(), execute_message)
		self.assertFalse(timer_future.cancelled())
		timer_service.shutdown()
	def test_timer_cancel(self):
		sink = TestSink()
		timer_service = TimerService(ThreadPoolExecutor())
		execute_message = BasicMessage(datetime.now())
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), sink, execute_message)
		self.assertFalse(sink.received)
		# already running so it won't cancel
		didit = timer_future.cancel()
		self.assertFalse(didit)
		# this sets the event to cancel the timer
		cancel()
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertFalse(sink.received)
		self.assertTrue(timer_future.done())
		self.assertIs(timer_future.result(), None)
		self.assertFalse(timer_future.cancelled())
		self.assertIs(sink.message, None)
		timer_service.shutdown()
	def test_timer_cancel_no_sink(self):
		timer_service = TimerService(ThreadPoolExecutor())
		execute_message = BasicMessage(datetime.now())
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), None, execute_message)
		# already running so it won't cancel
		didit = timer_future.cancel()
		self.assertFalse(didit)
		# this sets the event to cancel the timer
		cancel()
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(timer_future.done())
		self.assertIs(timer_future.result(), None)
		self.assertFalse(timer_future.cancelled())
		timer_service.shutdown()

if __name__ == "__main__":
	unittest.main()