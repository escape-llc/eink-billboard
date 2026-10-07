from typing import Any, Generator, Literal, Sequence, TypeVar, Protocol, TypedDict, runtime_checkable
import calendar
from datetime import datetime, timedelta, timezone

SCHEMA_PLAYLIST = "urn:inky:storage:schedule:playlist:1"
SCHEMA_TASKS = "urn:inky:storage:schedule:tasks:1"

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
			"_schema": SCHEMA_PLAYLIST,
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

def _is_int(value: Any) -> bool:
	return isinstance(value, int) and not isinstance(value, bool)

def _int_list(value: Any, low: int, high: int, name: str, problems: list[str], allowed_extra: tuple[int, ...] = ()) -> None:
	if not isinstance(value, list):
		problems.append(f"{name} must be a list of whole numbers")
		return
	for entry in value:
		if not _is_int(entry) or not (low <= entry <= high or entry in allowed_extra):
			problems.append(f"{name} has an invalid entry (expected {low} to {high})")
			return

def validate_trigger(trigger: Any) -> list[str]:
	"""
	Check a trigger's shape and ranges without evaluating it. Returns the problems found, empty when it is usable.
	The messages are our own text and never echo the stored values, so they are safe to show to the client.
	"""
	problems: list[str] = []
	if not isinstance(trigger, dict):
		return ["trigger must be an object"]
	day = trigger.get("day", None)
	time = trigger.get("time", None)
	if not isinstance(day, dict):
		problems.append("trigger needs a 'day' object")
	else:
		match day.get("type", None):
			case "dayofweek":
				_int_list(day.get("days", None), 0, 6, "day.days (0=Sunday)", problems)
			case "dayofmonth":
				_int_list(day.get("days", None), 1, 31, "day.days", problems, allowed_extra=(-1,))
			case "dayandmonth":
				dday, month = day.get("day", None), day.get("month", None)
				if not _is_int(dday) or not 1 <= dday <= 31:
					problems.append("day.day must be a whole number from 1 to 31")
				if not _is_int(month) or not 1 <= month <= 12:
					problems.append("day.month must be a whole number from 1 to 12")
			case _:
				problems.append("day.type must be dayofweek, dayofmonth or dayandmonth")
	if not isinstance(time, dict):
		problems.append("trigger needs a 'time' object")
	else:
		match time.get("type", None):
			case "hourly":
				_int_list(time.get("minutes", [0]), 0, 59, "time.minutes", problems)
				if "hours" in time:
					_int_list(time.get("hours"), 0, 23, "time.hours", problems)
			case "hourofday":
				_int_list(time.get("hours", []), 0, 23, "time.hours", problems)
				_int_list(time.get("minutes", [0]), 0, 59, "time.minutes", problems)
			case "specific":
				hour, minute = time.get("hour", 0), time.get("minute", 0)
				if not _is_int(hour) or not 0 <= hour <= 23:
					problems.append("time.hour must be a whole number from 0 to 23")
				if not _is_int(minute) or not 0 <= minute <= 59:
					problems.append("time.minute must be a whole number from 0 to 59")
			case _:
				problems.append("time.type must be hourly, hourofday or specific")
	return problems

def normalize(value: datetime) -> datetime:
	"""
	Make a wall-clock time a valid instant in its zone. A time that does not exist (inside a spring-forward gap)
	is moved forward by the length of the gap, and gets the offset that is really in force then.
	Naive datetimes (no zone) and times that exist are returned unchanged.
	"""
	if value.tzinfo is None:
		return value
	return value.astimezone(timezone.utc).astimezone(value.tzinfo)

def instant(value: datetime) -> float:
	"""The absolute time as POSIX seconds. Compare and sort with this: aware datetimes in one zone compare by wall clock, which is wrong across a DST change."""
	return value.timestamp()

def day_start(value: datetime) -> datetime:
	"""Midnight of the local day of `value` (the first valid instant of that day)."""
	return normalize(value.replace(hour=0, minute=0, second=0, microsecond=0, fold=0))

def next_day_start(value: datetime) -> datetime:
	"""Midnight that begins the local day after `value`'s, by wall-clock arithmetic (so 23 and 25 hour days are handled)."""
	return normalize(value.replace(hour=0, minute=0, second=0, microsecond=0, fold=0) + timedelta(days=1))

def _wall(now: datetime, hour: int, minute: int) -> datetime:
	return normalize(now.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0))

def generate_trigger_time(now: datetime, time: TimeTriggers, include_now: bool = False) -> Generator[datetime, None, None]:
	"""
	Yield the datetimes that match the given time trigger configuration based on the target time.
	The times are built from the wall clock of `now`'s day and are never earlier than `now` (an instant comparison).
	Times that do not exist on a DST day are normalised (02:30 in a spring-forward gap becomes 03:30), each instant is yielded once,
	and the result is in time order. A repeated hour on a fall-back day fires on its first pass only.

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
	candidates: list[datetime] = []
	match time_type:
		case "hourly":
			minutes = time.get("minutes", [0])
			for hour in range(0, 24):
				for minute in minutes:
					candidates.append(_wall(now, hour, minute))
		case "hourofday":
			hours = time.get("hours", [])
			minutes = time.get("minutes", [0])
			for hour in hours:
				for minute in minutes:
					candidates.append(_wall(now, hour, minute))
		case "specific":
			candidates.append(_wall(now, time.get("hour", 0), time.get("minute", 0)))
	now_ts = instant(now)
	seen: set[float] = set()
	for candidate in sorted(candidates, key=instant):
		ts = instant(candidate)
		if ts in seen:
			continue
		seen.add(ts)
		if ts < now_ts or (ts == now_ts and not include_now):
			continue
		yield candidate

def weekday_sunday_zero(value: datetime) -> int:
	"""Day of week numbered as the web app stores it: 0 = Sunday ... 6 = Saturday (datetime.weekday() has Monday as 0)."""
	return (value.weekday() + 1) % 7

def generate_schedule(now: datetime, trigger: TriggerDict, include_now: bool = False) -> Generator[datetime, None, None]:
	"""
	Run through the trigger and generate the next trigger time(s) based on the current time.
	Generates for the current day only!
	This generator may yield multiple times if the trigger matches multiple times in the future (e.g. hourly trigger).
	The "day" key in the trigger determines the type of trigger and how to evaluate it against the current time.
	If the day trigger matches the current time, then the "time" key is evaluated to generate the next trigger time(s) for that day.
	Days follow the web app: "dayofweek" is 0=Sunday..6=Saturday, "dayofmonth" is 1..31 or -1 for the last day of the month.

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
			if weekday_sunday_zero(now) in days:
				yield from generate_trigger_time(now, time, include_now=include_now)
		case "dayofmonth":
			days = day.get("days", [])
			last_day = calendar.monthrange(now.year, now.month)[1]
			if now.day in days or (-1 in days and now.day == last_day):
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
	"""Midnight of each of `n_days` local days from the day of `start_date`, counted on the wall clock (a day may be 23 or 25 hours long)."""
	base = start_date.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
	for ix in range(n_days):
		yield normalize(base + timedelta(days=ix))

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
	def validate_trigger(self) -> list[str]:
		"""The problems with this item's trigger; empty when it can be evaluated."""
		return validate_trigger(self.trigger)
	def to_dict(self) -> dict[str,Any]:
		retv = {
			"id": self._id,
			"enabled": self.enabled,
			"title": self.title,
			"trigger": self.trigger.copy() if isinstance(self.trigger, dict) else self.trigger,
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
			"_schema": SCHEMA_TASKS,
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