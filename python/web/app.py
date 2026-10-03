"""The web application: the JSON API under /api, plus the built web app (static files and the SPA entry page)."""
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..model.service_container import IServiceProvider
from .deps import require_token
from .errors import ApiError, install_error_handlers
from .routers import lookups, schedule, settings

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
	install_error_handlers(app)

	if web.cors_origin:
		app.add_middleware(
			CORSMiddleware,
			allow_origins=[web.cors_origin],
			allow_methods=["GET", "PUT"],
			allow_headers=["Content-Type", "Authorization"],
		)

	api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
	for module in (settings, lookups, schedule):
		api.include_router(module.router)
	for name, router in (routers or {}).items():
		api.include_router(router)
		logger.info(f"Registered router: {name}")
	app.include_router(api)

	# unknown API paths must stay JSON 404s and never fall through to the web app
	@app.api_route("/api/{path:path}", methods=["GET", "PUT", "POST", "DELETE", "PATCH"], include_in_schema=False)
	def api_not_found(path: str):
		raise ApiError(404, "Not found.")

	_mount_web_app(app, web.app_path)
	return app

def _mount_web_app(app: FastAPI, app_path: str|None) -> None:
	if not app_path:
		return
	index = os.path.join(app_path, "index.html")
	static = os.path.join(app_path, "static")
	if not os.path.isfile(index):
		logger.warning(f"Web app not found at '{app_path}'; serving the API only.")
		return
	if os.path.isdir(static):
		app.mount("/static", StaticFiles(directory=static), name="static")

	# the client-side router owns every other path
	@app.get("/{path:path}", include_in_schema=False)
	def spa(path: str):
		return FileResponse(index, media_type="text/html")
