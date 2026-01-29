import datetime
import unittest
import time
from concurrent.futures import ThreadPoolExecutor

from .utils import ScaledTimeOfDay, ScaledTimerService, FakePort
from ..task.messages import BasicMessage

class TestScaledTimeOfDay(unittest.TestCase):
	def test_current_time_scaling(self):
		# Use current time as the reference; start 5 seconds in the past
		now = datetime.datetime.now(datetime.timezone.utc)
		start = now - datetime.timedelta(seconds=5)
		scale = 3.0
		svc = ScaledTimeOfDay(start, scale)
		got = svc.current_time()
		expected_interval = (datetime.datetime.now(start.tzinfo) - start).total_seconds() * scale
		expected = start + datetime.timedelta(seconds=expected_interval)
		# allow a small delta because wall-clock moved between calls
		self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

	def test_current_time_utc_scaling(self):
		now_utc = datetime.datetime.now(datetime.timezone.utc)
		start = now_utc - datetime.timedelta(seconds=7)
		scale = 1.5
		svc = ScaledTimeOfDay(start, scale)
		got = svc.current_time_utc()
		expected_interval = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds() * scale
		expected = start + datetime.timedelta(seconds=expected_interval)
		self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

	def test_zero_scale_returns_start(self):
		now = datetime.datetime.now(datetime.timezone.utc)
		start = now - datetime.timedelta(seconds=10)
		with self.assertRaises(ValueError):
			ScaledTimeOfDay(start, 0.0)

	def test_scale_60_sleep_one_second(self):
		# start / now are timezone-aware UTC
		start = datetime.datetime.now(datetime.timezone.utc)
		svc = ScaledTimeOfDay(start, 60.0)
		time.sleep(1.0)
		got = svc.current_time()
		# Expect approximately 60 seconds elapsed relative to start
		elapsed = (got - start).total_seconds()
		self.assertTrue(58.0 <= elapsed <= 62.0, f"elapsed scaled seconds {elapsed} not ~60")

class TestScaledTimerService(unittest.TestCase):
	def test_scaled_timer_fires_and_returns_message(self):
		# Use a ThreadPoolExecutor explicitly to avoid relying on a missing name in utils
		with ThreadPoolExecutor(max_workers=2) as ex:
			svc = ScaledTimerService(scale=60.0, es=ex)
			sink = FakePort()
			msg = BasicMessage(datetime.datetime.now(datetime.timezone.utc))
			start = time.perf_counter()
			future, cancel = svc.create_timer(datetime.timedelta(seconds=60), sink, msg)

			# Future should complete in ~1s of real elapsed time (60 scaled by 60)
			res = future.result(timeout=3.0)
			elapsed = time.perf_counter() - start
			self.assertIs(res, msg)
			self.assertTrue(0.9 <= elapsed <= 1.1, f"future resolved in {elapsed} seconds, expected ~1s")

			# Confirm sink received the message
			self.assertTrue(sink.wait_for_message(timeout=0.1))

			svc.shutdown()

	def test_scaled_timer_can_be_cancelled(self):
		with ThreadPoolExecutor(max_workers=2) as ex:
			svc = ScaledTimerService(scale=60.0, es=ex)
			sink = FakePort()
			msg = BasicMessage(datetime.datetime.now(datetime.timezone.utc))
			future, cancel = svc.create_timer(datetime.timedelta(seconds=60), sink, msg)

			# Cancel immediately
			cancel()

			# Future should complete with None and sink should not receive a message
			res = future.result(timeout=3.0)
			self.assertIsNone(res)
			self.assertFalse(sink.wait_for_message(timeout=0.5))

			svc.shutdown()


if __name__ == "__main__":
    unittest.main()
