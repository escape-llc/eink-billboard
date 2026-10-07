from typing import cast
import unittest
import os
import json
import tempfile

from .utils import storage_path
from ..model.schedule import Playlist, SCHEMA_TASKS
from ..model.schedule_manager import ScheduleManager, ScheduleManagerDict

class TestScheduleManager(unittest.TestCase):
	def test_load_schedule(self):
		# This is a placeholder test. Actual implementation would depend on the filesystem and schedule structure.
		storage = storage_path()
		sm = ScheduleManager(root_path=f"{os.path.join(storage, "schedules")}")
		sinfos = sm.load()
		self.assertIsNotNone(sinfos)
		self.assertIn('tasks', sinfos)
		self.assertIn('playlists', sinfos)
		self.assertGreater(len(sinfos['tasks']), 0)  # Adjust based on expected number of tasks
		self.assertGreater(len(sinfos['playlists']), 0)  # Adjust based on expected number of playlists
		for sinfo in sinfos['playlists']:
			self.assertIn('info', sinfo)
			self.assertIn('path', sinfo)
			self.assertIn('name', sinfo)
			self.assertIn('type', sinfo)
			self.assertIsInstance(sinfo['path'], str)
			self.assertIsInstance(sinfo['name'], str)
			self.assertIsInstance(sinfo['type'], str)
			self.assertIsInstance(sinfo['info'], Playlist)

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
		schedule_list: dict[str, list] = {
			"playlists": [],
			"tasks": []
		}
		with self.assertRaises(ValueError):
			sm.validate(cast(ScheduleManagerDict, schedule_list))

	def test_validate_playlist_info_none(self):
		# master present, but a playlist entry has no 'info'
		sm = ScheduleManager(root_path=storage_path() + os.path.sep + "schedules")
		schedule_list = {
			"playlists": [{"name": "pl1", "info": None}],
			"tasks": []
		}
		with self.assertRaises(ValueError):
			sm.validate(cast(ScheduleManagerDict, schedule_list))

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
				sm.validate(cast(ScheduleManagerDict, None))
			with self.assertRaises(ValueError):
				sm.validate(cast(ScheduleManagerDict, {}))


class TestLoadIgnoresJunk(unittest.TestCase):
	def _good(self) -> dict:
		return {
			"_schema": SCHEMA_TASKS, "id": "good", "name": "Good",
			"items": [{
				"id": "t1", "enabled": True, "title": "T1",
				"task": { "plugin_name": "p", "content": {} },
				"trigger": { "day": { "type": "dayofweek", "days": [1] }, "time": { "type": "specific", "hour": 1, "minute": 0 } }
			}]
		}
	def test_non_schedule_entries_and_bad_files_are_skipped(self):
		with tempfile.TemporaryDirectory() as tmp:
			def write(name, text):
				with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
					f.write(text)
			write("good.json", json.dumps(self._good()))
			write(".gitkeep", "")
			write(".DS_Store", "\x00\x01binary")
			write(".tmp-good.json", "{ half writ")
			write("notes.txt", "hello")
			os.mkdir(os.path.join(tmp, "subfolder"))
			write("broken.json", "{ not json")
			write("empty.json", "")
			write("list.json", "[1, 2]")
			write("noschema.json", json.dumps({ "id": "x" }))
			bad_item = self._good()
			del bad_item["items"][0]["id"]
			write("noid.json", json.dumps(bad_item))
			sm = ScheduleManager(root_path=tmp)
			with self.assertLogs("python.model.schedule_manager", level="WARNING") as logs:
				loaded = sm.load()
			self.assertEqual([x["name"] for x in loaded["tasks"]], ["good.json"])
			self.assertEqual(loaded["playlists"], [])
			text = "\n".join(logs.output)
			for name in ("broken.json", "empty.json", "list.json", "noschema.json", "noid.json"):
				self.assertIn(name, text)
			for name in (".gitkeep", ".DS_Store", "notes.txt", "subfolder"):
				self.assertNotIn(name, text)  # not schedules at all: ignored quietly
