from typing import cast
import unittest
from datetime import datetime, timedelta

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

if __name__ == "__main__":
    unittest.main()