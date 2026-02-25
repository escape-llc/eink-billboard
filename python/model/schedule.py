from abc import abstractmethod, ABC
from typing import Any, Callable, Generator, Generic, Sequence, TypeVar, List, Protocol, runtime_checkable
from datetime import datetime, timedelta

T = TypeVar('T')

class SchedulableBase(ABC):
	def __init__(self, id: str, title: str, start_minutes: int, duration_minutes: int, dc: Callable|None = None):
		self.id = id
		self.title = title
		self.start_minutes = start_minutes
		self.duration_minutes = duration_minutes
		self.date_controller = dc if dc is not None else lambda : datetime.now()
	@property
	def start(self) -> datetime:
		if self.date_controller is None:
			raise ValueError("Date controller is not set")
		# start at midnight
		the_date = self.date_controller().replace(hour=0, minute=0, second=0, microsecond=0)
		return the_date + timedelta(minutes=self.start_minutes)
	@property
	def end(self) -> datetime:
		return self.start + timedelta(minutes=self.duration_minutes)
	@abstractmethod
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self.id,
			"title": self.title,
			"start_minutes": self.start_minutes,
			"duration_minutes": self.duration_minutes
		}
		return retv

class SchedulableItem(SchedulableBase, Generic[T]):
	def __init__(self, id: str, title: str, start_minutes: int, duration_minutes: int, content: T, dc: Callable|None = None):
		super().__init__(id, title, start_minutes, duration_minutes, dc)
		self.content = content

class PluginScheduleData:
	def __init__(self, data: dict):
		self.data = data

class PluginSchedule(SchedulableItem[PluginScheduleData]):
	def __init__(self, plugin_name: str, id: str, title: str, start_minutes: int, duration_minutes: int, content: PluginScheduleData, dc: Callable|None = None):
		super().__init__(id, title, start_minutes, duration_minutes, content, dc)
		self.plugin_name = plugin_name
	def to_dict(self) -> dict[str,Any]:
		retv = super().to_dict()
		retv["plugin_name"] = self.plugin_name
		retv["content"] = self.content.data
		return retv

class DefaultItem:
	def __init__(self, plugin_name: str, title: str, content: dict):
		self.plugin_name = plugin_name
		self.title = title
		self.content = content

@runtime_checkable
class PlaylistBase(Protocol):
	@property
	def id(self) -> str: ...
	@property
	def title(self) -> str: ...
	def to_dict(self) -> dict[str,Any]: ...

class PlaylistItem(PlaylistBase, Generic[T]):
	def __init__(self, id: str, title: str, content: T):
		self._id = id
		self._title = title
		self.content = content
	@property
	def id(self) -> str:
		return self._id
	@property
	def title(self) -> str:
		return self._title
	def to_dict(self) -> dict[str,Any]:
		return {"id": self.id, "title": self.title}

class PlaylistScheduleData:
	def __init__(self, data: dict):
		self.data = data

class PlaylistSchedule(PlaylistItem[PlaylistScheduleData]):
	def __init__(self, plugin_name: str, id: str, title: str, content: PlaylistScheduleData):
		super().__init__(id, title, content)
		self.plugin_name = plugin_name
	def to_dict(self) -> dict[str,Any]:
		retv = super().to_dict()
		retv["plugin_name"] = self.plugin_name
		retv["content"] = self.content.data.copy()
		return retv

class Playlist:
	def __init__(self, id: str, name: str, items: Sequence[PlaylistBase]):
		if items is None:
			raise ValueError("items cannot be None")
		self._id = id
		self._title = name
		# legacy attribute
		self.name = name
		self.items = items
	@property
	def id(self) -> str:
		return self._id
	@property
	def title(self) -> str:
		return self._title
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self.id,
			"name": self.name,
			"_schema": "urn:inky:storage:schedule:playlist:1",
			"items": [xx.to_dict() for xx in self.items]
		}
		return retv
	def validate(self):
		return None

