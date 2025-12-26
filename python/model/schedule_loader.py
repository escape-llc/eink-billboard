import json
from datetime import datetime
import uuid

from ..model.hash_manager import HashManager
from .schedule import MasterSchedule, MasterScheduleItem, Playlist, PlaylistSchedule, PlaylistScheduleData, TimedSchedule, PluginSchedule, PluginScheduleData, TimerTaskItem, TimerTaskTask, TimerTasks

class ScheduleLoader:
	@staticmethod
	def loadFile(path: str, name: str, hm: HashManager = None) -> dict:
		with open(path, 'r', encoding='utf-8') as f:
			data = json.load(f)
		schema = data.get("_schema", None)
		if schema is None:
			raise ValueError(f"Schedule file '{path}' is missing _schema field.")
		if schema == "urn:inky:storage:schedule:timed:1":
			if hm is not None:
				hm.hash_document(data['id'], path, data)
			info = ScheduleLoader.parseTimed(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		elif schema == "urn:inky:storage:schedule:master:1":
			if hm is not None:
				hm.hash_document(data['id'], path, data)
			info = ScheduleLoader.parseMaster(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		elif schema == "urn:inky:storage:schedule:playlist:1":
			if hm is not None:
				hm.hash_document(data['id'], path, data)
			info = ScheduleLoader.parsePlaylist(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		elif schema == "urn:inky:storage:schedule:tasks:1":
			if hm is not None:
				hm.hash_document(data['id'], path, data)
			info = ScheduleLoader.parseTimerTasks(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		else:
			raise ValueError(f"Unknown schema '{schema}' in schedule file '{path}'.")
	@staticmethod
	def loadString(s: str) -> TimedSchedule:
		data = json.loads(s)
		schema = data.get("_schema", None)
		if schema is None:
			raise ValueError(f"Schedule is missing _schema field.")
		if schema == "urn:inky:storage:schedule:timed:1":
			info = ScheduleLoader.parseTimed(data)
			return info
		elif schema == "urn:inky:storage:schedule:master:1":
			info = ScheduleLoader.parseMaster(data)
			return info
		elif schema == "urn:inky:storage:schedule:playlist:1":
			info = ScheduleLoader.parsePlaylist(data)
			return info
		elif schema == "urn:inky:storage:schedule:tasks:1":
			info = ScheduleLoader.parseTimerTasks(data)
			return info
		else:
			raise ValueError(f"Unknown schema '{schema}' in schedule.")

	@staticmethod
	def parseMaster(data: dict) -> MasterSchedule:
		defsched = data.get("defaultSchedule", None)
		schedulesp = data.get("schedules", None)
		if defsched is None or schedulesp is None:
			raise ValueError("Invalid master schedule data")
		schedules = []
		for entry in schedulesp:
			id = entry["id"]
			name = entry.get("name", None)
			description = entry.get("description", None)
			enabled = bool(entry.get("enabled", False))
			schedule = entry.get("schedule", None)
			trigger = entry.get("trigger", None)
			schedules.append(MasterScheduleItem(id, name, description, trigger, enabled, schedule))
		return MasterSchedule(defsched, schedules)

	@staticmethod
	def parseTimed(data: dict) -> TimedSchedule:
		name = data.get("name", "Unnamed Schedule")
		sid = data.get("id", str(uuid.uuid4()))
		items = []
		for entry in data.get("items", []):
			item_type = entry.get("type", "")
			id = entry["id"]
			title = entry.get("title", "")
			start = int(entry["start_minutes"])
			duration = int(entry["duration_minutes"])

			# Use type field to determine which Python class to instantiate
			if item_type == "PluginSchedule":
				content = entry.get("content", {})
				plugin_name = entry.get("plugin_name", "")
				plugin_data = PluginScheduleData(content)
				item = PluginSchedule(
					plugin_name=plugin_name,
					id=id,
					title=title,
					start_minutes=start,
					duration_minutes=duration,
					content=plugin_data
				)
			else:
				raise ValueError(f"Unknown schedule item type: {item_type}")
			items.append(item)

		return TimedSchedule(sid, name, items)

	@staticmethod
	def parsePlaylist(data: dict) -> Playlist:
		name = data.get("name", "Unnamed Playlist")
		sid = data.get("id", str(uuid.uuid4()))
		items = []
		for entry in data.get("items", []):
			item_type = entry.get("type", "")
			id = entry["id"]
			title = entry.get("title", "")

			# Use type field to determine which Python class to instantiate
			if item_type == "PlaylistSchedule":
				content = entry.get("content", {})
				plugin_name = entry.get("plugin_name", "")
				plugin_data = PlaylistScheduleData(content)
				item = PlaylistSchedule(
					plugin_name=plugin_name,
					id=id,
					title=title,
					content=plugin_data
				)
			else:
				raise ValueError(f"Unknown playlist item type: {item_type}")
			items.append(item)

		return Playlist(sid, name, items)
	
	@staticmethod
	def parseTimerTasks(data: dict) -> TimerTasks:
		name = data.get("name", "Unnamed Playlist")
		sid = data.get("id", str(uuid.uuid4()))
		items = []
		for entry in data.get("items", []):
			id = entry["id"]
			title = entry.get("title", "")
			desc = entry.get("description", "")
			enabled = entry.get("enabled", True)
			etask = entry.get("task", None)
			if etask is None:
				raise ValueError(f"Timer task entry '{title}' is missing 'task' field.")
			# only TimerTaskTask is supported currently
			task = TimerTaskTask(
				etask.get("plugin_name", None),
				etask.get("title", None),
				etask.get("duration_minutes", None),
				etask.get("content", {}))
			item = TimerTaskItem(id, title, enabled, desc, task, entry.get("trigger", {}))
			items.append(item)
		return TimerTasks(sid, name, items)