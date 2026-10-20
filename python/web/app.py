"""The web application: the JSON API under /api, plus the built web app (static files and the SPA entry page)."""
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider
from .access import AccessState
from .deps import require_auth
from .errors import ApiError, error_response, install_error_handlers
from .hosts import HostPolicy
from .routers import access, backup, display, fonts, lookups, schedule, session, settings, system, telemetry, theme, transport
from .sessions import SessionStore, SignInThrottle

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class WebSettings:
	"""Options from the command line / environment."""
	app_path: str|None = None
	"""Folder of the built web app (contains index.html and static/); None serves the API only."""
	cors_origin: str|None = None
	"""Browser origin allowed to call the API cross-site, e.g. the Vite dev server."""
	api_token: str|None = None
	"""The credential of scripts: `Authorization: Bearer <token>` (it also signs in the web app)."""
	auth: str = "auto"
	"""`auto` (a device on the network must be claimed, a local one is open until a password is set), `none` (--no-auth) or `always` (--require-auth)."""
	local: bool = True
	"""The server listens on this machine only (localhost); see `access.py`."""
	allowed_hosts: tuple[str, ...] = ()
	"""Names (besides localhost, addresses and this machine's) the server answers to; see `hosts.py`."""

def create_app(web: WebSettings, root_container: IServiceProvider|None = None, routers: Mapping[str, APIRouter]|None = None) -> FastAPI:
	"""
	Build the application. `root_container` can also be assigned later (`app.state.root_container`),
	because the services only exist once the Application task has started.
	`routers` are the extra API routers plugins and datasources contribute; they are mounted under /api.
	"""
	app = FastAPI(title="eInk Billboard", docs_url=None, redoc_url=None, openapi_url=None)
	app.state.root_container = root_container
	app.state.api_token = web.api_token
	app.state.sessions = SessionStore()
	# the stored password is read from the configuration manager, which only exists once the application has started
	def _manager():
		isp = app.state.root_container
		return isp.get_service(ConfigurationManager) if isp is not None else None
	app.state.access = AccessState(web.auth, web.local, web.api_token, _manager)
	app.state.throttle = SignInThrottle()
	# the telemetry WebSocket checks the page's origin against this one too (CORS does not cover a WebSocket)
	app.state.cors_origin = web.cors_origin
	app.state.hosts = HostPolicy(web.allowed_hosts)
	install_error_handlers(app)

	@app.middleware("http")
	async def known_host(request: Request, call_next):
		# DNS rebinding: a page of another name that resolves to this device is refused (hosts.py)
		if not app.state.hosts.allows(request.headers.get("host")):
			return error_response(421, "This server does not answer to that name. Use its address, or start it with --allow-host.")
		return await call_next(request)

	if web.cors_origin:
		app.add_middleware(
			CORSMiddleware,
			allow_origins=[web.cors_origin],
			# the web app signs in with a cookie, so a cross-origin development page must be allowed to send it
			allow_credentials=True,
			allow_methods=["GET", "PUT", "PATCH", "POST", "DELETE"],
			allow_headers=["Content-Type", "Authorization"],
		)

	api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
	for module in (settings, lookups, schedule, telemetry, fonts, theme, transport, display, backup, system):
		api.include_router(module.router)
	for name, router in (routers or {}).items():
		api.include_router(router)
		logger.info(f"Registered router: {name}")
	@api.get("/openapi.json", include_in_schema=False)
	def openapi_document():
		return app.openapi()

	@api.get("/docs", include_in_schema=False)
	def swagger_ui():
		return get_swagger_ui_html(openapi_url="/api/openapi.json", title="eInk Billboard - API")

	app.include_router(api)
	# not behind the token check: signing in is how you get past it
	app.include_router(session.router, prefix="/api")
	app.include_router(access.router, prefix="/api")
	# checks the session and the origin itself: a WebSocket has no request for the token dependency
	app.include_router(telemetry.ws_router, prefix="/api")

	# unknown API paths must stay JSON 404s and never fall through to the web app
	@app.api_route("/api/{path:path}", methods=["GET", "PUT", "POST", "DELETE", "PATCH"], include_in_schema=False)
	def api_not_found(path: str):
		raise ApiError(404, "Not found.")

	_mount_web_app(app, web.app_path)
	return app

def _mount_web_app(app: FastAPI, app_path: str|None) -> None:
	"""Serve the built web app (Vite's default layout: index.html and public/ files at the root, hashed bundles in assets/)."""
	if not app_path:
		return
	root = os.path.realpath(app_path)
	index = os.path.join(root, "index.html")
	if not os.path.isfile(index):
		logger.warning(f"Web app not found at '{app_path}'; serving the API only.")
		return

	# the folder prefix every served file must start with
	prefix = root if root.endswith(os.sep) else root + os.sep

	def _file_in_bundle(path: str) -> str|None:
		"""The real file the URL path names, only if it is inside the bundle folder."""
		if not path:
			return None
		try:
			# resolve "..", symbolic links, and the rest first, then require the result to be under the bundle folder
			candidate = os.path.realpath(os.path.join(root, path))
		except (OSError, ValueError):
			return None
		if candidate.startswith(prefix) and os.path.isfile(candidate):
			return candidate
		return None

	# index.html names the bundles of this build, and the public files keep their names across builds: the browser asks again every time
	# (a 304 when nothing changed). Without it a browser may keep an old index.html for a while (heuristic freshness) and run the old app after an update.
	revalidate = {"Cache-Control": "no-cache"}

	# existing files are served as they are; the client-side router owns every other path
	@app.get("/{path:path}", include_in_schema=False)
	def web_app(path: str):
		file = _file_in_bundle(path)
		if file is None and path.startswith("assets/"):
			# a bundle of another build (a tab opened before an update asks for its old chunks): a 404, never the app's page, which a
			# browser cannot run as a module (it showed "Failed to fetch dynamically imported module" with a 200); the app reloads itself
			return JSONResponse({ "success": False, "message": "Not found", "id": None }, status_code=404, headers=revalidate)
		if file is None:
			return FileResponse(index, media_type="text/html", headers=revalidate)
		if path.startswith("assets/"):
			# the file names carry a content hash, so they never change
			return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})
		return FileResponse(file, headers=revalidate)
