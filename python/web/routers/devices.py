"""The buttons wired to the device (the Devices settings' `triggers`): running a button's task from the web app."""
from fastapi import APIRouter, Request

from ..errors import ApiError
from ..openapi import Done, answers
from .transport import application_of

router = APIRouter(prefix="/devices")

@router.post("/triggers/{pin}/run", status_code=202, **answers(Done))
def run_button_task(pin: int, request: Request):
	"""Run the task the button on `pin` carries (its saved row), as if it was pressed: the Devices settings' Run now. The answer is that it was asked to."""
	reason = application_of(request).run_trigger(pin)
	if reason != "ok":
		raise ApiError(409, reason, None)
	return { "success": True }
