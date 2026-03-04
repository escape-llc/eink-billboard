import os
import logging
from typing import TypedDict

from .schedule import Playlist
from .schedule_loader import ScheduleLoader, ScheduleLoaderDict

logger = logging.getLogger(__name__)

class ScheduleManagerDict(TypedDict):
	playlists: list[ScheduleLoaderDict]
	tasks: list[ScheduleLoaderDict]

class ScheduleManager:
	def __init__(self, root_path):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		self.ROOT_PATH = root_path
		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")

	def load(self) -> ScheduleManagerDict:
		""" Load all schedules from the root path. 
		Args:
		Returns:
			dict: A dictionary containing the master schedule and a list of schedules.
			keys: "playlists", "tasks"
		"""
		item_list:list[ScheduleLoaderDict] = []
		for schedule in os.listdir(self.ROOT_PATH):
			logger.debug(f"Found file: {schedule}")
			schedule_path = os.path.join(self.ROOT_PATH, schedule)
			info = ScheduleLoader.loadFile(schedule_path, schedule)
			item_list.append(info)
		playlist_list = [item for item in item_list if item.get("type") == "urn:inky:storage:schedule:playlist:1"]
		tasks_list = [item for item in item_list if item.get("type") == "urn:inky:storage:schedule:tasks:1"]
		return { "playlists": playlist_list, "tasks": tasks_list }

	def validate(self, schedule: ScheduleManagerDict) -> None:
		if schedule is None:
			raise ValueError("schedule_list cannot be None")
		# TODO validate schedule.get("tasks",[])
		tasks = schedule.get("tasks", [])
		if len(tasks) == 0:
			raise ValueError("No tasks found in schedule")
		playlists = schedule.get("playlists", [])
		if len(playlists) == 0:
			raise ValueError("No playlists found in schedule")
		for playlist in playlists:
			info = playlist.get("info", None)
			if info is None:
				raise ValueError(f"Playlist info is None for {playlist.get('name', 'unknown')}")
			if isinstance(info, Playlist):
				validation_error = info.validate()
				if validation_error is not None:
					raise ValueError(f"Validation error in playlist '{playlist.get('name', 'unknown')}': {validation_error}")
		pass