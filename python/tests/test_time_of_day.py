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

class TestConfiguredTimeOfDay(unittest.TestCase):
	def test_uses_the_named_zone(self):
		from ..model.time_of_day import ConfiguredTimeOfDay
		now = ConfiguredTimeOfDay(lambda: "Asia/Tokyo").current_time()
		self.assertEqual(now.utcoffset().total_seconds(), 9 * 3600)

	def test_follows_a_change_without_restart(self):
		from ..model.time_of_day import ConfiguredTimeOfDay
		name = ["Asia/Tokyo"]
		tod = ConfiguredTimeOfDay(lambda: name[0])
		self.assertEqual(tod.current_time().utcoffset().total_seconds(), 9 * 3600)
		name[0] = "UTC"
		self.assertEqual(tod.current_time().utcoffset().total_seconds(), 0)

	def test_unknown_or_failing_source_falls_back_to_the_machine_zone(self):
		from ..model.time_of_day import ConfiguredTimeOfDay
		self.assertIsNotNone(ConfiguredTimeOfDay(lambda: "Not/AZone").current_time().tzinfo)
		def boom(): raise RuntimeError("x")
		self.assertIsNotNone(ConfiguredTimeOfDay(boom).current_time().tzinfo)
