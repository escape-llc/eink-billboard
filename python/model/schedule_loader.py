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
				etask.get("content", {}))
			item = TimerTaskItem(id, title, enabled, desc, task, entry.get("trigger", {}))
			items.append(item)
		return TimerTasks(sid, name, items)