import datetime
import unittest
import time

from .utils import ScaledTimeService


class TestScaledTimeService(unittest.TestCase):
    def test_current_time_scaling(self):
        # Use current time as the reference; start 5 seconds in the past
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - datetime.timedelta(seconds=5)
        scale = 3.0
        svc = ScaledTimeService(start, scale)
        got = svc.current_time()
        expected_interval = (datetime.datetime.now(start.tzinfo) - start).total_seconds() * scale
        expected = start + datetime.timedelta(seconds=expected_interval)
        # allow a small delta because wall-clock moved between calls
        self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

    def test_current_time_utc_scaling(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        start = now_utc - datetime.timedelta(seconds=7)
        scale = 1.5
        svc = ScaledTimeService(start, scale)
        got = svc.current_time_utc()
        expected_interval = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds() * scale
        expected = start + datetime.timedelta(seconds=expected_interval)
        self.assertAlmostEqual((got - expected).total_seconds(), 0.0, delta=0.25)

    def test_zero_scale_returns_start(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - datetime.timedelta(seconds=10)
        with self.assertRaises(ValueError):
            ScaledTimeService(start, 0.0)

    def test_scale_60_sleep_one_second(self):
        # start / now are timezone-aware UTC
        start = datetime.datetime.now(datetime.timezone.utc)
        svc = ScaledTimeService(start, 60.0)
        time.sleep(1.0)
        got = svc.current_time()
        # Expect approximately 60 seconds elapsed relative to start
        elapsed = (got - start).total_seconds()
        self.assertTrue(58.0 <= elapsed <= 62.0, f"elapsed scaled seconds {elapsed} not ~60")


if __name__ == "__main__":
    unittest.main()
