"""Playlists and timer tasks: the stored schedules, and the rendered view of the timer tasks over a date range."""
import json
import logging
import zoneinfo
from datetime import datetime, timedelta, tzinfo
from typing import Any

from fastapi import APIRouter, Query

from ...model.configuration_manager import HASH_KEY, create_hash
from ...model.schedule import TimerTasks, daily_sequence, day_start, normalize, render_task_schedule_at
from ..deps import CM, TOD
from ..errors import ApiError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedule")

MAX_RENDER_DAYS = 62

def _load_schedules(cm) -> dict:
	try:
		return cm.schedule_manager().load()
	except (ValueError, OSError, json.JSONDecodeError) as e:
		# the details name files and paths: keep them in the log
		logger.error(f"schedule load failed: {e}", exc_info=True)
		raise ApiError(500, "The stored schedules could not be loaded; see the server log.", "schedules")

def _with_rev(info) -> dict:
	dx = info.to_dict()
	dx[HASH_KEY] = create_hash(dx)
	return dx

@router.get('/playlist/list')
def schedule_playlist_list(cm: CM):
	playlists = [_with_rev(x["info"]) for x in _load_schedules(cm).get("playlists", []) if x.get("info") is not None]
	return { "success": True, "playlists": playlists }

@router.get('/timer/list')
def schedule_timed_list(cm: CM):
	tasks = [_with_rev(x["info"]) for x in _load_schedules(cm).get("tasks", []) if x.get("info") is not None]
	return { "success": True, "timed": tasks }

def _system_timezone(cm, default: tzinfo|None) -> tzinfo|None:
	_, system = cm.settings_manager().open("system").get()
	name = system.get("timezoneName") if system else None
	if not name:
		return default
	try:
		return zoneinfo.ZoneInfo(name)
	except (zoneinfo.ZoneInfoNotFoundError, ValueError):
		raise ApiError(500, f"The system timezone '{name}' is not valid.", "system-settings")

# the render range is limited to years every platform's datetime and zone database handle
MIN_RENDER_YEAR = 1970
MAX_RENDER_YEAR = 2100

def _render_start(start: datetime|None, now: datetime, tz: tzinfo|None, days: int) -> datetime:
	"""Midnight of the first day to render, in the system zone. A `start` with an offset is converted to that zone first."""
	try:
		if start is not None and not MIN_RENDER_YEAR <= start.year <= MAX_RENDER_YEAR:
			raise OverflowError("year")
		if start is None:
			start_ts = now.astimezone(tz)
		elif start.tzinfo is None:
			start_ts = start.replace(tzinfo=tz)
		else:
			start_ts = start.astimezone(tz)
		start_ts = day_start(start_ts)
		end_ts = start_ts + timedelta(days=days)
		if not (MIN_RENDER_YEAR <= start_ts.year and end_ts.year <= MAX_RENDER_YEAR):
			raise OverflowError("year")
		return start_ts
	except (OverflowError, ValueError, OSError):
		raise ApiError(422, f"start must be between the years {MIN_RENDER_YEAR} and {MAX_RENDER_YEAR}.", "start")

@router.get('/tasks/render')
def render_tasks_schedule(
	cm: CM,
	tod: TOD,
	start: datetime|None = Query(None, description="ISO date/time the range starts at; its day (in the system time zone) is used"),
	days: int = Query(7, ge=1, le=MAX_RENDER_DAYS),
):
	"""
	The timer task triggers for each of `days` days, starting on the day of `start` (today by default).
	Disabled items are not rendered (the timer layer does not run them); items whose trigger is malformed are skipped and listed in `invalid`.
	"""
	now = tod.current_time()
	tz = _system_timezone(cm, now.tzinfo)
	start_ts = _render_start(start, now, tz, days)
	end_ts = normalize(start_ts.replace(hour=0, minute=0, second=0, microsecond=0, fold=0) + timedelta(days=days))
	schedule_map: dict[str, Any] = {}
	render_list: list = []
	notrender_list: list = []
	invalid_list: list = []
	for schedule in _load_schedules(cm).get("tasks", []):
		timer_tasks = schedule.get("info", None)
		if not isinstance(timer_tasks, TimerTasks):
			continue
		did = False
		for tti in timer_tasks.items:
			if not tti.enabled:
				continue
			problems = tti.validate_trigger()
			if problems:
				logger.warning(f"Not rendering timer task '{tti.title}' ({tti.id}) of schedule '{timer_tasks.id}': {'; '.join(problems)}")
				invalid_list.append({ "schedule": timer_tasks.id, "id": tti.id, "title": tti.title, "message": "; ".join(problems) })
				continue
			idid = False
			for schedule_ts in daily_sequence(start_ts, days):
				tdid = render_task_schedule_at(schedule_ts, tti, timer_tasks.id, render_list)
				did = did or tdid
				idid = idid or tdid
			if not idid:
				notrender_list.append({ "schedule": timer_tasks.id, "id": tti.id })
		if did:
			schedule_map.setdefault(timer_tasks.id, _with_rev(timer_tasks))
	return {
		"success": True,
		"start_ts": start_ts.isoformat(),
		"end_ts": end_ts.isoformat(),
		"days": days,
		"schedules": schedule_map,
		"render": render_list,
		"not_render": notrender_list,
		"invalid": invalid_list
	}
