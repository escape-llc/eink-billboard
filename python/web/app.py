"""The web application: the JSON API under /api, plus the built web app (static files and the SPA entry page)."""
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from ..model.service_container import IServiceProvider
from .deps import require_token
from .errors import ApiError, install_error_handlers
from .routers import lookups, schedule, session, settings
from .sessions import SessionStore

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class WebSettings:
	"""Options from the command line / environment."""
	app_path: str|None = None
	"""Folder of the built web app (contains index.html and static/); None serves the API only."""
	cors_origin: str|None = None
	"""Browser origin allowed to call the API cross-site, e.g. the Vite dev server."""
	api_token: str|None = None
	"""When set, every /api request must carry `Authorization: Bearer <token>`."""

def create_app(web: WebSettings, root_container: IServiceProvider|None = None, routers: Mapping[str, APIRouter]|None = None) -> FastAPI:
	"""
	Build the application. `root_container` can also be assigned later (`app.state.root_container`),
	because the services only exist once the Application task has started.
	`routers` are the extra API routers plugins and datasources contribute; they are mounted under /api.
	"""
	app = FastAPI(title="eInk Billboard", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
	app.state.root_container = root_container
	app.state.api_token = web.api_token
	app.state.sessions = SessionStore()
	install_error_handlers(app)

	if web.cors_origin:
		app.add_middleware(
			CORSMiddleware,
			allow_origins=[web.cors_origin],
			# the web app signs in with a cookie, so a cross-origin development page must be allowed to send it
			allow_credentials=True,
			allow_methods=["GET", "PUT", "POST", "DELETE"],
			allow_headers=["Content-Type", "Authorization"],
		)

	api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
	for module in (settings, lookups, schedule):
		api.include_router(module.router)
	for name, router in (routers or {}).items():
		api.include_router(router)
		logger.info(f"Registered router: {name}")
	app.include_router(api)
	# not behind the token check: signing in is how you get past it
	app.include_router(session.router, prefix="/api")

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

	# existing files are served as they are; the client-side router owns every other path
	@app.get("/{path:path}", include_in_schema=False)
	def web_app(path: str):
		file = _file_in_bundle(path)
		if file is None:
			return FileResponse(index, media_type="text/html")
		if path.startswith("assets/"):
			# the file names carry a content hash, so they never change
			return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})
		return FileResponse(file)
