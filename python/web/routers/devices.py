"""The buttons wired to the device (the GPIO settings' `triggers`): running a button's task from the web app."""
from fastapi import APIRouter, Request

from ..errors import ApiError
from ..deps import CM
from ..documents import playlist_ids
from ..openapi import Choice, Done, answers
from .transport import application_of

router = APIRouter(prefix="/devices")

@router.get("/playlists", **answers(list[Choice]))
def get_playlists(cm: CM):
	"""The playlists a button can play (the GPIO settings' Play playlist): each stores its id and shows its name."""
	return [{ "name": name, "value": ident } for ident, name in playlist_ids(cm).items()]

@router.post("/triggers/{pin}/run", status_code=202, **answers(Done))
def run_button_task(pin: int, request: Request):
	"""Run the task the button on `pin` carries (its saved row), as if it was pressed: the GPIO settings' Run now. The answer is that it was asked to."""
	reason = application_of(request).run_trigger(pin)
	if reason != "ok":
		raise ApiError(409, reason, None)
	return { "success": True }
