from datetime import datetime, date, timedelta
import os
import json
from flask import Blueprint, Response, jsonify, render_template, current_app, send_from_directory, send_file, request
import pytz
import logging

from ..model.hash_manager import HashManager, HASH_KEY
from ..model.schedule import TimedSchedule
from ..model.configuration_manager import ConfigurationManager

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
plugin_bp = Blueprint('plugin', __name__, url_prefix='/plugin')
api_bp.register_blueprint(plugin_bp)

def create_cm():
	root = current_app.config['ROOT_PATH']
	storage = current_app.config['STORAGE_PATH']
	return ConfigurationManager(source_path=root, storage_path=storage)

def get_hash_manager() -> HashManager:
	return current_app.config.get('HASH_MANAGER', None)

def send_json_file_with_rev(id: str, path:str, hm:HashManager) -> Response:
	with open(path, 'r') as fx:
		data = json.load(fx)
	return send_json_with_rev(id, data, hm)

def send_json_with_rev(id: str, data:dict, hm:HashManager) -> Response:
	updated, hash = hm.hash_document(id, None, data)
	data[HASH_KEY] = hash
	return jsonify(data)

@api_bp.route('/settings/system', methods=['GET'])
def settings_system():
	logger.info("GET /settings/system")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.settings_manager().settings_path("system")
	try:
		return send_json_file_with_rev("system-settings", path, hm)
	except FileNotFoundError as e:
		logger.error(f"/settings/system: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "system-settings" }
		return jsonify(error), 404

def save_json_file_with_rev(id:str, path:str, document:dict, hm:HashManager) -> Response:
	def save_the_file(doc):
		doc.pop(HASH_KEY, None)
		with open(path, 'w') as fx:
			json.dump(doc, fx, indent=2)

	rev = document.get(HASH_KEY, None)
	if rev is None:
		error = { "id": id, "success": False, "message": "Missing _rev", "rev": None }
		return jsonify(error), 400
	committed, new_hash = hm.commit_document(id, rev, document, save_the_file)
	if not committed:
		error = { "id": id, "success": False, "message": "Revision mismatch", "rev": rev }
		return jsonify(error), 409
	success = { "id": id, "success": True, "message": "Success", "rev": new_hash }
	return jsonify(success)

@api_bp.route('/settings/system', methods=['PUT'])
def update_settings_system():
	logger.info("PUT /settings/system")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.settings_manager().settings_path("system")
	try:
		return save_json_file_with_rev("system-settings", path, request.get_json(), hm)
	except FileNotFoundError as e:
		logger.error(f"/settings/system: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "system-settings" }
		return jsonify(error), 404

@api_bp.route('/settings/display', methods=['GET'])
def settings_display():
	logger.info("GET /settings/display")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.settings_manager().settings_path("display")
	try:
		return send_json_file_with_rev("display-settings", path, hm)
	except FileNotFoundError as e:
		logger.error(f"/schemas/system: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "display-settings" }
		return jsonify(error), 404

@api_bp.route('/settings/display', methods=['PUT'])
def update_settings_display():
	logger.info("PUT /settings/display")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.settings_manager().settings_path("display")
	try:
		return save_json_file_with_rev("display-settings", path, request.get_json(), hm)
	except FileNotFoundError as e:
		logger.error(f"/settings/display: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "display-settings" }
		return jsonify(error), 404

@api_bp.route('/schemas/system', methods=['GET'])
def schemas_system():
	logger.info("GET /schemas/system")
	cm = create_cm()
	path = os.path.join(cm.storage_schemas, "system.json")
	try:
		return send_file(path, mimetype="application/json")
	except FileNotFoundError as e:
		logger.error(f"/schemas/system: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "system-schema" }
		return jsonify(error), 404

@api_bp.route('/schemas/display', methods=['GET'])
def schemas_display():
	logger.info("GET /schemas/display")
	cm = create_cm()
	path = os.path.join(cm.storage_schemas, "display.json")
	try:
		return send_file(path, mimetype="application/json")
	except FileNotFoundError as e:
		logger.error(f"/schemas/display: {path}: {str(e)}")
		error = { "message": "File not found.", "id": "display-schema" }
		return jsonify(error), 404

@api_bp.route('/schemas/plugin/<plugin>', methods=['GET'])
def plugin_schema(plugin:str):
	logger.info(f"GET /schemas/plugin{plugin}")
	return "Ho-lee cow!"

@api_bp.route('/plugins/list', methods=['GET'])
def plugins_list():
	cm = create_cm()
	plugins = cm.enum_plugins()
	plist = list(map(lambda x: x.get("info"), plugins))
	return jsonify(plist)

@api_bp.route('/plugins/<plugin>/settings', methods=['GET'])
def plugin_settings(plugin:str):
	logger.info(f"GET /plugins/{plugin}/settings")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.plugin_manager(plugin).settings_path()
	try:
		return send_json_file_with_rev(f"plugin-{plugin}-settings", path, hm)
	except FileNotFoundError as e:
		logger.error(f"/plugins/{plugin}/settings: {path}: {str(e)}")
		error = { "message": "File not found.", "id": plugin }
		return jsonify(error), 404

@api_bp.route('/plugins/<plugin>/settings', methods=['PUT'])
def save_plugin_settings(plugin:str):
	logger.info(f"PUT /plugins/{plugin}/settings")
	cm = create_cm()
	hm = get_hash_manager()
	path = cm.plugin_manager(plugin).settings_path()
	try:
		return save_json_file_with_rev(f"plugin-{plugin}-settings", path, request.get_json(), hm)
	except FileNotFoundError as e:
		logger.error(f"/plugins/{plugin}/settings: {path}: {str(e)}")
		error = { "message": "File not found.", "id": plugin }
		return jsonify(error), 404

@api_bp.route('/lookups/timezone', methods=['GET'])
def list_timezones():
	"""Returns a list of all time zones using the pytz library."""
	logger.info("GET /lookups/timezone")
	timezones = sorted(pytz.all_timezones)
	lookup = list(map(lambda x: { "name": x, "value": x }, timezones))
	return jsonify(lookup)

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

@api_bp.route('/schedule/render', methods=['GET'])
def render_schedule():
	"""
	QSP   format  default  description
	days  int     7        number of days to render
	start iso8601 today    starting date (time is ignored) SHOULD include TZ
	"""
	logger.info("GET /schedule/render")
	start_at = request.args.get("start", None)
	days = request.args.get("days", 7, type=int)
	cm = create_cm()
	hm = get_hash_manager()
	stm = cm.settings_manager()
	system_cob = stm.load_settings("system")
	(_, system) = system_cob.get()
	tz = pytz.timezone(system.get("timezoneName", "US/Eastern"))
	sm = cm.schedule_manager()
	schedule_info = sm.load(hm)
	sm.validate(schedule_info)
	master_schedule = schedule_info.get("master", None)
	if master_schedule is None:
		return jsonify({"success": False, "error": "Master Schedule not found"}), 404
	schedules = schedule_info.get("schedules", [])
	if schedules is []:
		return jsonify({"success": False, "error": "Schedule List not found"}), 404

	start_ts = datetime.now(tz) if start_at is None else datetime.fromisoformat(start_at)
	start_ts = start_ts.replace(hour=0, minute=0, second=0, microsecond=0)
	end_ts = start_ts + timedelta(days=days)
	schedule_ts = start_ts
	schedule_map = {}
	render_list = []
	while schedule_ts < end_ts:
		for schedule in schedules:
			info = schedule.get("info", None)
			if info is not None and isinstance(info, TimedSchedule):
				info.set_date_controller(lambda: schedule_ts)
		current = master_schedule.evaluate(schedule_ts)
		if current:
			schedule = next((sx for sx in schedules if sx.get("name", None) and sx["name"] == current.schedule), None)
			if schedule and "info" in schedule and isinstance(schedule["info"], TimedSchedule):
				target:TimedSchedule = schedule["info"]
				render = [{ "schedule": target.id, "id":xx.id, "start": xx.start.isoformat(), "end": xx.end.isoformat() } for xx in target.items]
				render_list.extend(render)
				schedule_map.setdefault(target.id, target.to_dict())
		else:
			return jsonify({ "schedule_ts": schedule_ts.isoformat(), "success": False, "error": "Master Schedule evaluate failed"}), 404
		schedule_ts = schedule_ts + timedelta(days=1)
		pass
	retv = {
		"success": True,
		"start_ts": start_ts.isoformat(),
		"end_ts": end_ts.isoformat(),
		"days": days,
		"schedules": schedule_map,
		"render": render_list
	}
	return jsonify(retv)
