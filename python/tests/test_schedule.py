from typing import cast
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..model.schedule import (
	TimeTriggerDict,
	TriggerDict,
	generate_schedule,
	generate_trigger_time,
)

class TestTriggers(unittest.TestCase):
	def test_generate_trigger_time_hourly(self):
		now = datetime(2024, 1, 1, 10, 15)  # Jan 1, 2024, 10:15 AM
		time_config: TimeTriggerDict = {
			"type": "hourly",
			"hours": [10,11,12,13,14,15,16,17,18,19,20,21,22,23],
			"minutes": [0, 30]
		}
		generator = generate_trigger_time(now, time_config)
		expected_times = [
			datetime(2024, 1, 1, 10, 30),
			datetime(2024, 1, 1, 11, 0),
			datetime(2024, 1, 1, 11, 30),
			datetime(2024, 1, 1, 12, 0),
			datetime(2024, 1, 1, 12, 30),
			datetime(2024, 1, 1, 13, 0),
			datetime(2024, 1, 1, 13, 30),
			datetime(2024, 1, 1, 14, 0),
			datetime(2024, 1, 1, 14, 30),
			datetime(2024, 1, 1, 15, 0),
			datetime(2024, 1, 1, 15, 30),
			datetime(2024, 1, 1, 16, 0),
			datetime(2024, 1, 1, 16, 30),
			datetime(2024, 1, 1, 17, 0),
			datetime(2024, 1, 1, 17, 30),
			datetime(2024, 1, 1, 18, 0),
			datetime(2024, 1, 1, 18, 30),
			datetime(2024, 1, 1, 19, 0),
			datetime(2024, 1, 1, 19, 30),
			datetime(2024, 1, 1, 20, 0),
			datetime(2024, 1, 1, 20, 30),
			datetime(2024, 1, 1, 21, 0),
			datetime(2024, 1, 1, 21, 30),
			datetime(2024, 1, 1, 22, 0),
			datetime(2024, 1, 1, 22, 30),
			datetime(2024, 1, 1, 23, 0),
			datetime(2024, 1, 1, 23, 30),
		]
		for expected in expected_times:
			self.assertEqual(next(generator), expected)
		generator = generate_trigger_time(now, time_config)
		for gen in generator:
			self.assertIn(gen, expected_times)

	def test_generate_schedule_daily(self):
		now = datetime(2024, 1, 1, 10, 15)  # Jan 1, 2024, 10:15 AM
		trigger_config: TriggerDict = {
			"day": {
				"type": "dayofweek",
				"days": [0,1,2,3,4,5,6]  # Every day
			},
			"time": cast(TimeTriggerDict, {
				"type": "hourly",
				"hours": [10,11,12,13,14,15,16,17,18,19,20,21,22,23],
				"minutes": [0]
			})
		}
		generator = generate_schedule(now, trigger_config)
		expected_times = [
			datetime(2024, 1, 1, 11, 0),
			datetime(2024, 1, 1, 12, 0),
			datetime(2024, 1, 1, 13, 0),
			datetime(2024, 1, 1, 14, 0),
			datetime(2024, 1, 1, 15, 0),
			datetime(2024, 1, 1, 16, 0),
			datetime(2024, 1, 1, 17, 0),
			datetime(2024, 1, 1, 18, 0),
			datetime(2024, 1, 1, 19, 0),
			datetime(2024, 1, 1, 20, 0),
			datetime(2024, 1, 1, 21, 0),
			datetime(2024, 1, 1, 22, 0),
			datetime(2024, 1, 1, 23, 0),
		]
		for expected in expected_times:
			self.assertEqual(next(generator), expected)

		generator = generate_schedule(now, trigger_config)
		for gen in generator:
			self.assertIn(gen, expected_times)

NY = ZoneInfo("America/New_York")

def _daily(time: dict, day: dict|None = None) -> TriggerDict:
	return cast(TriggerDict, { "day": day if day is not None else { "type": "dayofweek", "days": [0,1,2,3,4,5,6] }, "time": time })

class TestDayMatching(unittest.TestCase):
	def test_dayofweek_is_sunday_zero_like_the_ui(self):
		# 2024-01-07 is a Sunday, 2024-01-01 a Monday
		sunday = datetime(2024, 1, 7, 0, 0, tzinfo=NY)
		monday = datetime(2024, 1, 1, 0, 0, tzinfo=NY)
		at_nine = { "type": "specific", "hour": 9, "minute": 0 }
		only_sunday = _daily(at_nine, { "type": "dayofweek", "days": [0] })
		only_monday = _daily(at_nine, { "type": "dayofweek", "days": [1] })
		self.assertEqual(len(list(generate_schedule(sunday, only_sunday))), 1)
		self.assertEqual(len(list(generate_schedule(monday, only_sunday))), 0)
		self.assertEqual(len(list(generate_schedule(monday, only_monday))), 1)
		self.assertEqual(len(list(generate_schedule(sunday, only_monday))), 0)
		saturday = datetime(2024, 1, 6, 0, 0, tzinfo=NY)
		self.assertEqual(len(list(generate_schedule(saturday, _daily(at_nine, { "type": "dayofweek", "days": [6] })))), 1)

	def test_dayofmonth_minus_one_is_the_last_day(self):
		at_nine = { "type": "specific", "hour": 9, "minute": 0 }
		trigger = _daily(at_nine, { "type": "dayofmonth", "days": [-1] })
		def hits(y, m, d):
			return len(list(generate_schedule(datetime(y, m, d, 0, 0, tzinfo=NY), trigger)))
		self.assertEqual(hits(2024, 2, 29), 1)  # leap year
		self.assertEqual(hits(2024, 2, 28), 0)
		self.assertEqual(hits(2023, 2, 28), 1)
		self.assertEqual(hits(2024, 1, 31), 1)
		self.assertEqual(hits(2024, 4, 30), 1)
		self.assertEqual(hits(2024, 4, 29), 0)
		self.assertEqual(hits(2024, 12, 31), 1)

