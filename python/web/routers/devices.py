"""The buttons and the outputs wired to the device (the GPIO settings): running a button's task, the outputs a feedback row names, and playing a cue, from the web app."""
from typing import Any

from fastapi import APIRouter, Body, Request

from ..errors import ApiError
from ..deps import CM
from ..documents import playlist_ids
from ..openapi import Choice, Done, answers, test_route
from ...device.cues import CUES
from ...device.gpio_output import SPEEDS
from ...device.outputs import output_rows
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

def stored_devices(cm: Any) -> dict[str, Any]:
	"""The saved `devices` settings (none saved: empty)."""
	_, content = cm.settings_manager().open("devices").get()
	return content if isinstance(content, dict) else {}

def _row_of(body: dict[str, Any]) -> dict[str, Any]:
	row = body.get("row")
	return row if isinstance(row, dict) else {}

def _no_output(name: str) -> dict:
	return { "ok": False, "message": f"The output {name} is not open: save it first, with its hardware connected (the GPIO tab says when it is open)." }

@router.get("/outputs", **answers(list[Choice]))
def get_outputs(cm: CM, kind: str|None = None):
	"""The outputs a feedback row can name (the GPIO settings' saved Outputs), by name; `kind`: only that kind's (a feedback section's), any other value none."""
	return [{ "name": row["name"], "value": row["name"] } for row in output_rows(stored_devices(cm)) if kind is None or row["kind"] == kind]

@router.post("/outputs/test", **test_route())
def test_feedback_cue(request: Request, body: dict[str, Any] = Body(...)):
	"""The Test beside a feedback row's cue: plays the cue chosen in the form on the row's output (a saved, open one), now (a cue that repeats for a few seconds on an LED), the quiet hours or not."""
	cue = body.get("value")
	output = _row_of(body).get("output")
	if not isinstance(cue, str) or cue not in CUES:
		return { "ok": False, "message": "Choose a cue first." }
	if not isinstance(output, str) or output == "":
		return { "ok": False, "message": "Choose an output first." }
	if cue == "off":
		return { "ok": True, "message": "Off: the output stays still." }
	if not application_of(request).output_test(output, cue):
		return _no_output(output)
	return { "ok": True, "message": f"Playing {CUES[cue].title.lower()} on {output}." }

# what the Test beside a speed plays
SPEED_TEST = "three"

@router.post("/outputs/speed-test", **test_route())
def test_output_speed(request: Request, body: dict[str, Any] = Body(...)):
	"""The Test beside a GPIO output's speed: plays three blinks at the speed chosen in the form on that output (a saved, open one), now, the quiet hours or not."""
	speed = body.get("value")
	output = _row_of(body).get("name")
	if not isinstance(speed, str) or speed not in SPEEDS:
		return { "ok": False, "message": "Choose a speed first." }
	if not isinstance(output, str) or not application_of(request).output_test(output, SPEED_TEST, { "speed": speed }):
		return _no_output(str(output or "this output"))
	return { "ok": True, "message": f"Playing three blinks at {speed} s a blink on {output}." }
