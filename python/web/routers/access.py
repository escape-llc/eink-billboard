"""The device password: claim a new device with its setup code, sign in state, change the password. See python/web/access.py."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response

from ..access import password_problem
from ..deps import require_auth
from ..errors import ApiError
from .session import client_of, start_session, too_many_tries, wrong_try

# not behind the sign-in check (a new device cannot sign in): `GET /access` and `POST /access/setup` say nothing a visitor could not see anyway,
# and the password change checks for itself
router = APIRouter(prefix="/access")

@router.get("")
def state(request: Request):
	"""What the web app needs to know before it can sign in: is a sign-in needed, and does this device still have to be set up."""
	access = request.app.state.access
	return { "required": access.required(), "setupRequired": access.setup_open(), "passwordSet": access.password_set(), "localOnly": access.local }

@router.post("/setup")
def setup(request: Request, response: Response, body: Any = Body(None)):
	"""Claim a new device: the setup code (from its log or its panel) and the password to choose. Starts a session."""
	access = request.app.state.access
	if not access.setup_open():
		raise ApiError(409, "This device is already set up.")
	busy = too_many_tries(request)
	if busy is not None:
		return busy
	data = body if isinstance(body, dict) else {}
	if not access.check_code(data.get("code")):
		wrong_try(request, "setup")
		raise ApiError(403, "That is not the setup code.")
	problem = password_problem(data.get("password"))
	if problem:
		raise ApiError(422, problem, None, errors=[{ "path": ["password"], "message": problem }])
	access.set_password(data["password"])
	request.app.state.throttle.succeeded(client_of(request))
	start_session(request, response)
	return { "success": True }

@router.put("/password", dependencies=[Depends(require_auth)])
def change_password(request: Request, response: Response, body: Any = Body(None)):
	"""Change the device password (the current one is needed when there is one). The caller stays signed in."""
	access = request.app.state.access
	data = body if isinstance(body, dict) else {}
	if access.password_set():
		busy = too_many_tries(request)
		if busy is not None:
			return busy
		if not access.verify(data.get("current")):
			wrong_try(request, "password change")
			raise ApiError(403, "The current password is not right.", None, errors=[{ "path": ["current"], "message": "Not the current password." }])
	problem = password_problem(data.get("new"))
	if problem:
		raise ApiError(422, problem, None, errors=[{ "path": ["new"], "message": problem }])
	access.set_password(data["new"])
	request.app.state.throttle.succeeded(client_of(request))
	start_session(request, response)
	return { "success": True }
