"""Sign in and out of the web app when the API requires a token. These are not behind the token check: signing in is how you get past it."""
from fastapi import APIRouter, Request, Response

from ..deps import SESSION_COOKIE, has_valid_bearer
from ..errors import ApiError

router = APIRouter(prefix="/session")

@router.post("")
def sign_in(request: Request, response: Response):
	"""
	Present the token as `Authorization: Bearer <token>`. When it is right, the server starts a session and sets the
	session cookie (HttpOnly, SameSite=Strict, so scripts cannot read it and other sites cannot send it).
	"""
	if not getattr(request.app.state, "api_token", None):
		return { "success": True, "required": False }
	if not has_valid_bearer(request):
		raise ApiError(401, "Missing or invalid API token.")
	store = request.app.state.sessions
	response.set_cookie(
		SESSION_COOKIE, store.create(),
		max_age=store.ttl, path="/api", httponly=True, samesite="strict",
		# plain HTTP is normal on a home network; a cookie marked Secure would never be sent back there
		secure=request.url.scheme == "https",
	)
	return { "success": True, "required": True }

@router.delete("")
def sign_out(request: Request, response: Response):
	request.app.state.sessions.delete(request.cookies.get(SESSION_COOKIE))
	response.delete_cookie(SESSION_COOKIE, path="/api")
	return { "success": True }
