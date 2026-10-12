"""Sign in and out of the web app when the device requires it. These are not behind the sign-in check: signing in is how you get past it."""
import logging
import math
from typing import Any

from fastapi import APIRouter, Body, Request, Response

from ..deps import SESSION_COOKIE, has_valid_bearer
from ..errors import ApiError, error_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session")

def client_of(request: Request) -> str:
	return request.client.host if request.client else "unknown"

def start_session(request: Request, response: Response) -> None:
	"""A new session for this browser: the server remembers it, the browser holds only an HttpOnly, SameSite=Strict cookie with its unguessable ID."""
	store = request.app.state.sessions
	response.set_cookie(
		SESSION_COOKIE, store.create(),
		max_age=store.ttl, path="/api", httponly=True, samesite="strict",
		# plain HTTP is normal on a home network; a cookie marked Secure would never be sent back there
		secure=request.url.scheme == "https",
	)

def too_many_tries(request: Request) -> Response|None:
	"""The answer for a client that has to wait (429 with Retry-After), or None when it may try."""
	wait = request.app.state.throttle.wait(client_of(request))
	if wait <= 0:
		return None
	seconds = math.ceil(wait)
	busy = error_response(429, f"Too many wrong tries. Try again in {seconds} seconds.", retryAfter=seconds)
	busy.headers["Retry-After"] = str(seconds)
	return busy

def wrong_try(request: Request, what: str) -> None:
	# the address and the count, never what was sent
	who = client_of(request)
	logger.warning(f"Failed {what} from {who} ({request.app.state.throttle.failed(who)} in a row).")

@router.post("")
def sign_in(request: Request, response: Response, body: Any = Body(None)):
	"""
	Present the API token as `Authorization: Bearer <token>`, or the device password as `{ "password": "..." }`. When it is right, the server
	starts a session and sets the session cookie (HttpOnly, SameSite=Strict, so scripts cannot read it and other sites cannot send it).
	"""
	access = request.app.state.access
	if not access.required():
		return { "success": True, "required": False }
	busy = too_many_tries(request)
	if busy is not None:
		return busy
	password = body.get("password") if isinstance(body, dict) else None
	if not (has_valid_bearer(request) or (password is not None and access.verify(password))):
		wrong_try(request, "sign-in")
		raise ApiError(401, "Wrong password." if password is not None else "Missing or invalid API token.")
	request.app.state.throttle.succeeded(client_of(request))
	start_session(request, response)
	return { "success": True, "required": True }

@router.delete("")
def sign_out(request: Request, response: Response):
	request.app.state.sessions.delete(request.cookies.get(SESSION_COOKIE))
	response.delete_cookie(SESSION_COOKIE, path="/api")
	return { "success": True }
