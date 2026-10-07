"""Playlists and timer tasks: the stored schedules, and the rendered view of the timer tasks over a date range."""
import json
import logging
import zoneinfo
from datetime import datetime, timedelta, tzinfo
from typing import Any

from fastapi import APIRouter, Body, Query

from ...model.configuration_manager import HASH_KEY, create_hash
from ...model.schedule import Playlist, TimerTasks, daily_sequence, day_start, normalize, render_task_schedule_at
from ...model.schedule_store import PLAYLISTS, TASKS, Ambiguous, Conflict, Invalid, Kind, NotFound, ScheduleStore, ScheduleStoreError
from ..deps import CM, TOD
from ..documents import validate_properties
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
	if isinstance(info, (TimerTasks, Playlist)):
		# each task or track carries its own revision, which is what a change to just that task must echo
		dx["items"] = [{ **x, HASH_KEY: create_hash(x) } for x in dx["items"]]
	return dx

@router.get('/playlist/list')
def schedule_playlist_list(cm: CM):
	playlists = [_with_rev(x["info"]) for x in _load_schedules(cm).get("playlists", []) if x.get("info") is not None]
	return { "success": True, "playlists": playlists }

@router.get('/timer/list')
def schedule_timed_list(cm: CM):
	tasks = [_with_rev(x["info"]) for x in _load_schedules(cm).get("tasks", []) if x.get("info") is not None]
	return { "success": True, "timed": tasks }

def _zone_name(tz: tzinfo|None, at: datetime) -> str|None:
	"""What a browser can use as a time zone name: the IANA key, else the fixed offset (`+05:30`) in force at `at`."""
	key = getattr(tz, "key", None)
	if isinstance(key, str):
		return key
	offset = at.strftime("%z")
	return f"{offset[:3]}:{offset[3:5]}" if len(offset) >= 5 else None

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
		"timezone": _zone_name(tz, start_ts),
		"schedules": schedule_map,
		"render": render_list,
		"not_render": notrender_list,
		"invalid": invalid_list
	}


# --- incremental changes to the timer tasks: whole documents and single tasks (see model/schedule_store.py)

def _instance_properties(item: dict) -> tuple[list[dict], dict]:
	"""The `instanceSettings` properties and lookups a plugin or datasource declares for a task's `content`."""
	schema = ((item["info"].get("instanceSettings") or {}).get("schema")) or {}
	return schema.get("properties") or [], schema.get("lookups") or {}

def _plugin_content_errors(plugins: dict, datasources: dict, plugin_name: Any, content: dict, path: list) -> list[dict]:
	"""The plugin exists and `content` follows its settings (and its data source's); `path` is where `plugin_name` and `content` live in the item (`["task"]` for a timer task, none for a track)."""
	plugin = plugins.get(plugin_name)
	if plugin is None:
		return [{ "path": [*path, "plugin_name"], "message": "Unknown plugin" }]
	props, lookups = _instance_properties(plugin)
	errors = validate_properties(content, props, lookups)
	for prop in props:
		chosen = content.get(prop.get("name")) if prop.get("type") == "schema" else None
		if isinstance(chosen, str) and chosen:
			source = datasources.get(chosen)
			if source is None:
				errors.append({ "path": [prop["name"]], "message": "Not one of the allowed values" })
			else:
				sprops, slookups = _instance_properties(source)
				errors.extend(validate_properties(content, sprops, slookups))
	return [{ "path": [*path, "content", *e["path"]], "message": e["message"] } for e in errors]

def _item_validator(cm, kind: Kind = TASKS):
	"""What the store cannot know: the plugin exists and its `content` is valid. A timer task keeps them under `task`, a playlist track at the top."""
	plugins = {p["info"].get("id"): p for p in cm.enum_plugins()}
	datasources = {d["info"].get("id"): d for d in cm.enum_datasources()}
	if kind is TASKS:
		def validate_task(item: dict) -> list[dict]:
			task = item.get("task") or {}
			return _plugin_content_errors(plugins, datasources, task.get("plugin_name"), task.get("content") or {}, ["task"])
		return validate_task
	def validate_track(item: dict) -> list[dict]:
		return _plugin_content_errors(plugins, datasources, item.get("plugin_name"), item.get("content") or {}, [])
	return validate_track

def _store(cm, kind: Kind = TASKS) -> ScheduleStore:
	return ScheduleStore(cm.schedule_manager(), _item_validator(cm, kind), kind)

def _call(doc_id: str|None, fn):
	"""Run a store operation and report its errors in the API's uniform shape. The ids are ours, never the request's text."""
	try:
		return fn()
	except NotFound as e:
		raise ApiError(404, "Unknown schedule." if e.what == "schedule" else "Unknown task.", None)
	except Ambiguous:
		raise ApiError(409, "More than one stored schedule has this id; fix the files first.", None)
	except Conflict as e:
		raise ApiError(409, "Revision mismatch: it changed since it was loaded.", doc_id, rev=e.rev)
	except Invalid as e:
		raise ApiError(422, "Schedule validation failed", doc_id, errors=e.errors)
	except ScheduleStoreError as e:
		raise ApiError(400, "The change could not be made.", doc_id)
	except (OSError, ValueError, json.JSONDecodeError) as e:
		logger.error(f"schedule change failed: {e}", exc_info=True)
		raise ApiError(500, "The schedule could not be changed; see the server log.", doc_id)

