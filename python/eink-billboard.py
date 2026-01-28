#!/usr/bin/env python3

# run from root folder
# python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ../.storage

import os, logging.config

from python.model.configuration_watcher import ConfigurationWatcher
from python.model.hash_manager_eviction_sink import HashManagerEvictionSink
from python.model.service_container import ServiceContainer
from python.model.time_of_day import SystemTimeOfDay, TimeOfDay

from .model.configuration_manager import ConfigurationManager

from .blueprints.root import root_bp
from .blueprints.api import api_bp
from .task.telemetry_sink import TelemetrySink
from .task.application import Application, StartEvent
from .task.messages import QuitMessage, StartOptions
from .model.hash_manager import HashManager, HASH_KEY

logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
import warnings
warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

import random
import logging
import argparse
#from utils.app_utils import generate_startup_image
from flask import Flask, request
from werkzeug.serving import is_running_from_reloader
# from config import Config
#from jinja2 import ChoiceLoader, FileSystemLoader
from waitress import serve

logger = logging.getLogger(__name__)

# Parse command line arguments
APPNAME = "EInk Billboard"
parser = argparse.ArgumentParser(description=f"{APPNAME} Server")
parser.add_argument('--dev', action='store_true', help='Run in development mode')
parser.add_argument('--host', help='Change listening interface')
parser.add_argument('--app', help='Path to web app bundle')
parser.add_argument('--storage', help='Path to storage folder; relative to location of the PY file!')
parser.add_argument('--cors', help='Activate CORS and set the allowed host URL')
args = parser.parse_args()

# development mode
if args.dev:
#    Config.config_file = os.path.join(Config.BASE_DIR, "config", "device_dev.json")
	DEV_MODE = True
	PORT = 8080
	logger.info(f"Starting {APPNAME} in DEVELOPMENT mode on port 8080")
else:
	DEV_MODE = False
	PORT = 80
	logger.info(f"Starting {APPNAME} in PRODUCTION mode on port 80")

# listening interface
HOST = "0.0.0.0"
if args.host:
	HOST = args.host
	logger.info(f"HOST {HOST}")

# app bundle path
PATH = "../app/dist"
if args.app:
	PATH = args.app
	logger.info(f"PATH {PATH}")

# storage root path
STORAGE = None
if args.storage:
	STORAGE = os.path.abspath(args.storage)
	logger.info(f"STORAGE {STORAGE}")

logging.getLogger('waitress.queue').setLevel(logging.ERROR)
app = Flask(__name__, static_folder=f"{PATH}/static", template_folder=f"{PATH}", static_url_path="/static")
if args.cors:
	from flask_cors import CORS
	CORSDM = args.cors
	logger.info(f"CORS {CORSDM}")
	cors_options = {r"/api/*": {"origins": CORSDM}}
	if CORSDM is None:
		CORS(app)
	else:
		CORS(app, resources=cors_options)
#template_dirs = [
#   os.path.join(os.path.dirname(__file__), "templates"),    # Default template folder
#   os.path.join(os.path.dirname(__file__), "plugins"),      # Plugin templates
#]
# app.jinja_loader = ChoiceLoader([FileSystemLoader(directory) for directory in template_dirs])

# Set additional parameters
app.secret_key = str(random.randint(100000,999999))
app.config['MAX_FORM_PARTS'] = 10_000

if __name__ == '__main__':
	# display default inkypi image on startup
#	if device_config.get_config("startup") is True:
#		logger.info("Startup flag is set, displaying startup image")
#		img = generate_startup_image(device_config.get_resolution())
#		display_manager.display_image(img)
#		device_config.update_value("startup", False, write=True)

	try:
		cm = ConfigurationManager(storage_path=STORAGE)
		# TODO get system settings timezone and use it in SystemTimeOfDay
		time_base = SystemTimeOfDay()
		hash_manager = HashManager(cm.STORAGE_PATH)
		watcher_sink = HashManagerEvictionSink(hash_manager)
		config_watcher = ConfigurationWatcher(time_base, watcher_sink, cm.ROOT_PATH)
		# register plugin blueprints
		blueprint_map = cm.load_blueprints(cm.enum_plugins())
		for bp_name, bp in blueprint_map.items():
			app.register_blueprint(bp)
			logger.info(f"Registered blueprint: {bp_name}")
		# Register Blueprints
		app.register_blueprint(root_bp)
		app.register_blueprint(api_bp)
		# start the application layer
		sink = TelemetrySink()
		xapp = Application(APPNAME, sink)
		xapp.start()
		force_reset = not os.path.exists(STORAGE)
		if force_reset:
			logger.info("No storage folder detected, force_reset")
		options = StartOptions(storagePath=STORAGE,hardReset=force_reset)
		root = ServiceContainer()
		root.add_service(TimeOfDay, time_base)
		root.add_service(HashManager, hash_manager)
		root.add_service(TelemetrySink, sink)
		root.add_service(Application, xapp)
		xapp.accept(StartEvent(options, root, time_base.current_time()))
		started = xapp.app_started.wait(timeout=5)
		if not started:
			logger.warning(f"Application start timed out")
		else:
			logger.info("Application is started")
		app.config['HASH_MANAGER'] = hash_manager
		app.config['APPLICATION'] = xapp
		app.config['TELEMETRY'] = sink
		app.config['ROOT_PATH'] = cm.ROOT_PATH
		app.config['STORAGE_PATH'] = cm.STORAGE_PATH

		msg = sink.receive()
		while msg is not None:
			logger.warning(f"startup message {msg}")
			msg = sink.receive()

		config_watcher.start()

		# Get local IP address for display (only in dev mode when running on non-Pi)
		if DEV_MODE and HOST == '0.0.0.0':
			import socket
			try:
				s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				s.connect(("8.8.8.8", 80))
				local_ip = s.getsockname()[0]
				s.close()
				logger.info(f"Serving on http://{local_ip}:{PORT}")
			except:
				pass  # Ignore if we can't get the IP

		serve(app, host=HOST, port=PORT, threads=1)
	except Exception as e:
		logger.error(f"Exception in main: {e}", exc_info=True)
	finally:
		logger.info("eInk Billboard application shut down start")
		try:
			xapp.accept(QuitMessage(time_base.current_time()))
			xapp.join(timeout=5)
			if config_watcher is not None:
				config_watcher.stop()
		except Exception as ee:
			logger.error(f"Exception during shutdown: {ee}", exc_info=True)
		finally:
			logger.info("eInk Billboard application shut down complete")