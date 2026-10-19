"""
Push a message or a picture to the panel from a script (Home Assistant, cron, CI, a doorbell): it is shown over everything for a few minutes, then the playlist is back. Whoever may use the
rest of the API may use this (the token or the session); a device that has not been claimed refuses it. The panel's rest after a refresh applies as ever, so a message shows when the panel
may be refreshed: the answer says roughly when.
"""
import logging
import re

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ...model.theme import current_inputs
from ...task.application import Application, PushRefused
from ...utils.message_image import MAX_TEXT_CHARACTERS, MAX_TITLE_CHARACTERS, render_message_image
from ...utils.upload_image import MAX_UPLOAD_BYTES, decode_upload
from ..deps import CM
from ..errors import ApiError
from .transport import application_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/display")

DEFAULT_MINUTES = 5
MAX_MINUTES = 60
# the control characters a text may not carry (a line break and a tab are text)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

class MessageRequest(BaseModel):
	text: str = Field(min_length=1, max_length=MAX_TEXT_CHARACTERS)
	title: str = Field("", max_length=MAX_TITLE_CHARACTERS)
	minutes: int = Field(DEFAULT_MINUTES, ge=1, le=MAX_MINUTES)

def _clean(text: str) -> str:
	return _CONTROL.sub("", text).strip()

def _pushed(result) -> dict:
	return { "success": True, "id": result.id, "title": result.title, "startsInSeconds": result.starts_in_seconds }

def _refused(e: PushRefused) -> ApiError:
	return ApiError(e.status, e.message, "display-push")

@router.post("/message")
def push_message(body: MessageRequest, request: Request, cm: CM):
	"""Show `text` (with an optional `title`) over everything for `minutes`. The answer has the `id` that takes it down again (`DELETE /api/display/message/{id}`) and `startsInSeconds`, the least it waits."""
	application = application_of(request)
	text, title = _clean(body.text), _clean(body.title)
	if not text:
		raise ApiError(422, "The message has no text.", "display-push", errors=[{ "path": ["text"], "message": "Required" }])
	try:
		size = application.content_size()
		image = render_message_image(cm.static_manager(), size, title, text, current_inputs(cm.settings_manager()))
		return _pushed(application.push_image(title or "Message", image, body.minutes))
	except PushRefused as e:
		raise _refused(e) from None

async def _limited_body(request: Request) -> bytes:
	"""The request's body, refused as soon as it is larger than a picture may be (a sender that does not say how long it is is cut off at the same size)."""
	declared = request.headers.get("content-length", "")
	too_big = ApiError(413, f"The picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", "display-push")
	if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
		raise too_big
	chunks: list[bytes] = []
	total = 0
	async for chunk in request.stream():
		total += len(chunk)
		if total > MAX_UPLOAD_BYTES:
			raise too_big
		chunks.append(chunk)
	return b"".join(chunks)

@router.post("/image")
def push_image(request: Request, picture: bytes = Depends(_limited_body), title: str = Query("", max_length=MAX_TITLE_CHARACTERS), minutes: int = Query(DEFAULT_MINUTES, ge=1, le=MAX_MINUTES)):
	"""
	Show a picture over everything for `minutes`: the request's body is the picture itself (PNG, JPEG, GIF or WEBP, at most 10 MB), `title` and `minutes` are in the address
	(`curl -X POST --data-binary @door.jpg -H "Content-Type: image/jpeg" "http://pi/api/display/image?minutes=2"`). It is shown whole, on a blurred margin of its own colors.
	"""
	application = application_of(request)
	try:
		size = application.content_size()
		try:
			image = decode_upload(picture, size)
		except ValueError as e:
			raise ApiError(415 if "not a picture" in str(e) else 422, str(e), "display-push") from None
		return _pushed(application.push_image(_clean(title) or "Picture", image, minutes))
	except PushRefused as e:
		raise _refused(e) from None

@router.delete("/message/{message_id}")
def delete_message(message_id: str, request: Request):
	"""Take a pushed message or picture down, whether it is showing or still waiting its turn. 404 when there is none (it was never made, or it is over)."""
	if not application_of(request).revoke_pushed(message_id):
		raise ApiError(404, "There is no such message.", "display-push")
	return { "success": True }
