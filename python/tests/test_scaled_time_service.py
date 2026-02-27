import unittest
import time
from datetime import datetime, timezone, timedelta

from .utils import ConstantTimeOfDay, ScaledTimeOfDay, ScaledTimerThreadService, MessageCollectSink, ScaledTimerThreadService

class TestScaledTimeOfDay(unittest.TestCase):
	def test_current_time_scaling(self):
		# Use current time as the reference; start 5 seconds in the past
		now = datetime.now(timezone.utc)
		start = now - timedelta(seconds=5)
		scale = 3.0
		svc = ScaledTimeOfDay(start, scale)
		got = svc.current_time()
		expected_interval = (datetime.now(timezone.utc) - start).total_seconds() * scale
		expected = start + timedelta(seconds=expected_interval)
		# allow a small delta because wall-clock moved between calls
		self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

	def test_current_time_utc_scaling(self):
		now_utc = datetime.now(timezone.utc)
		start = now_utc - timedelta(seconds=7)
		scale = 1.5
		svc = ScaledTimeOfDay(start, scale)
		got = svc.current_time_utc()
		expected_interval = (datetime.now(timezone.utc) - start).total_seconds() * scale
		expected = start + timedelta(seconds=expected_interval)
		self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

	def test_zero_scale_returns_start(self):
		now = datetime.now(timezone.utc)
		start = now - timedelta(seconds=10)
		with self.assertRaises(ValueError):
			ScaledTimeOfDay(start, 0.0)

	def test_scale_60_sleep_one_second(self):
		# start / now are timezone-aware UTC
		start = datetime.now(timezone.utc)
		svc = ScaledTimeOfDay(start, 60.0)
		time.sleep(1.0)
		got = svc.current_time()
		# Expect approximately 60 seconds elapsed relative to start
		elapsed = (got - start).total_seconds()
		self.assertTrue(58.0 <= elapsed <= 62.0, f"elapsed scaled seconds {elapsed} not ~60")

class TestScaledTimerThreadService(unittest.TestCase):
	def test_invalid_scale_raises(self):
		with self.assertRaises(ValueError):
			ScaledTimerThreadService(timebase=ConstantTimeOfDay(datetime.now(timezone.utc)), scale=0.0)
		with self.assertRaises(ValueError):
			ScaledTimerThreadService(timebase=ConstantTimeOfDay(datetime.now(timezone.utc)), scale=-1.0)

	def test_scaled_timer_thread_service_fires(self):
		svc = ScaledTimerThreadService(timebase=ConstantTimeOfDay(datetime.now(timezone.utc)), scale=60.0)
		sink = MessageCollectSink()
		start = time.perf_counter()
		future, cancel = svc.create_timer(timedelta(seconds=60), sink, "token", "state")

		res = future.result(timeout=3.0)
		elapsed = time.perf_counter() - start
		self.assertIsNotNone(res)
		if res is not None:
			self.assertEqual(res.timestamp, svc.timebase.current_time())
			self.assertEqual(res.token, "token")
			self.assertEqual(res.state, "state")
		self.assertTrue(0.9 <= elapsed <= 1.1, f"future resolved in {elapsed} seconds, expected ~1s")
		self.assertTrue(sink.wait_for_message(timeout=0.1))

	def test_scaled_timer_thread_service_cancel(self):
		svc = ScaledTimerThreadService(timebase=ConstantTimeOfDay(datetime.now(timezone.utc)), scale=60.0)
		sink = MessageCollectSink()
		future, cancel = svc.create_timer(timedelta(seconds=60), sink, "token", "state")

		cancel()

		res = future.result(timeout=3.0)
		self.assertIsNone(res)
		self.assertFalse(sink.wait_for_message(timeout=0.5))

if __name__ == "__main__":
    unittest.main()