def generate_trigger_time(now: datetime, time: dict[str,Any], include_now: bool = False) -> Generator[datetime, None, None]:
	"""
	Yield the datetimes that match the given time trigger configuration based on the target time.

	:param now: Target time to evaluate the trigger against
	:type now: datetime
	:param time: Day trigger description dict, must contain "type" key with appropriate sub-keys for trigger evaluation
	:type time: dict[str, Any]
	:param include_now: Whether to include the current time if it matches the trigger
	:type include_now: bool
	"""
	time_type = time.get("type", None)
	if time_type is None:
		raise ValueError("Time Trigger must contain 'type' field")
	match time_type:
		case "hourly":
			minutes = time.get("minutes", [0])
			for hour in range(now.hour, 24):
				for minute in minutes:
					next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
					if next_time < now:
						continue
					elif next_time == now and not include_now:
						continue
					yield next_time
		case "hourofday":
			hours = time.get("hours", [])
			minutes = time.get("minutes", [0])
			for hour in hours:
				for minute in minutes:
					next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
					if next_time < now:
						continue
					elif next_time == now and not include_now:
						continue
					yield next_time
		case "specific":
			hour = time.get("hour", 0)
			minute = time.get("minute", 0)
			next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
			if next_time < now:
				pass
			elif next_time == now and include_now:
				yield next_time
			elif next_time > now:
				yield next_time
		case None:
			pass
	pass
def generate_schedule(now: datetime, trigger: dict[str,Any], include_now: bool = False) -> Generator[datetime, None, None]:
	"""
	Run through the trigger and generate the next trigger time(s) based on the current time.
	Generates for the current day only!
	This generator may yield multiple times if the trigger matches multiple times in the future (e.g. hourly trigger).
	The "day" key in the trigger determines the type of trigger and how to evaluate it against the current time.
	If the day trigger matches the current time, then the "time" key is evaluated to generate the next trigger time(s) for that day.
	
	:param now: Target time to evaluate the trigger against
	:type now: datetime
	:param trigger: Trigger description dict, must contain "day" and "time" keys with appropriate sub-keys for trigger evaluation
	:type trigger: dict[str, Any]
	:param include_now: Whether to include the current time if it matches the trigger
	:type include_now: bool
	:return: Generator yielding the next trigger times based on the current time and trigger configuration
	:rtype: Generator[datetime, None, None]
	"""
	day = trigger.get("day", None)
	time = trigger.get("time", None)
	if day is None or time is None:
		raise ValueError("Trigger must contain 'day' and 'time' fields")
	day_type = day.get("type", None)
	if day_type is None:
		raise ValueError("Day Trigger must contain 'type' field")
	match day_type:
		case "dayofweek":
			days = day.get("days", [])
			if now.weekday() in days:
				yield from generate_trigger_time(now, time, include_now=include_now)
		case "dayofmonth":
			days = day.get("days", [])
			if now.day in days:
				yield from generate_trigger_time(now, time, include_now=include_now)
		case "dayandmonth":
			dday = day.get("day", None)
			month = day.get("month", None)
			if now.day == dday and now.month == month:
				yield from generate_trigger_time(now, time, include_now=include_now)
		case None:
			pass
	pass

class TimerTaskTask:
	def __init__(self, plugin_name: str, title: str, content: dict):
		if plugin_name is None:
			raise ValueError("plugin_name cannot be None")
		if title is None:
			raise ValueError("title cannot be None")
		if content is None:
			raise ValueError("content cannot be None")
		self.plugin_name = plugin_name
		self.title = title
		self.content = content
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"title": self.title,
			"plugin_name": self.plugin_name,
			"content": self.content.copy()
		}
		return retv
	pass
class TimerTaskItem(PlaylistBase):
	def __init__(self, id: str, name: str, enabled: bool, desc: str, task: TimerTaskTask, trigger: dict):
		if id is None:
			raise ValueError("id cannot be None")
		if name is None:
			raise ValueError("name cannot be None")
		if task is None:
			raise ValueError("task cannot be None")
		if trigger is None:
			raise ValueError("trigger cannot be None")
		# store id internally and keep `name` for backward compatibility
		self._id = id
		self.name = name
		self.enabled = enabled
		self.description = desc
		self.task = task
		self.trigger = trigger
	@property
	def id(self) -> str:
		return self._id
	@property
	def title(self) -> str:
		# provide `title` property to satisfy PlaylistBase protocol
		return self.name
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self._id,
			"name": self.name,
			"title": self.title,
			"enabled": self.enabled,
			"description": self.description,
			"trigger": self.trigger.copy(),
			"task": self.task.to_dict()
		}
		return retv
class TimerTasks:
	def __init__(self, id: str, name: str, items: Sequence[TimerTaskItem]|None = None):
		if id is None:
			raise ValueError("id cannot be None")
		if name is None:
			raise ValueError("name cannot be None")
		if items is None:
			raise ValueError("items cannot be None")
		self.id = id
		self.name = name
		self.items: Sequence[TimerTaskItem] = items if items is not None else []
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self.id,
			"name": self.name,
			"_schema": "urn:inky:storage:schedule:tasks:1",
			"items": [xx.to_dict() for xx in self.items]
		}
		return retv