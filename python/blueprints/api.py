from datetime import datetime, timedelta
from functools import lru_cache
from flask import Blueprint, Response, jsonify, render_template, current_app, send_from_directory, send_file, request
import zoneinfo
import logging
from typing import Generator, cast

from ..model.service_container import IServiceProvider
from ..model.schedule import TimerTaskItem, TimerTasks, daily_sequence, generate_schedule, render_task_schedule_at
from ..model.configuration_manager import ConfigurationManager, ConfigurationObject, HASH_KEY, ID_KEY, create_hash

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
plugin_bp = Blueprint('plugin', __name__, url_prefix='/plugin')
datasource_bp = Blueprint('datasource', __name__, url_prefix='/datasource')
api_bp.register_blueprint(plugin_bp)
api_bp.register_blueprint(datasource_bp)

def get_cm() -> ConfigurationManager|None:
	isp: IServiceProvider|None = current_app.config.get('ROOT_CONTAINER', None)
	if isp is not None:
		cm = isp.get_service(ConfigurationManager)
		return cm
	return None

def send_cob_with_rev(id: str, cob: ConfigurationObject) -> Response | tuple[Response, int]:
	hash, document = cob.get()
	if document is None:
		error = { "id": id, "success": False, "message": f"{id}: not found", "rev": None }
		return jsonify(error), 404
	document[HASH_KEY] = hash
	document[ID_KEY] = id
	return jsonify(document)

