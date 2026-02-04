import os
import json
import logging
from typing import List

from .schedule import MasterSchedule, Playlist, TimedSchedule
from .schedule_loader import ScheduleLoader

logger = logging.getLogger(__name__)

MASTER:str = "master_schedule.json"

class ScheduleManager:
	def __init__(self, root_path):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		self.ROOT_PATH = root_path
		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")

	def load(self):
		""" Load all schedules from the root path. 
		Args:
		Returns:
			dict: A dictionary containing the master schedule and a list of schedules.
			keys: "master", "schedules", "playlists", "tasks"
		"""
		master_schedule_file = os.path.join(self.ROOT_PATH, MASTER)
		if not os.path.isfile(master_schedule_file):
			raise FileNotFoundError(f"Master schedule file '{master_schedule_file}' does not exist.")
		item_list:List[TimedSchedule] = []
		for schedule in os.listdir(self.ROOT_PATH):
			logger.debug(f"Found file: {schedule}")
			schedule_path = os.path.join(self.ROOT_PATH, schedule)
			info = ScheduleLoader.loadFile(schedule_path, schedule)
			item_list.append(info)
		master_schedule = next((item for item in item_list if item.get("type") == "urn:inky:storage:schedule:master:1"), None)
		schedule_list = [item for item in item_list if item.get("type") == "urn:inky:storage:schedule:timed:1"]
		playlist_list = [item for item in item_list if item.get("type") == "urn:inky:storage:schedule:playlist:1"]
		tasks_list = [item for item in item_list if item.get("type") == "urn:inky:storage:schedule:tasks:1"]
		return { "master": master_schedule, "schedules": schedule_list, "playlists": playlist_list, "tasks": tasks_list }

	def validate(self, schedule: dict):
		if schedule is None:
			raise ValueError("schedule_list cannot be None")
		master = schedule.get("master", None)
		if master is None:
			raise ValueError("Master schedule is missing.")
		if isinstance(master, MasterSchedule):
			validation_error = master.validate(schedule)
			if validation_error is not None:
				raise ValueError(f"Validation error in master schedule '{master.get('name', 'unknown')}': {validation_error}")
		for playlist in schedule.get("schedules", []):
			info = playlist.get("info", None)
			if info is None:
				raise ValueError(f"Schedule info is None for {playlist.get('name', 'unknown')}")
			elif isinstance(info, TimedSchedule):
				validation_error = info.validate()
				if validation_error is not None:
					raise ValueError(f"Validation error in schedule '{playlist.get('name', 'unknown')}': {validation_error}")
		for playlist in schedule.get("playlists", []):
			info = playlist.get("info", None)
			if info is None:
				raise ValueError(f"Playlist info is None for {playlist.get('name', 'unknown')}")
			if isinstance(info, Playlist):
				validation_error = info.validate()
				if validation_error is not None:
					raise ValueError(f"Validation error in playlist '{playlist.get('name', 'unknown')}': {validation_error}")
		pass