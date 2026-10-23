"""The device password: claim a new device with its setup code, sign in state, change the password. See python/web/access.py."""
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel

from ..access import password_problem
from ..deps import require_auth
from ..errors import ApiError
from ..openapi import Done, json_body
from .session import client_of, start_session, too_many_tries, wrong_try

logger = logging.getLogger(__name__)

# not behind the sign-in check (a new device cannot sign in): `GET /access` and `POST /access/setup` say nothing a visitor could not see anyway,
# and the password change checks for itself
router = APIRouter(prefix="/access")

class AccessState(BaseModel):
	"""What the sign-in needs to know (the web app's AccessInfo)."""
	required: bool
	setupRequired: bool
	passwordSet: bool
	localOnly: bool

class SetupBody(BaseModel):
	"""The setup code (from the log or the panel) and the password to choose."""
	code: str
	password: str

class PasswordBody(BaseModel):
	"""The current password (when there is one) and the new one."""
	current: str | None = None
	new: str

@router.get("", response_model=AccessState)
def state(request: Request):
	"""What the web app needs to know before it can sign in: is a sign-in needed, and does this device still have to be set up."""
	access = request.app.state.access
	return { "required": access.required(), "setupRequired": access.setup_open(), "passwordSet": access.password_set(), "localOnly": access.local }

@router.post("/setup", response_model=Done, openapi_extra=json_body(SetupBody))
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
	if access.on_claimed is not None:
		try:
			access.on_claimed()
		except Exception as e:
			logger.warning(f"The panel's setup page could not be taken down ({type(e).__name__}).")
	request.app.state.throttle.succeeded(client_of(request))
	start_session(request, response)
	return { "success": True }

@router.put("/password", dependencies=[Depends(require_auth)], response_model=Done, openapi_extra=json_body(PasswordBody))
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