@api_bp.route('/settings/system', methods=['GET'])
def settings_system():
	logger.info("GET /settings/system")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "system-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("system")
		return send_cob_with_rev("system-settings", settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/system: {str(e)}")
		error = { "message": "File not found.", "id": "system-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/settings/system: {str(e)}")
		error = { "message": str(e), "id": "system-settings", "success": False }
		return jsonify(error), 500

def save_cob_with_rev(id:str, document:dict, cob: ConfigurationObject) -> Response | tuple[Response, int]:
	xid = document.get(ID_KEY, None)
	rev = cast(str, document.get(HASH_KEY, None))
	if xid is None or xid != id:
		error = { "id": id, "success": False, "message": "ID mismatch", "rev": rev }
		return jsonify(error), 400
#	if rev is None:
#		error = { "id": id, "success": False, "message": f"Missing {HASH_KEY}", "rev": None }
#		return jsonify(error), 400
	document.pop(HASH_KEY, None)
	document.pop(ID_KEY, None)
	committed, new_hash = cob.save(rev, document)
	if not committed:
		error = { "id": id, "success": False, "message": "Revision mismatch", "rev": rev }
		return jsonify(error), 409
	success = { "id": id, "success": True, "message": "Success", "rev": new_hash }
	return jsonify(success)

@api_bp.route('/settings/system', methods=['PUT'])
def update_settings_system():
	logger.info("PUT /settings/system")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "system-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("system")
		return save_cob_with_rev("system-settings", request.get_json(), settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/system: {str(e)}")
		error = { "message": "File not found.", "id": "system-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/settings/system: {str(e)}")
		error = { "message": str(e), "id": "system-settings", "success": False }
		return jsonify(error), 500

@api_bp.route('/settings/display', methods=['GET'])
def settings_display():
	logger.info("GET /settings/display")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "display-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("display")
		return send_cob_with_rev("display-settings", settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/display: {str(e)}")
		error = { "message": "File not found.", "id": "display-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/settings/display: {str(e)}")
		error = { "message": str(e), "id": "display-settings", "success": False }
		return jsonify(error), 500

@api_bp.route('/settings/display', methods=['PUT'])
def update_settings_display():
	logger.info("PUT /settings/display")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "display-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("display")
		return save_cob_with_rev("display-settings", request.get_json(), settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/display: {str(e)}")
		error = { "message": "File not found.", "id": "display-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/settings/display: {str(e)}")
		error = { "message": str(e), "id": "display-settings", "success": False }
		return jsonify(error), 500

@api_bp.route('/settings/theme', methods=['GET'])
def settings_theme():
	logger.info("GET /settings/theme")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "theme-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("theme")
		return send_cob_with_rev("theme-settings", settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/theme: {str(e)}")
		error = { "message": "File not found.", "id": "theme-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		# Log full exception details, including stack trace, but do not expose them to the client.
		logger.exception("/settings/theme: Unexpected error while retrieving theme settings")
		error = { "message": "An internal error has occurred.", "id": "theme-settings", "success": False }
		return jsonify(error), 500

@api_bp.route('/settings/theme', methods=['PUT'])
def update_settings_theme():
	logger.info("PUT /settings/theme")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "theme-settings", "success": False }
		return jsonify(error), 500
	try:
		settings_cob = cm.settings_manager().open("theme")
		return save_cob_with_rev("theme-settings", request.get_json(), settings_cob)
	except FileNotFoundError as e:
		logger.error(f"/settings/theme: {str(e)}")
		error = { "message": "File not found.", "id": "theme-settings", "success": False }
		return jsonify(error), 404
	except Exception as e:
		# Log full exception details, including stack trace, but do not expose them to the client.
		logger.exception(f"/settings/theme: Unexpected error while updating theme settings")
		error = { "message": "An internal error has occurred.", "id": "theme-settings", "success": False }
		return jsonify(error), 500

@api_bp.route('/schemas/system', methods=['GET'])
def schemas_system():
	logger.info("GET /schemas/system")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "system-schema", "success": False }
		return jsonify(error), 500
	path = cm.schema_path("system")
	try:
		return send_file(path, mimetype="application/json")
	except FileNotFoundError as e:
		logger.error(f"/schemas/system: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "system-schema", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/schemas/system: {path}: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": "system-schema", "success": False }
		return jsonify(error), 500

@api_bp.route('/schemas/display', methods=['GET'])
def schemas_display():
	logger.info("GET /schemas/display")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "display-schema", "success": False }
		return jsonify(error), 500
	path = cm.schema_path("display")
	try:
		return send_file(path, mimetype="application/json")
	except FileNotFoundError as e:
		logger.error(f"/schemas/display: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "display-schema", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/schemas/display: {path}: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": "display-schema", "success": False }
		return jsonify(error), 500

@api_bp.route('/schemas/theme', methods=['GET'])
def schemas_theme():
	logger.info("GET /schemas/theme")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "theme-schema", "success": False }
		return jsonify(error), 500
	path = cm.schema_path("theme")
	try:
		return send_file(path, mimetype="application/json")
	except FileNotFoundError as e:
		logger.error(f"/schemas/theme: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "theme-schema", "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/schemas/theme: {path}: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": "theme-schema", "success": False }
		return jsonify(error), 500

@api_bp.route('/schemas/plugin/<plugin>', methods=['GET'])
def plugin_schema(plugin:str):
	logger.info(f"GET /schemas/plugin/{plugin}")
	return "Ho-lee cow!"

@api_bp.route('/plugins/list', methods=['GET'])
def plugins_list():
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "plugins-list", "success": False }
		return jsonify(error), 500
	plugins = cm.enum_plugins()
	plist = list(map(lambda x: x.get("info"), plugins))
	return jsonify(plist)

@api_bp.route('/plugins/<plugin>/settings', methods=['GET'])
def plugin_settings(plugin:str):
	logger.info(f"GET /plugins/{plugin}/settings")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": f"plugin-{plugin}-settings", "success": False }
		return jsonify(error), 500
	try:
		plugin_cob = cm.plugin_manager(plugin).open()
		return send_cob_with_rev(f"plugin-{plugin}-settings", plugin_cob)
	except FileNotFoundError as e:
		logger.error(f"/plugins/{plugin}/settings: {str(e)}")
		error = { "message": "File not found.", "id": plugin, "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/plugins/{plugin}/settings: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": plugin, "success": False }
		return jsonify(error), 500

@api_bp.route('/plugins/<plugin>/settings', methods=['PUT'])
def save_plugin_settings(plugin:str):
	logger.info(f"PUT /plugins/{plugin}/settings")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": f"plugin-{plugin}-settings", "success": False }
		return jsonify(error), 500
	try:
		plugin_cob = cm.plugin_manager(plugin).open()
		return save_cob_with_rev(f"plugin-{plugin}-settings", request.get_json(), plugin_cob)
	except FileNotFoundError as e:
		logger.error(f"/plugins/{plugin}/settings: {str(e)}")
		error = { "message": "File not found.", "id": plugin, "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/plugins/{plugin}/settings: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": plugin, "success": False }
		return jsonify(error), 500

@api_bp.route('/datasources/list', methods=['GET'])
def datasources_list():
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "datasources-list", "success": False }
		return jsonify(error), 500
	dss = cm.enum_datasources()
	plist = list(map(lambda x: x.get("info"), dss))
	return jsonify(plist)

@api_bp.route('/datasources/<plugin>/settings', methods=['GET'])
def datasource_settings(plugin:str):
	logger.info(f"GET /datasources/{plugin}/settings")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": f"datasource-{plugin}-settings", "success": False }
		return jsonify(error), 500
	try:
		plugin_cob = cm.datasource_manager(plugin).open()
		return send_cob_with_rev(f"datasource-{plugin}-settings", plugin_cob)
	except FileNotFoundError as e:
		logger.error(f"/datasources/{plugin}/settings: {str(e)}")
		error = { "message": "File not found.", "id": plugin, "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.error(f"/datasources/{plugin}/settings: {str(e)}")
		error = { "message": "An internal error has occurred.", "id": plugin, "success": False }
		return jsonify(error), 500

@lru_cache(maxsize=1)
def get_timezone_options():
	# 1. Define the major regions we want to show
	major_regions = {
			"Africa", "America", "Antarctica", "Asia", "Atlantic", 
			"Australia", "Europe", "Indian", "Pacific"
	}
	options = []
	now = datetime.now()
	# 2. Get all zones and sort them alphabetically
	for tz_name in sorted(zoneinfo.available_timezones()):
		# Split into Region/City (e.g., "America/New_York")
		parts = tz_name.split('/')
		# 3. Filter: Must be in "Region/City" format and in our major_regions list
		if len(parts) >= 2 and parts[0] in major_regions:
			tz_obj = zoneinfo.ZoneInfo(tz_name)
			# Get the UTC offset string (e.g., "-0500" -> "UTC-05:00")
			offset = now.astimezone(tz_obj).strftime('%z')
			display_offset = f"UTC{offset[:3]}:{offset[3:]}"
			# Clean up the name for the label (e.g., "America/New_York" -> "New York")
			# We join the parts after the region to handle "America/Argentina/Buenos_Aires"
			city_name = " / ".join(parts[1:]).replace('_', ' ')
			options.append({
				"name": f"{parts[0]}: {city_name} ({display_offset})",
				"value": tz_name
			})
	return options

@api_bp.route('/datasources/<plugin>/settings', methods=['PUT'])
def save_datasource_settings(plugin:str):
	logger.info(f"PUT /datasources/{plugin}/settings")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": f"datasource-{plugin}-settings", "success": False }
		return jsonify(error), 500
	try:
		plugin_cob = cm.datasource_manager(plugin).open()
		return save_cob_with_rev(f"datasource-{plugin}-settings", request.get_json(), plugin_cob)
	except FileNotFoundError as e:
		logger.error(f"/datasources/{plugin}/settings: {str(e)}")
		error = { "message": "File not found.", "id": plugin, "success": False }
		return jsonify(error), 404
	except Exception as e:
		logger.exception(f"/datasources/{plugin}/settings: Unexpected error")
		error = { "message": "Internal server error.", "id": plugin, "success": False }
		return jsonify(error), 500

@api_bp.route('/lookups/timezone', methods=['GET'])
def list_timezones():
	"""Returns a list of all time zones using the zoneinfo library."""
	logger.info("GET /lookups/timezone")
#	timezones = sorted(zoneinfo.available_timezones())
#	lookup = list(map(lambda x: { "name": x, "value": x }, timezones))
	return jsonify(get_timezone_options())

@api_bp.route('/lookups/locale', methods=['GET'])
def get_locales():
	"""
	Returns a list of supported locales.
	"""
	logger.info("GET /lookups/locale")
	locales = [
		{"value": "en-US", "name": "English"},
		{"value": "es-ES", "name": "Español"},
		{"value": "fr-FR", "name": "Français"},
		{"value": "de-DE", "name": "Deutsch"}
	]
	return jsonify(locales)

@api_bp.route('/schedule/playlist/list', methods=['GET'])
def schedule_playlist_list():
	logger.info("GET /schedule/playlist/list")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "schedule-playlist-list", "success": False }
		return jsonify(error), 500
	try:
		sm = cm.schedule_manager()
		schedule_info = sm.load()
		sm.validate(schedule_info)
		playlists = schedule_info.get("playlists", [])
		if not playlists:
			return jsonify({"success": False, "error": "Playlists not found"}), 404
		playlist_resp = []
		for schedule in playlists:
			info = schedule.get("info", None)
			if info is not None:
				dx = info.to_dict()
				hash = create_hash(dx)
				dx[HASH_KEY] = hash
				playlist_resp.append(dx)
		return jsonify({ "success": True, "playlists": playlist_resp })
	except Exception:
		logger.exception("/schedule/playlist/list: unhandled exception while loading playlist schedule")
		error = { "message": "An internal error occurred while loading the playlist schedule.", "id": "schedule-playlist-list", "success": False }
		return jsonify(error), 500

@api_bp.route('/schedule/timer/list', methods=['GET'])
def schedule_timed_list():
	logger.info("GET /schedule/timer/list")
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "schedule-timer-list", "success": False }
		return jsonify(error), 500
	try:
		sm = cm.schedule_manager()
		schedule_info = sm.load()
		sm.validate(schedule_info)
		tasks = schedule_info.get("tasks", [])
		if not tasks:
			return jsonify({"success": False, "error": "Timer Tasks not found"}), 404
		task_resp = []
		for schedule in tasks:
			info = schedule.get("info", None)
			if info is not None:
				dx = info.to_dict()
				hash = create_hash(dx)
				dx[HASH_KEY] = hash
				task_resp.append(dx)
		return jsonify({ "success": True, "timed": task_resp })
	except Exception:
		logger.exception("/schedule/timer/list: unhandled exception while loading timer schedule")
		error = { "message": "An internal error occurred while loading the timer schedule.", "id": "schedule-timer-list", "success": False }
		return jsonify(error), 500

