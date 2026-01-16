import unittest
from datetime import datetime, timedelta
import random
import string

from ..model.schedule import (
	TimedSchedule,
	PluginSchedule,
	PluginScheduleData,
	Playlist,
	PlaylistSchedule,
	PlaylistScheduleData,
	TimerTaskTask,
	TimerTaskItem,
	TimerTasks,
	generate_schedule,
	generate_trigger_time,
)

def random_plugin_data():
	return PluginScheduleData({
		'value': random.randint(1, 100),
		'info': ''.join(random.choices(string.ascii_letters, k=8))
	})

class TestSchedule(unittest.TestCase):
	def setUp(self):
			now = datetime.now().replace(second=0, microsecond=0)
			self.items = [
					PluginSchedule(
						plugin_name="PluginA",
						id="1",
						title="First",
						start_minutes=0,
						duration_minutes=30,
						content=random_plugin_data()
					),
					PluginSchedule(
						plugin_name="PluginB",
						id="2",
						title="Second",
						start_minutes=25,
						duration_minutes=30,
						content=random_plugin_data()
					),
					PluginSchedule(
						plugin_name="PluginC",
						id="3",
						title="Third",
						start_minutes=60,
						duration_minutes=15,
						content=random_plugin_data()
					),
			]
			self.schedule = TimedSchedule("test-schedule", "TestSchedule", self.items)
			self.schedule.set_date_controller(lambda: now)

	def test_sorted_items(self):
		sorted_items = self.schedule.sorted_items
		self.assertEqual(sorted_items[0].start, min(item.start for item in self.items))
		self.assertEqual(sorted_items[-1].start, max(item.start for item in self.items))

	def test_check_overlap(self):
		# Overlaps with first and second
		overlap_item = PluginSchedule(
			plugin_name="PluginX",
			id="X",
			title="Overlap",
			start_minutes=self.items[0].start_minutes + 20,
			duration_minutes=20,
			content=random_plugin_data()
		)
		offending = self.schedule.check(overlap_item)
		self.assertIsNotNone(offending)
		self.assertIn(offending.id, ["1", "2"])

		# No overlap
		no_overlap_item = PluginSchedule(
			plugin_name="PluginY",
			id="Y",
			title="NoOverlap",
			start_minutes=self.items[2].start_minutes + self.items[2].duration_minutes + 1,
			duration_minutes=10,
			content=random_plugin_data()
		)
		self.assertIsNone(self.schedule.check(no_overlap_item))

	def test_current(self):
		# Should be in first item
		ts = self.items[0].start + timedelta(minutes=10)
		current = self.schedule.current(ts)
		self.assertIsNotNone(current)
		self.assertEqual(current.id, "1")

		# Should be in second item (overlap region)
		ts = self.items[1].start + timedelta(minutes=5)
		current = self.schedule.current(ts)
		self.assertIsNotNone(current)
		self.assertEqual(current.id, "2")

		# Should be None (outside all items)
		ts = self.items[2].end + timedelta(minutes=5)
		self.assertIsNone(self.schedule.current(ts))

	def test_validate(self):
		# Should raise ValueError due to overlap between items 1 and 2
		result = self.schedule.validate()
		self.assertIsNotNone(result)

		# Remove overlap and validate should not raise
		non_overlapping_items = [
				PluginSchedule(
					plugin_name="PluginA",
					id="1",
					title="First",
					start_minutes=self.items[0].start_minutes,
					duration_minutes=10,
					content=random_plugin_data()
				),
				PluginSchedule(
					plugin_name="PluginB",
					id="2",
					title="Second",
					start_minutes=self.items[0].start_minutes + 15,
					duration_minutes=10,
					content=random_plugin_data()
				),
		]
		schedule_no_overlap = TimedSchedule("NoOverlap", non_overlapping_items)
		overlaps = schedule_no_overlap.validate()
		self.assertIsNone(overlaps)

	def test_plugin_schedule_to_dict(self):
		ps = PluginSchedule(
			plugin_name="PluginZ",
			id="pz",
			title="PZ",
			start_minutes=5,
			duration_minutes=10,
			content=PluginScheduleData({"foo": "bar"}),
		)
		d = ps.to_dict()
		self.assertEqual(d["id"], "pz")
		self.assertEqual(d["plugin_name"], "PluginZ")
		self.assertIn("content", d)
		self.assertEqual(d["content"], {"foo": "bar"})

	def test_playlist_and_playlist_schedule_to_dict(self):
		pl_item = PlaylistSchedule(
			plugin_name="PluginP",
			id="pl1",
			title="PL1",
			content=PlaylistScheduleData({"a": 1}),
		)
		playlist = Playlist("plist", "MyPlaylist", items=[pl_item])
		d = playlist.to_dict()
		self.assertEqual(d["id"], "plist")
		self.assertEqual(d["name"], "MyPlaylist")
		self.assertEqual(d["_schema"], "urn:inky:storage:schedule:playlist:1")
		self.assertIsInstance(d["items"], list)
		self.assertEqual(d["items"][0]["plugin_name"], "PluginP")

	def test_timed_schedule_to_dict(self):
		ps1 = PluginSchedule("PluginA", "t1", "T1", 0, 10, PluginScheduleData({}))
		ps2 = PluginSchedule("PluginB", "t2", "T2", 20, 5, PluginScheduleData({}))
		ts = TimedSchedule("tsid", "TSName", items=[ps1, ps2])
		d = ts.to_dict()
		self.assertEqual(d["id"], "tsid")
		self.assertEqual(d["name"], "TSName")
		self.assertEqual(d["_schema"], "urn:inky:storage:schedule:timed:1")
		self.assertEqual(len(d["items"]), 2)

	def test_timer_task_to_dicts(self):
		task = TimerTaskTask("p1", "TaskTitle", 15, {"x": 1})
		td = task.to_dict()
		self.assertEqual(td["plugin_name"], "p1")
		self.assertEqual(td["title"], "TaskTitle")
		self.assertEqual(td["duration_minutes"], 15)

		item = TimerTaskItem("it1", "ItemName", True, "desc", task, {"time": {}})
		idct = item.to_dict()
		self.assertEqual(idct["id"], "it1")
		self.assertEqual(idct["task"]["plugin_name"], "p1")

		tasks = TimerTasks("tid", "TasksName", items=[item])
		tdct = tasks.to_dict()
		self.assertEqual(tdct["id"], "tid")
		self.assertEqual(tdct["_schema"], "urn:inky:storage:schedule:tasks:1")
		self.assertEqual(len(tdct["items"]), 1)

class TestTriggers(unittest.TestCase):
	def test_generate_trigger_time_hourly(self):
		now = datetime(2024, 1, 1, 10, 15)  # Jan 1, 2024, 10:15 AM
		time_config = {
			"type": "hourly",
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
		trigger_config = {
			"day": {
				"type": "dayofweek",
				"days": [0,1,2,3,4,5,6]  # Every day
			},
			"time": {
				"type": "hourly",
				"minutes": [0]
			}
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