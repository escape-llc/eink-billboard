#!/usr/bin/env python3

# run from root folder
# python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ./.storage

import argparse
import logging
import logging.config
import os
import socket
import warnings
from urllib.parse import urlsplit
from typing import Any

import yaml

from .model.configuration_watcher import ConfigurationWatcher
from .model.configuration_manager_eviction_sink import ConfigurationManagerEvictionSink
from .model.service_container import ServiceContainer
from .task.fanout_sink import FanoutSink
from .model.time_of_day import ConfiguredTimeOfDay, TimeOfDay
from .model.configuration_manager import ConfigurationManager

from .task.telemetry_hub import TelemetryHub
from .task.application import Application, StartEvent
from .task.messages import QuitMessage, StartOptions
from .web.access import AccessState, clear_password
from .web.app import WebSettings, create_app
from .utils.utils import local_address

APPNAME: str = "EInk Billboard"
TOKEN_ENV = "EINK_API_TOKEN"
PUBLIC_URL_ENV = "EINK_PUBLIC_URL"
# the default bundle is found relative to this file (not the working directory), so it works from any folder
DEFAULT_APP_PATH: str = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "dist"))

logger = logging.getLogger(__name__)

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

def public_url_of(text: str|None) -> str|None:
	"""`--public-url` / EINK_PUBLIC_URL: the address people use to reach this device, when the one it sees for itself is not it (a container's, a proxy's). None for anything but http(s) with a host."""
	if not text or not text.strip():
		return None
	parsed = urlsplit(text.strip())
	if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
		return None
	return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

def setup_address(port: int, public_url: str|None = None) -> str:
	"""Where to open the web app to set the device up: the configured public address, else its own address, or its name when it has none."""
	if public_url:
		return public_url
	address = local_address() or f"{socket.gethostname()}.local"
	return f"http://{address}" if port == 80 else f"http://{address}:{port}"

def announce_setup_code(access: AccessState, port: int, public_url: str|None = None) -> None:
	"""A device that is not claimed yet tells the owner how to claim it: in the log, the one place a visitor to the web app cannot see."""
	code = access.setup_code()
	if code:
		logger.warning(f"This device is not set up yet. Open {setup_address(port, public_url)} and enter the setup code {code} to choose its password.")

def setup_notice(access: AccessState, port: int, public_url: str|None = None) -> list[str]|None:
	"""The lines of the page the panel shows while the device is not claimed, or None."""
	code = access.setup_code()
	return [f"Open {setup_address(port, public_url)}", f"Setup code {code}"] if code else None

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
	parser.add_argument('--allow-host', action='append', default=[], help="A name this server answers to, besides localhost, addresses and the machine's own (repeatable; or EINK_ALLOW_HOSTS, comma separated)")
	parser.add_argument('--public-url', help=f"The address people use to reach this device, shown on the setup page and in the log (default: the {PUBLIC_URL_ENV} environment variable, else the device's own address, which is wrong in a container or behind a proxy)")
	parser.add_argument('--no-auth', action='store_true', help='Keep the device open on the network: no password, no setup code (a network you trust, on purpose)')
	parser.add_argument('--require-auth', action='store_true', help='Require the password (or setup) even when listening on this machine only')
	parser.add_argument('--reset-password', action='store_true', help='Forget the device password and exit: the device asks to be set up again with a new setup code')
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
	local = args.host in LOCAL_HOSTS
	public_text = args.public_url or os.environ.get(PUBLIC_URL_ENV)
	public_url = public_url_of(public_text)
	if public_text and public_text.strip() and public_url is None:
		logger.warning(f"--public-url / {PUBLIC_URL_ENV} is not an http(s) address with a host; ignored.")
	# a name of its own that people use to reach it is a name it answers to
	allowed_hosts = tuple(args.allow_host) + ((urlsplit(public_url).hostname,) if public_url and urlsplit(public_url).hostname else ())
	auth = "none" if args.no_auth else "always" if args.require_auth else "auto"
	if auth == "none" and not local:
		logger.warning("--no-auth: the device is open to the network, anyone who can reach it can read and change its settings.")

	cm = ConfigurationManager(storage_path=storage)
	if args.reset_password:
		print("The device password was forgotten; the device asks for a new setup code." if clear_password(cm) else "There was no device password.")
		return
	def system_timezone_name() -> str|None:
		_, system = cm.settings_manager().open("system").get()
		return system.get("timezoneName") if system else None
	time_base = ConfiguredTimeOfDay(system_timezone_name)
	# the cache is evicted first, so that whoever hears of a change next reads the new file; the application is added once it exists
	watcher_sink = FanoutSink(ConfigurationManagerEvictionSink(cm))
	# EINK_WATCH_POLL (seconds) for a storage whose file system sends no change events (a Windows folder mounted into a container)
	poll_text = os.environ.get("EINK_WATCH_POLL", "").strip()
	try:
		poll: float|None = float(poll_text) if poll_text else None
	except ValueError:
		logger.warning("EINK_WATCH_POLL is not a number of seconds, using file system events.")
		poll = None
	config_watcher = ConfigurationWatcher(time_base, watcher_sink, cm.STORAGE_PATH, poll=poll if poll and poll > 0 else None)
	# plugins and datasources may contribute API routers
	routers: dict[str, Any] = {}
	routers.update(cm.load_routers(cm.enum_plugins()))
	routers.update(cm.load_routers(cm.enum_datasources()))
	app = create_app(
		WebSettings(app_path=args.app, cors_origin=args.cors, api_token=token, allowed_hosts=allowed_hosts, auth=auth, local=local),
		routers=routers
	)
	# start the application layer
	# the telemetry route's sink: the live view of the web app (python/task/telemetry_hub.py)
	sink = TelemetryHub()
	xapp: Application = Application(APPNAME, sink)
	xapp.setup_notice = lambda: setup_notice(app.state.access, port, public_url)
	app.state.access.on_claimed = xapp.setup_done
	app.state.access.on_code_changed = xapp.setup_code_changed
	watcher_sink.add(xapp)
	try:
		xapp.start()
		force_reset: bool = False
		if storage is not None:
			force_reset = ConfigurationManager.needs_seeding(storage)
			if force_reset:
				logger.info("No storage detected (missing or empty folder), force_reset")
		else:
			logger.info("No storage folder specified, force_reset check bypassed")
		# TODO pull force_reset logic into host application (this code)
		options = StartOptions(storagePath=storage, hardReset=force_reset)
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		root.add_service(TimeOfDay, time_base)
		root.add_service(TelemetryHub, sink)
		root.add_service(Application, xapp)
		# before the start: the setup page asks the access rules (which read the settings through it) as soon as the display is ready
		app.state.root_container = root
		xapp.accept(StartEvent(time_base.current_time(), options, root))
		started = xapp.app_started.wait(timeout=5)
		if not started:
			logger.warning("Application start timed out")
		else:
			logger.info("Application is started")
		announce_setup_code(app.state.access, port, public_url)

		for event in sink.since(0):
			logger.warning(f"startup telemetry: {event.get('source')} {event.get('kind')} {event.get('message', '')}")

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
