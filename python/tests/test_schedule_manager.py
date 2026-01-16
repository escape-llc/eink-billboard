import unittest
import os
import tempfile

from .utils import storage_path
from ..model.schedule import MasterSchedule, Playlist, TimedSchedule, SchedulableItem


# Concrete SchedulableItem for tests (SchedulableItem is abstract)
class ConcreteSchedItem(SchedulableItem):
	def to_dict(self):
		return {
			"id": self.id,
			"title": self.title,
			"start_minutes": self.start_minutes,
			"duration_minutes": self.duration_minutes,
			"content": self.content,
		}
from ..model.schedule_manager import ScheduleManager

class TestScheduleManager(unittest.TestCase):
	def test_load_schedule(self):
		# This is a placeholder test. Actual implementation would depend on the filesystem and schedule structure.
		storage = storage_path()
		sm = ScheduleManager(root_path=f"{os.path.join(storage, "schedules")}")
		sinfos = sm.load()
		self.assertIsNotNone(sinfos)
		self.assertIn('master', sinfos)
		self.assertIn('schedules', sinfos)
		self.assertIn('playlists', sinfos)
		self.assertGreater(len(sinfos['schedules']), 0)  # Adjust based on expected number of schedules
		self.assertGreater(len(sinfos['playlists']), 0)  # Adjust based on expected number of playlists
		for sinfo in sinfos['schedules']:
			self.assertIn('info', sinfo)
			self.assertIn('path', sinfo)
			self.assertIn('name', sinfo)
			self.assertIn('type', sinfo)
			self.assertIsInstance(sinfo['path'], str)
			self.assertIsInstance(sinfo['name'], str)
			self.assertIsInstance(sinfo['type'], str)
			self.assertIsInstance(sinfo['info'], TimedSchedule)
		for sinfo in sinfos['playlists']:
			self.assertIn('info', sinfo)
			self.assertIn('path', sinfo)
			self.assertIn('name', sinfo)
			self.assertIn('type', sinfo)
			self.assertIsInstance(sinfo['path'], str)
			self.assertIsInstance(sinfo['name'], str)
			self.assertIsInstance(sinfo['type'], str)
			self.assertIsInstance(sinfo['info'], Playlist)
		info = sinfos['master']
		if isinstance(info, MasterSchedule):
			self.assertIsNotNone(info.defaultSchedule)
			self.assertIsNotNone(info.schedules)
			for item in info.schedules:
				self.assertIsNotNone(item.id)
				self.assertIsNotNone(item.name)
				self.assertIsNotNone(item.enabled)
				self.assertIsNotNone(item.description)
				self.assertIsNotNone(item.schedule)
				self.assertIsNotNone(item.trigger)

	def test_validate(self):
		storage = storage_path()
		sm = ScheduleManager(root_path=f"{os.path.join(storage, "schedules")}")
		sinfos = sm.load()
		self.assertIsNotNone(sinfos)
		self.assertGreater(len(sinfos), 0)
		sm.validate(sinfos)
		pass

	def test_validate_schedule_info_none(self):
		# master present, but a schedule entry has no 'info'
		sm = ScheduleManager(root_path=storage_path() + os.path.sep + "schedules")
		schedule_list = {
			"master": {},
			"schedules": [{"name": "s1", "info": None}],
			"playlists": [],
			"tasks": []
		}
		with self.assertRaises(ValueError):
			sm.validate(schedule_list)

	def test_validate_playlist_info_none(self):
		# master present, but a playlist entry has no 'info'
		sm = ScheduleManager(root_path=storage_path() + os.path.sep + "schedules")
		schedule_list = {
			"master": {},
			"schedules": [],
			"playlists": [{"name": "pl1", "info": None}],
			"tasks": []
		}
		with self.assertRaises(ValueError):
			sm.validate(schedule_list)

	def test_validate_timed_schedule_validation_error(self):
		# construct a TimedSchedule with overlapping items so validate() returns overlaps
		item1 = ConcreteSchedItem("i1", "one", 0, 60, None)
		item2 = ConcreteSchedItem("i2", "two", 30, 60, None)
		timed = TimedSchedule("ts1", "TestTimed", items=[item1, item2])
		sm = ScheduleManager(root_path=storage_path() + os.path.sep + "schedules")
		schedule_list = {
			"master": {},
			"schedules": [{"name": "ts1", "info": timed}],
			"playlists": [],
			"tasks": []
		}
		with self.assertRaises(ValueError):
			sm.validate(schedule_list)

	def test_ctor_invalid_root_path(self):
		with self.assertRaises(ValueError):
			ScheduleManager(None)

	def test_ctor_nonexistent_root_path(self):
		with self.assertRaises(ValueError):
			ScheduleManager("/path/that/does/not/exist_12345")

	def test_validate_invalid_parameters(self):
		import tempfile
		with tempfile.TemporaryDirectory() as tmp:
			sm = ScheduleManager(root_path=tmp)
			with self.assertRaises(ValueError):
				sm.validate(None)
			with self.assertRaises(ValueError):
				sm.validate({})
