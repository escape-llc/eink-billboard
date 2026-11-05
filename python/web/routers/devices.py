"""The buttons and the LED wired to the device (the GPIO settings): running a button's task, and playing an LED pattern, from the web app."""
from typing import Any

from fastapi import APIRouter, Body, Request

from ..errors import ApiError
from ..deps import CM
from ..documents import playlist_ids
from ..openapi import Choice, Done, answers, test_route
from ...device.led import PATTERNS
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

@router.post("/led/test", **test_route())
def test_led_pattern(request: Request, body: dict[str, Any] = Body(...)):
	"""The Test beside an LED pattern: plays the pattern chosen in the form on the LED of the saved pin, now (a pattern that repeats for a few seconds), the quiet hours or not."""
	pattern = body.get("value")
	if not isinstance(pattern, str) or pattern not in PATTERNS:
		return { "ok": False, "message": "Choose a pattern first." }
	if pattern == "off":
		return { "ok": True, "message": "Off: the LED stays dark." }
	if not application_of(request).led_test(pattern):
		return { "ok": False, "message": "There is no LED: choose its pin and save first (the GPIO tab says when it is open)." }
	return { "ok": True, "message": f"Playing {PATTERNS[pattern].title.lower()} on the LED." }
