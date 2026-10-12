"""FastAPI dependencies shared by the routers."""
import hmac
from typing import Annotated

from fastapi import Depends, Request

from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from .errors import ApiError

def get_container(request: Request) -> IServiceProvider|None:
	return getattr(request.app.state, "root_container", None)

def get_cm(request: Request) -> ConfigurationManager:
	isp = get_container(request)
	cm = isp.get_service(ConfigurationManager) if isp is not None else None
	if cm is None:
		raise ApiError(503, "Configuration Manager not available.")
	return cm

def get_time_of_day(request: Request) -> TimeOfDay:
	isp = get_container(request)
	tod = isp.get_service(TimeOfDay) if isp is not None else None
	return tod if tod is not None else SystemTimeOfDay()

SESSION_COOKIE = "eink_session"

def has_valid_bearer(request: Request) -> bool:
	token: str|None = getattr(request.app.state, "api_token", None)
	if not token:
		return False
	scheme, _, presented = request.headers.get("authorization", "").partition(" ")
	return scheme.lower() == "bearer" and hmac.compare_digest(presented.strip().encode(), token.encode())

def signed_in(app, authorization: str|None, session_cookie: str|None) -> bool:
	"""A Bearer token (scripts) or the cookie of a session (the web app): shared by the HTTP routes and the WebSocket."""
	token: str|None = getattr(app.state, "api_token", None)
	if token:
		scheme, _, presented = (authorization or "").partition(" ")
		if scheme.lower() == "bearer" and hmac.compare_digest(presented.strip().encode(), token.encode()):
			return True
	return bool(app.state.sessions.valid(session_cookie))

def require_auth(request: Request) -> None:
	"""
	When the device requires a sign-in (python/web/access.py), every /api request must present the API token as a Bearer token (scripts),
	or carry the cookie of a session started with the device password or the token (the web app, see routers/session.py).
	A new device that is not claimed yet answers 401 with `setup: true`.
	"""
	access = request.app.state.access
	if not access.required():
		return
	if signed_in(request.app, request.headers.get("authorization"), request.cookies.get(SESSION_COOKIE)):
		return
	if access.setup_open():
		raise ApiError(401, "This device is not set up yet.", None, setup=True)
	raise ApiError(401, "Sign in to use this device." if access.password_set() else "Missing or invalid API token.")

CM = Annotated[ConfigurationManager, Depends(get_cm)]
TOD = Annotated[TimeOfDay, Depends(get_time_of_day)]
