"""Play, stop and next for the playlist layer. The command goes to the Application task, which forwards it (python/task/application.py, `transport`)."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...task.application import Application
from ..deps import get_container
from ..errors import ApiError
from ..openapi import Answer, Done, answers

router = APIRouter(prefix="/transport")

class TransportRequest(BaseModel):
	command: Literal["play", "stop", "next"]

class TransportState(Answer):
	"""Whether playback is stopped, and where the playlist layer is: its playlist and track by id (left out before its first track)."""
	stopped: bool
	playlist_id: str | None = None
	track_id: str | None = None

def application_of(request: Request) -> Application:
	isp = get_container(request)
	application = isp.get_service(Application) if isp is not None else None
	# the layers exist only once the application has started
	if application is None or application.playlist_layer is None:
		raise ApiError(503, "The device is still starting.")
	return application

@router.get("", **answers(TransportState))
def get_transport(request: Request):
	"""Whether playback is stopped, for the play/stop button, and the playlist and track the layer is on, for the System page's playlist panel."""
	application = application_of(request)
	answer: dict[str, object] = { "stopped": application.playback_stopped }
	position = application.playback_position
	if position is not None:
		answer["playlist_id"], answer["track_id"] = position
	return answer

@router.post("", **answers(Done))
def send_transport(body: TransportRequest, request: Request):
	"""
	Forward a command: `play` (resume where it stopped), `stop`, or `next` (the next track; a stopped layer plays from there).
	It is accepted, not done: the layer does it on its own thread, and its telemetry says what happened.
	"""
	if not application_of(request).transport(body.command):
		raise ApiError(503, "The device is shutting down.")
	return { "success": True }