class TestDaylightSaving(unittest.TestCase):
	def test_nonexistent_local_time_is_normalised(self):
		# 2024-03-10: 02:00 -> 03:00 in New York, so 02:30 does not exist
		midnight = datetime(2024, 3, 10, 0, 0, tzinfo=NY)
		got = list(generate_schedule(midnight, _daily({ "type": "specific", "hour": 2, "minute": 30 }), include_now=True))
		self.assertEqual(len(got), 1)
		self.assertEqual(got[0].isoformat(), "2024-03-10T03:30:00-04:00")

	def test_hourly_on_spring_forward_day_has_no_duplicates_and_is_ordered(self):
		midnight = datetime(2024, 3, 10, 0, 0, tzinfo=NY)
		got = list(generate_schedule(midnight, _daily({ "type": "hourly", "minutes": [0] }), include_now=True))
		instants = [g.timestamp() for g in got]
		self.assertEqual(instants, sorted(set(instants)))
		self.assertEqual(len(got), 23)
		for g in got:
			self.assertEqual(g.utcoffset(), g.astimezone(NY).utcoffset())

	def test_hourly_on_fall_back_day_is_ordered_by_absolute_time(self):
		midnight = datetime(2024, 11, 3, 0, 0, tzinfo=NY)
		got = list(generate_schedule(midnight, _daily({ "type": "hourly", "minutes": [0, 30] }), include_now=True))
		instants = [g.timestamp() for g in got]
		self.assertEqual(instants, sorted(instants))
		self.assertEqual(len(instants), len(set(instants)))
		# every wall-clock slot once (the repeated 01:xx hour fires on its first occurrence only)
		self.assertEqual(len(got), 48)

	def test_comparison_is_by_instant_not_wall_clock(self):
		# 01:45 EST (second pass of the ambiguous hour) is later than 01:30 EDT; the 01:30 trigger has passed.
		now = datetime(2024, 11, 3, 1, 45, tzinfo=NY, fold=1)
		got = list(generate_schedule(now, _daily({ "type": "specific", "hour": 1, "minute": 30 })))
		self.assertEqual(got, [])

class TestValidateTrigger(unittest.TestCase):
	def test_valid_triggers(self):
		from ..model.schedule import validate_trigger
		good = [
			_daily({ "type": "hourly", "minutes": [0, 15, 30, 45] }),
			_daily({ "type": "hourofday", "hours": [9, 17], "minutes": [0] }),
			_daily({ "type": "specific", "hour": 23, "minute": 59 }, { "type": "dayofmonth", "days": [1, -1] }),
			_daily({ "type": "specific", "hour": 0, "minute": 0 }, { "type": "dayandmonth", "day": 29, "month": 2 }),
		]
		for trigger in good:
			self.assertEqual(validate_trigger(trigger), [], trigger)

	def test_invalid_triggers(self):
		from ..model.schedule import validate_trigger
		bad = [
			None, [], {},
			{ "time": { "type": "specific", "hour": 1, "minute": 0 } },
			{ "day": { "type": "dayofweek", "days": [1] } },
			_daily({ "type": "hourofday", "hours": [25], "minutes": [0] }),
			_daily({ "type": "hourofday", "hours": [9], "minutes": [60] }),
			_daily({ "type": "hourofday", "hours": "9", "minutes": [0] }),
			_daily({ "type": "hourly", "minutes": [-1] }),
			_daily({ "type": "specific", "hour": 24, "minute": 0 }),
			_daily({ "type": "specific", "hour": "9", "minute": 0 }),
			_daily({ "type": "nope" }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayofweek", "days": 3 }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayofweek", "days": [7] }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayofmonth", "days": [0] }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayofmonth", "days": [32] }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayandmonth", "day": 1, "month": 13 }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "dayandmonth" }),
			_daily({ "type": "specific", "hour": 1, "minute": 0 }, { "type": "weekly" }),
			_daily({ "type": "specific", "hour": True, "minute": 0 }),
		]
		for trigger in bad:
			self.assertNotEqual(validate_trigger(trigger), [], trigger)

if __name__ == "__main__":
    unittest.main()