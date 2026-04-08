import json
from typing import Literal, ReadOnly, TypedDict
import uuid

from .schedule import Playlist, PlaylistSchedule, PlaylistScheduleData, TimerTaskItem, TimerTaskTask, TimerTasks

type LoaderType = Playlist|TimerTasks

type SchemaType = Literal["urn:inky:storage:schedule:playlist:1", "urn:inky:storage:schedule:tasks:1"]

class ScheduleLoaderDict(TypedDict):
	info: ReadOnly[LoaderType]
	name: ReadOnly[str]
	path: ReadOnly[str]
	type: ReadOnly[SchemaType]

class ScheduleLoader:
	@staticmethod
	def loadFile(path: str, name: str) -> ScheduleLoaderDict:
		with open(path, 'r', encoding='utf-8') as f:
			data = json.load(f)
		schema = data.get("_schema", None)
		if schema is None:
			raise ValueError(f"Schedule file '{path}' is missing _schema field.")
		if schema == "urn:inky:storage:schedule:playlist:1":
			info = ScheduleLoader.parsePlaylist(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		elif schema == "urn:inky:storage:schedule:tasks:1":
			info = ScheduleLoader.parseTimerTasks(data)
			return { "info": info, "name": name, "path": path, "type": schema }
		else:
			raise ValueError(f"Unknown schema '{schema}' in schedule file '{path}'.")
	@staticmethod
	def loadString(s: str) -> LoaderType:
		data = json.loads(s)
		schema = data.get("_schema", None)
		if schema is None:
			raise ValueError(f"Schedule is missing _schema field.")
		if schema == "urn:inky:storage:schedule:playlist:1":
			info = ScheduleLoader.parsePlaylist(data)
			return info
		elif schema == "urn:inky:storage:schedule:tasks:1":
			info = ScheduleLoader.parseTimerTasks(data)
			return info
		else:
			raise ValueError(f"Unknown schema '{schema}' in schedule.")

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
			title = entry.get("title", entry.get("name", ""))
			enabled = entry.get("enabled", True)
			etask = entry.get("task", None)
			if etask is None:
				raise ValueError(f"Timer task entry '{id}' is missing 'task' field.")
			plugin_name = etask.get("plugin_name", None)
			if plugin_name is None:
				raise ValueError(f"Timer task entry '{id}' is missing 'plugin_name' in 'task' field.")
			content = etask.get("content", None)
			if content is None:
				raise ValueError(f"Timer task entry '{id}' is missing 'content' in 'task' field.")
			trigger = entry.get("trigger", None)
			if trigger is None:
				raise ValueError(f"Timer task entry '{id}' is missing 'trigger' field.")
			# only TimerTaskTask is supported currently
			task = TimerTaskTask(plugin_name, content)
			item = TimerTaskItem(id, title, enabled, task, trigger)
			items.append(item)
		return TimerTasks(sid, name, items)