@api_bp.route('/schedule/tasks/render', methods=['GET'])
def render_tasks_schedule():
	"""
	Returns a list of all timer tasks that are currently active.
	"""
	logger.info("GET /schedule/tasks/render")
	start_at = request.args.get("start", None)
	days = request.args.get("days", 7, type=int)
	cm = get_cm()
	if cm is None:
		error = { "message": "Configuration Manager not available.", "id": "schedule-tasks-render" }
		return jsonify(error), 500
	scm = cm.settings_manager()
	system_cob = scm.open("system")
	_, system = system_cob.get()
	if system is None:
		return jsonify({"success": False, "error": "System Settings not found"}), 404
	tz = zoneinfo.ZoneInfo(system.get("timezoneName", "US/Eastern"))
	sm = cm.schedule_manager()
	schedule_info = sm.load()
	sm.validate(schedule_info)
	schedule_info_tasks = schedule_info.get("tasks", [])
	if not schedule_info_tasks:
		return jsonify({"success": False, "error": "Timer Tasks not found"}), 404
	try:
		# TODO get timebase from container
		start_ts = datetime.now(tz) if start_at is None else datetime.fromisoformat(start_at)
		start_ts = start_ts.replace(hour=0, minute=0, second=0, microsecond=0)
		end_ts = start_ts + timedelta(days=days)
		schedule_map = {}
		render_list = []
		notrender_list = []
		for schedule in schedule_info_tasks:
			timer_tasks = schedule.get("info", None)
			if timer_tasks is not None and isinstance(timer_tasks, TimerTasks):
				did = False
				for tti in timer_tasks.items:
#					schedule_ts = start_ts
					idid = False
					for schedule_ts in daily_sequence(start_ts, days):
#					while schedule_ts < end_ts:
						tdid = render_task_schedule_at(schedule_ts, tti, timer_tasks.id, render_list)
						did = did or tdid
						idid = idid or tdid
#						schedule_ts = schedule_ts + timedelta(days=1)
					if not idid:
						notrender_list.append({
							"schedule": timer_tasks.id,
							"id": tti.id,
						})
				if did:
					dx = timer_tasks.to_dict()
					hash = create_hash(dx)
					dx[HASH_KEY] = hash
					schedule_map.setdefault(timer_tasks.id, dx)
		retv = {
			"success": True,
			"start_ts": start_ts.isoformat(),
			"end_ts": end_ts.isoformat(),
			"days": days,
			"schedules": schedule_map,
			"render": render_list,
			"not_render": notrender_list
		}
		return jsonify(retv)
	except Exception as e:
		logger.exception("/schedule/tasks/render failed")
		error = {
			"message": "An internal error has occurred while rendering the schedule.",
			"id": "schedule-tasks-render",
			"success": False
		}
		return jsonify(error), 500