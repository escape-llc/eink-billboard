import unittest
import tempfile
import json
from datetime import datetime, timedelta

from python.model.schedule_manager import SCHEMA_PLAYLIST

from ..model.schedule_loader import ScheduleLoader

class TestScheduleLoader(unittest.TestCase):
    def test_load_schedule_from_json(self):
        # Create a temporary JSON file with schedule data
        now = datetime.now().replace(second=0, microsecond=0)
        schedule_data = {
        "_schema": SCHEMA_PLAYLIST,
        "name": "Test Playlist",
        "id": "test-playlist",
        "items": [
		{
			"type": "PlaylistSchedule",
			"plugin_name": "slide-show",
			"id": "0",
			"title": "0 Item",
			"content": {
				"dataSource": "comic",
				"comic": "XKCD",
				"fontSize": 12,
				"titleCaption": True,
				"maxCount": 4,
				"slideMinutes": 2
			}
		},
		{
			"type": "PlaylistSchedule",
			"plugin_name": "slide-show",
			"id": "1",
			"title": "1 Item",
			"content": {
				"dataSource": "comic",
				"comic": "Cyanide & Happiness",
				"fontSize": 12,
				"titleCaption": True,
				"maxCount": 4,
				"slideMinutes": 2
			}
		},
        ]
        }
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
            json.dump(schedule_data, tmp)
            tmp.flush()
            filename = tmp.name

        # Load the schedule using ScheduleLoader
        info = ScheduleLoader.loadFile(filename, "Test Schedule")

        # Assertions
        schedule = info["info"]
        self.assertEqual(schedule.name, "Test Playlist")
        self.assertEqual(len(schedule.items), 2)
        self.assertEqual(schedule.items[0].id, "0")
        self.assertEqual(schedule.items[1].id, "1")
        self.assertEqual(schedule.items[0].title, "0 Item")
        self.assertEqual(schedule.items[1].title, "1 Item")

if __name__ == "__main__":
    unittest.main()