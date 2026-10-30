"""Play, stop, next and seek (to a playlist) for the playlist layer. The command goes to the Application task, which forwards it (python/task/application.py, `transport`)."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...task.application import Application
from ..deps import CM, get_container
from ..documents import playlist_ids
from ..errors import ApiError
from ..openapi import Answer, Done, answers

router = APIRouter(prefix="/transport")

class TransportRequest(BaseModel):
	command: Literal["play", "stop", "next", "seek"]
	# the playlist a `seek` goes to (its id, from `GET /api/devices/playlists`); not allowed with the other commands
	playlist_id: str | None = None

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
def send_transport(body: TransportRequest, request: Request, cm: CM):
	"""
	Forward a command: `play` (resume where it stopped), `stop`, `next` (the next track; a stopped layer plays from there) or `seek` (the first track of the playlist `playlist_id`, then on as usual).
	It is accepted, not done: the layer does it on its own thread, and its telemetry says what happened.
	"""
	if (body.command == "seek") != (body.playlist_id is not None):
		raise ApiError(422, "A seek names a playlist, and no other command does.", None)
	if body.playlist_id is not None and body.playlist_id not in playlist_ids(cm):
		raise ApiError(404, "No such playlist.", None)
	if not application_of(request).transport(body.command, body.playlist_id):
		raise ApiError(503, "The device is shutting down.")
	return { "success": True }
