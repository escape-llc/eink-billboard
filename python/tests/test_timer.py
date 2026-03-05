from datetime import datetime, timedelta
import unittest

from ..model.time_of_day import SystemTimeOfDay
from ..task.messages import BasicMessage, TimerExpired
from ..task.protocols import MessageSink
from ..task.timer_tick import TickMessage
from ..task.timer import Timer, TimerThreadService

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
		tick_ts = datetime.now()
		initial_tick = TickMessage(datetime.now(), tick_ts, 0)
		timer = TestTimer(initial_tick, timedelta(seconds=2))
		self.assertFalse(timer.was_triggered())
		next_tick = TickMessage(tick_ts, initial_tick.tick_ts + timedelta(seconds=1), 1)
		self.assertFalse(timer.trigger(next_tick))
		next_tick = TickMessage(tick_ts, initial_tick.tick_ts + timedelta(seconds=2), 2)
		self.assertTrue(timer.trigger(next_tick))
		self.assertTrue(timer.was_triggered())
		self.assertTrue(timer.expired)
	def test_timer_throws(self):
		tick_ts = datetime.now()
		initial_tick = TickMessage(datetime.now(), tick_ts, 0)
		timer = ExceptionTimer(initial_tick, timedelta(seconds=2))
		self.assertFalse(timer.was_triggered())
		next_tick = TickMessage(tick_ts, initial_tick.tick_ts + timedelta(seconds=1), 1)
		self.assertFalse(timer.trigger(next_tick))
		next_tick = TickMessage(tick_ts, initial_tick.tick_ts + timedelta(seconds=2), 2)
		try:
			timer.trigger(next_tick)
		except Exception:
			self.assertTrue(timer.was_triggered())
			self.assertFalse(timer.expired)

class TestSink(MessageSink):
	def __init__(self):
		self.received = False
		self.message = None
	def accept(self, msg: BasicMessage):
		self.received = True
		self.message = msg

SLEEP_INTERVAL = 0.1
class TestTimerThreadService(unittest.TestCase):
	def test_timer_thread_service(self):
		sink = TestSink()
		timebase = SystemTimeOfDay()
		timer_service = TimerThreadService(timebase)
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), sink, "token", "state")
		self.assertFalse(sink.received)
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(sink.received)
		self.assertTrue(timer_future.done())
		fr = timer_future.result()
		self.assertIsNotNone(fr)
		self.assertIsInstance(fr, TimerExpired)
		if fr is not None:
			self.assertEqual(fr.token, "token")
			self.assertEqual(fr.state, "state")
		self.assertIsNotNone(sink.message)
		self.assertIsInstance(sink.message, TimerExpired)
		if sink.message is not None and isinstance(sink.message, TimerExpired):
			self.assertEqual(sink.message.token, "token")
			self.assertEqual(sink.message.state, "state")
	def test_timer_thread_service_no_sink(self):
		timebase = SystemTimeOfDay()
		timer_service = TimerThreadService(timebase)
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=SLEEP_INTERVAL), None, "token", "state")
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(timer_future.done())
		fr = timer_future.result()
		self.assertIsNotNone(fr)
		self.assertIsInstance(fr, TimerExpired)
		if fr is not None:
			self.assertEqual(fr.token, "token")
			self.assertEqual(fr.state, "state")
	def test_timer_thread_service_cancel(self):
		sink = TestSink()
		timebase = SystemTimeOfDay()
		timer_service = TimerThreadService(timebase)
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=2*SLEEP_INTERVAL), sink, "token", "state")
		self.assertFalse(sink.received)
		cancel()
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertFalse(sink.received)
		self.assertTrue(timer_future.done())
		self.assertIsNone(timer_future.result())
		self.assertIsNone(sink.message)
	def test_timer_thread_service_cancel_no_sink(self):
		timebase = SystemTimeOfDay()
		timer_service = TimerThreadService(timebase)
		(timer_future, cancel) = timer_service.create_timer(timedelta(seconds=2*SLEEP_INTERVAL), None, "token", "state")
		cancel()
		timer_future.result(timeout=2 * SLEEP_INTERVAL)
		self.assertTrue(timer_future.done())
		self.assertIsNone(timer_future.result())

if __name__ == "__main__":
	unittest.main()