def _rev_of(body: Any) -> Any:
	return body.get(HASH_KEY) if isinstance(body, dict) else None

@router.post('/timer', status_code=201)
def timer_create(cm: CM, body: dict[str, Any] = Body(...)):
	doc = _call(None, lambda: _store(cm).create_document(body))
	return { "success": True, "message": "Success", "id": doc["id"], "rev": doc[HASH_KEY], "schedule": doc }

@router.get('/timer/{doc_id}')
def timer_get(doc_id: str, cm: CM):
	return { "success": True, "schedule": _call(None, lambda: _store(cm).get_document(doc_id)) }

@router.put('/timer/{doc_id}')
def timer_put(doc_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	doc = _call(doc_id, lambda: _store(cm).replace_document(doc_id, body, _rev_of(body)))
	return { "success": True, "message": "Success", "id": doc["id"], "rev": doc[HASH_KEY], "schedule": doc }

@router.patch('/timer/{doc_id}')
def timer_rename(doc_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	doc = _call(doc_id, lambda: _store(cm).rename_document(doc_id, body, _rev_of(body)))
	return { "success": True, "message": "Success", "id": doc["id"], "rev": doc[HASH_KEY], "schedule": doc }

@router.delete('/timer/{doc_id}')
def timer_delete(doc_id: str, cm: CM, rev: str = Query(...)):
	_call(doc_id, lambda: _store(cm).delete_document(doc_id, rev))
	return { "success": True, "message": "Success", "id": None }

@router.get('/timer/{doc_id}/items/{item_id}')
def timer_item_get(doc_id: str, item_id: str, cm: CM):
	return { "success": True, "task": _call(None, lambda: _store(cm).get_item(doc_id, item_id)) }

@router.post('/timer/{doc_id}/items', status_code=201)
def timer_item_add(doc_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	item = _call(doc_id, lambda: _store(cm).add_item(doc_id, body))
	return { "success": True, "message": "Success", "id": item["id"], "rev": item[HASH_KEY], "schedule_rev": item["schedule_rev"], "task": item }

@router.put('/timer/{doc_id}/items/{item_id}')
def timer_item_put(doc_id: str, item_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	item = _call(doc_id, lambda: _store(cm).replace_item(doc_id, item_id, body))
	return { "success": True, "message": "Success", "id": item["id"], "rev": item[HASH_KEY], "schedule_rev": item["schedule_rev"], "task": item }

@router.patch('/timer/{doc_id}/items/{item_id}')
def timer_item_patch(doc_id: str, item_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	item = _call(doc_id, lambda: _store(cm).patch_item(doc_id, item_id, body))
	return { "success": True, "message": "Success", "id": item["id"], "rev": item[HASH_KEY], "schedule_rev": item["schedule_rev"], "task": item }

@router.delete('/timer/{doc_id}/items/{item_id}')
def timer_item_delete(doc_id: str, item_id: str, cm: CM, rev: str = Query(...)):
	doc = _call(doc_id, lambda: _store(cm).delete_item(doc_id, item_id, rev))
	return { "success": True, "message": "Success", "id": item_id, "schedule_rev": doc[HASH_KEY] }


# --- playlists are self-contained documents: saved whole (the tracks and their order), no single-track routes

def _saved(doc: dict) -> dict:
	return { "success": True, "message": "Success", "id": doc["id"], "rev": doc[HASH_KEY], "schedule": doc }

@router.post('/playlist', status_code=201)
def playlist_create(cm: CM, body: dict[str, Any] = Body(...)):
	return _saved(_call(None, lambda: _store(cm, PLAYLISTS).create_document(body)))

@router.get('/playlist/{doc_id}')
def playlist_get(doc_id: str, cm: CM):
	return { "success": True, "schedule": _call(None, lambda: _store(cm, PLAYLISTS).get_document(doc_id)) }

@router.put('/playlist/{doc_id}')
def playlist_put(doc_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	return _saved(_call(doc_id, lambda: _store(cm, PLAYLISTS).replace_document(doc_id, body, _rev_of(body))))

@router.patch('/playlist/{doc_id}')
def playlist_rename(doc_id: str, cm: CM, body: dict[str, Any] = Body(...)):
	return _saved(_call(doc_id, lambda: _store(cm, PLAYLISTS).rename_document(doc_id, body, _rev_of(body))))

@router.delete('/playlist/{doc_id}')
def playlist_delete(doc_id: str, cm: CM, rev: str = Query(...)):
	_call(doc_id, lambda: _store(cm, PLAYLISTS).delete_document(doc_id, rev))
	return { "success": True, "message": "Success", "id": None }
