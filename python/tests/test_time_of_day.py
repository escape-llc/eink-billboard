import os
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from ..model.time_of_day import SystemTimeOfDay

@unittest.skipUnless(hasattr(time, "tzset"), "needs POSIX tzset")
class TestSystemTimeOfDay(unittest.TestCase):
	def _with_tz(self, name: str):
		patcher = mock.patch.dict(os.environ, { "TZ": name })
		patcher.start()
		self.addCleanup(time.tzset)
		self.addCleanup(patcher.stop)
		time.tzset()

	def test_carries_the_real_zone_not_a_fixed_offset(self):
		self._with_tz("America/New_York")
		now = SystemTimeOfDay().current_time()
		self.assertIsInstance(now.tzinfo, ZoneInfo)
		self.assertEqual(getattr(now.tzinfo, "key"), "America/New_York")
		# wall-clock arithmetic across the spring-forward gap keeps the zone's rules
		before = datetime(2024, 3, 9, 12, 0, tzinfo=now.tzinfo)
		self.assertEqual((before + timedelta(days=1)).utcoffset(), timedelta(hours=-4))
		self.assertEqual(before.utcoffset(), timedelta(hours=-5))

	def test_explicit_zone_wins(self):
		self._with_tz("America/New_York")
		now = SystemTimeOfDay(ZoneInfo("Europe/Berlin")).current_time()
		self.assertEqual(getattr(now.tzinfo, "key"), "Europe/Berlin")

	def test_unknown_zone_falls_back_to_a_fixed_offset(self):
		self._with_tz("Not/AZone")
		now = SystemTimeOfDay().current_time()
		self.assertIsNotNone(now.utcoffset())

if __name__ == "__main__":
	unittest.main()
