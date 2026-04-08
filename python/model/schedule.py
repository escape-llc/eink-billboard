from typing import Any, Generator, Literal, Sequence, TypeVar, Protocol, TypedDict, runtime_checkable
from datetime import datetime, timedelta

T = TypeVar('T')

@runtime_checkable
class ScheduleItemBase(Protocol):
	@property
	def id(self) -> str: ...
	@property
	def title(self) -> str: ...
	def to_dict(self) -> dict[str,Any]: ...

class PlaylistItem[T](ScheduleItemBase):
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
		return { "id": self.id, "title": self.title }

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
	def __init__(self, id: str, name: str, items: Sequence[ScheduleItemBase]):
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

type TimeTriggerType = Literal["hourly", "hourofday", "specific"]
type DayTriggerType = Literal["dayofweek", "dayofmonth", "dayandmonth"]
class TimeTriggerDict(TypedDict):
	type: TimeTriggerType
	minutes: list[int]
	hours: list[int]
class TimeTriggerSpecificDict(TypedDict):
	type: TimeTriggerType
	minute: int
	hour: int
type TimeTriggers = TimeTriggerDict | TimeTriggerSpecificDict
class DayTriggerDict(TypedDict):
	type: DayTriggerType
	days: list[int]
class DayTriggerSpecificDict(TypedDict):
	type: DayTriggerType
	day: int
	month: int
type DayTriggers = DayTriggerDict | DayTriggerSpecificDict
class TriggerDict(TypedDict):
	time: TimeTriggers
	day: DayTriggers

def generate_trigger_time(now: datetime, time: TimeTriggers, include_now: bool = False) -> Generator[datetime, None, None]:
	"""
	Yield the datetimes that match the given time trigger configuration based on the target time.

	:param now: Target time to evaluate the trigger against
	:type now: datetime
	:param time: Day trigger description dict, must contain "type" key with appropriate sub-keys for trigger evaluation
	:type time: TimeTriggers
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
def generate_schedule(now: datetime, trigger: TriggerDict, include_now: bool = False) -> Generator[datetime, None, None]:
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
def daily_sequence(start_date: datetime, n_days: int) -> Generator[datetime, None, None]:
	start_ts = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
	for ix in range(n_days):
		yield start_ts + timedelta(days=ix)

class TimerTaskTask:
	def __init__(self, plugin_name: str, content: dict):
		if plugin_name is None:
			raise ValueError("plugin_name cannot be None")
		if content is None:
			raise ValueError("content cannot be None")
		self.plugin_name = plugin_name
		self.content = content
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"plugin_name": self.plugin_name,
			"content": self.content.copy()
		}
		return retv
	pass
class TimerTaskItem(ScheduleItemBase):
	def __init__(self, id: str, title: str, enabled: bool, task: TimerTaskTask, trigger: TriggerDict):
		if id is None:
			raise ValueError("id cannot be None")
		if title is None:
			raise ValueError("title cannot be None")
		if task is None:
			raise ValueError("task cannot be None")
		if trigger is None:
			raise ValueError("trigger cannot be None")
		self._id = id
		self._title = title
		self.enabled = enabled
		self.task = task
		self.trigger = trigger
	@property
	def id(self) -> str:
		return self._id
	@property
	def title(self) -> str:
		return self._title
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self._id,
			"enabled": self.enabled,
			"title": self.title,
			"trigger": self.trigger.copy(),
			"task": self.task.to_dict()
		}
		return retv
class TimerTasks:
	def __init__(self, id: str, name: str, items: Sequence[TimerTaskItem]):
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

class RenderScheduleDict(TypedDict):
	schedule: str
	id: str
	scheduled_time: str

def render_task_schedule_at(schedule_ts: datetime, item: TimerTaskItem, schedid: str, render_list: list[RenderScheduleDict], include_now:bool = True) -> bool:
	did = False
	for trigger_ts in generate_schedule(schedule_ts, item.trigger, include_now=include_now):
		render_list.append({
			"schedule": schedid,
			"id": item.id,
			"scheduled_time": trigger_ts.isoformat()
		})
		did = True
	return did