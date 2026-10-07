#!/usr/bin/env python3

# run from root folder
# python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ./.storage

import argparse
import logging
import logging.config
import os
import warnings

import yaml

from .model.configuration_watcher import ConfigurationWatcher
from .model.configuration_manager_eviction_sink import ConfigurationManagerEvictionSink
from .model.service_container import ServiceContainer
from .task.fanout_sink import FanoutSink
from .model.time_of_day import ConfiguredTimeOfDay, TimeOfDay
from .model.configuration_manager import ConfigurationManager

from .task.telemetry_sink import TelemetrySink
from .task.application import Application, StartEvent
from .task.messages import QuitMessage, StartOptions
from .web.app import WebSettings, create_app

APPNAME: str = "EInk Billboard"
TOKEN_ENV = "EINK_API_TOKEN"
# the default bundle is found relative to this file (not the working directory), so it works from any folder
DEFAULT_APP_PATH: str = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "dist"))

logger = logging.getLogger(__name__)

def configure_logging() -> None:
	logfile = os.path.join(os.path.dirname(__file__), 'config', 'logging.yaml')
	with open(logfile, 'r') as f:
		logging.config.dictConfig(yaml.safe_load(f.read()))
	# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
	warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

def parse_args(argv: list[str]|None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=f"{APPNAME} Server")
	parser.add_argument('--dev', action='store_true', help='Run in development mode')
	parser.add_argument('--host', default="0.0.0.0", help='Change listening interface')
	parser.add_argument('--port', type=int, help='Listening port; default 8080 in development mode, 80 otherwise')
	parser.add_argument('--app', default=DEFAULT_APP_PATH, help='Path to web app bundle; a relative path is relative to the current working directory (default: app/dist of this repository)')
	parser.add_argument('--storage', help='Path to storage folder; a relative path is relative to the current working directory')
	parser.add_argument('--cors', help='Activate CORS and set the allowed host URL')
	parser.add_argument('--token', help=f'Require this Bearer token on /api requests (default: the {TOKEN_ENV} environment variable)')
	args = parser.parse_args(argv)
	args.app = os.path.abspath(args.app)
	return args

def run_application(args: argparse.Namespace) -> None:
	import uvicorn

	dev_mode: bool = args.dev
	port: int = args.port if args.port else (8080 if dev_mode else 80)
	logger.info(f"Starting {APPNAME} in {'DEVELOPMENT' if dev_mode else 'PRODUCTION'} mode on port {port}")
	storage: str|None = os.path.abspath(args.storage) if args.storage else None
	if storage:
		logger.info(f"STORAGE {storage}")
	token: str|None = args.token or os.environ.get(TOKEN_ENV) or None
	if token is None and args.host not in ("localhost", "127.0.0.1", "::1"):
		logger.warning(f"The API is open to the network without a token; set --token or {TOKEN_ENV} to require one.")

	cm = ConfigurationManager(storage_path=storage)
	def system_timezone_name() -> str|None:
		_, system = cm.settings_manager().open("system").get()
		return system.get("timezoneName") if system else None
	time_base = ConfiguredTimeOfDay(system_timezone_name)
	# the cache is evicted first, so that whoever hears of a change next reads the new file; the application is added once it exists
	watcher_sink = FanoutSink(ConfigurationManagerEvictionSink(cm))
	config_watcher = ConfigurationWatcher(time_base, watcher_sink, cm.STORAGE_PATH)
	# plugins and datasources may contribute API routers
	routers = {}
	routers.update(cm.load_routers(cm.enum_plugins()))
	routers.update(cm.load_routers(cm.enum_datasources()))
	app = create_app(
		WebSettings(app_path=args.app, cors_origin=args.cors, api_token=token),
		routers=routers
	)
	# start the application layer
	sink = TelemetrySink()
	xapp: Application = Application(APPNAME, sink)
	watcher_sink.add(xapp)
	try:
		xapp.start()
		force_reset: bool = False
		if storage is not None:
			force_reset = not os.path.exists(storage)
			if force_reset:
				logger.info("No storage folder detected, force_reset")
		else:
			logger.info("No storage folder specified, force_reset check bypassed")
		# TODO pull force_reset logic into host application (this code)
		options = StartOptions(storagePath=storage, hardReset=force_reset)
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		root.add_service(TimeOfDay, time_base)
		root.add_service(TelemetrySink, sink)
		root.add_service(Application, xapp)
		xapp.accept(StartEvent(time_base.current_time(), options, root))
		started = xapp.app_started.wait(timeout=5)
		if not started:
			logger.warning("Application start timed out")
		else:
			logger.info("Application is started")
		app.state.root_container = root

		msg = sink.receive()
		while msg is not None:
			logger.warning(f"startup message {msg}")
			msg = sink.receive()

		config_watcher.start()
		# endpoints are plain functions: they run in uvicorn's thread pool and may block on the (locked) configuration files
		# log_config=None keeps the logging configuration from logging.yaml
		uvicorn.run(app, host=args.host, port=port, log_config=None)
	except Exception as e:
		logger.error(f"Exception in main: {e}", exc_info=True)
	finally:
		logger.info("eInk Billboard application shut down start")
		try:
			xapp.accept(QuitMessage(time_base.current_time()))
			xapp.join(timeout=5)
			config_watcher.stop()
		except Exception as ee:
			logger.error(f"Exception during shutdown: {ee}", exc_info=True)
		finally:
			logger.info("eInk Billboard application shut down complete")

def main(argv: list[str]|None = None) -> None:
	configure_logging()
	run_application(parse_args(argv))

if __name__ == '__main__':
	main()
