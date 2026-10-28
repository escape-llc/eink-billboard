"""
The Gallery's routes (#238), mounted under /api like every data source's: list the pictures, show one, pin and remove them, add one from the device the web app runs on, and keep one the panel
showed. Whoever may use the rest of the API may use these.

The picture's id in an address is only ever matched against the Gallery's own index (`GalleryStore`), never made into a path: an id that is not in it is a 404, in words that do not echo it.
Every change is told as telemetry (`gallery-kept`, `gallery-removed`, `gallery-pinned`, which `gallery.py` also sends when a producer's picture is kept), so a page that is open asks again.
"""
import collections
import io
import logging
import re
import threading
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from ...model.configuration_manager import DatasourceConfigurationManager
from ...task.messages import Telemetry
from ...task.telemetry_hub import TelemetryHub
from ...utils.upload_image import open_picture
from ...web.deps import CM, get_container, get_time_of_day
from ...web.errors import ApiError
from ...web.openapi import Answer, Done, answers, json_body
from ...web.uploads import read_limited
from .gallery import MAX_TITLE, encode
from .offer import CHANGED, GALLERY_ID
from .store import GalleryStore, Kept, bounds

logger = logging.getLogger(__name__)

# mounted under /api by the web application
gallery_router = APIRouter(prefix="/datasource/gallery")

_ID = re.compile(r"^[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
THUMB_SIDE = 320
# thumbnails are made once per picture and kept a while (a picture never changes under its id)
_THUMBS: collections.OrderedDict[str, bytes] = collections.OrderedDict()
_THUMBS_LOCK = threading.Lock()
MAX_THUMBS = 256

class Item(Answer):
	"""One picture of the Gallery. `origin` is the data source that drew it (`upload`, or `display` for one the panel showed); `prompt` is only there for a picture that was drawn from one."""
	id: str
	title: str | None = None
	origin: str | None = None
	prompt: str | None = None
	added: str
	size: int
	width: int | None = None
	height: int | None = None
	pinned: bool

class Items(Answer):
	"""The pictures, newest first, and how many and how many bytes the Gallery holds (against its limits)."""
	items: list[Item]
	count: int
	bytes: int
	maxPictures: int
	maxBytes: int

class KeepAnswer(Answer):
	"""What keeping a picture did: `kept` is false for one already there (`duplicate`); `id` names it either way."""
	success: bool
	kept: bool
	id: str
	message: str

class PinBody(BaseModel):
	pinned: bool

class SaveBody(BaseModel):
	"""A picture the panel showed (its digest, from the telemetry), and the title to keep it under."""
	digest: str
	title: str = ""

def _store(cm: CM) -> tuple[GalleryStore, DatasourceConfigurationManager]:
	dscm = cm.datasource_manager(GALLERY_ID)
	return GalleryStore(dscm), dscm

def _tell(request: Request, kind: str, message: str, **values: Any) -> None:
	"""Tell the web app what changed; a hub that is not there (a test, a start that failed) is nobody to tell."""
	isp = get_container(request)
	hub = isp.get_service(TelemetryHub) if isp is not None else None
	if hub is None:
		return
	try:
		hub.accept(Telemetry(get_time_of_day(request).current_time(), "data-source", { "kind": kind, "datasource": GALLERY_ID, "message": message, "changed": CHANGED, **values }))
	except Exception as e:
		logger.warning(f"A Gallery event could not be sent ({type(e).__name__}).")

def _no_such_picture() -> ApiError:
	return ApiError(404, "There is no such picture in the Gallery.", "gallery")

def _item_id(item_id: str) -> str:
	if not _ID.match(item_id):
		raise _no_such_picture()
	return item_id

@gallery_router.get("/items", **answers(Items))
def list_items(cm: CM):
	"""The Gallery's pictures, newest first, with its totals and limits."""
	store, dscm = _store(cm)
	items = store.items()
	_, settings = dscm.open().get()
	maximum, max_bytes = bounds(settings)
	return { "items": items, "count": len(items), "bytes": sum(i["size"] for i in items if isinstance(i.get("size"), int)), "maxPictures": maximum, "maxBytes": max_bytes }

def _thumbnail(item_id: str, data: bytes) -> bytes:
	with _THUMBS_LOCK:
		found = _THUMBS.get(item_id)
		if found is not None:
			_THUMBS.move_to_end(item_id)
			return found
	with Image.open(io.BytesIO(data)) as opened:
		picture = opened.convert("RGB")
		picture.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
	out = io.BytesIO()
	picture.save(out, "JPEG", quality=80)
	made = out.getvalue()
	with _THUMBS_LOCK:
		_THUMBS[item_id] = made
		while len(_THUMBS) > MAX_THUMBS:
			_THUMBS.popitem(last=False)
	return made

@gallery_router.get("/items/{item_id}/image", responses={ 200: { "content": { "image/jpeg": { "schema": { "type": "string", "format": "binary" } } } } })
def get_image(item_id: str, cm: CM, size: str = Query("thumb", pattern="^(thumb|full)$")):
	"""A picture as a JPEG, the whole of it or a thumbnail. A picture never changes under its id, so the answer may be kept for ever."""
	store, _ = _store(cm)
	data = store.read(_item_id(item_id))
	if data is None:
		raise _no_such_picture()
	body = data if size == "full" else _thumbnail(item_id, data)
	return Response(body, media_type="image/jpeg", headers={ "Cache-Control": "private, max-age=31536000, immutable" })

@gallery_router.put("/items/{item_id}/pin", **answers(Done), openapi_extra=json_body(PinBody))
def pin_item(item_id: str, request: Request, cm: CM, body: dict[str, Any] = Body(...)):
	"""Pin a picture (the limits never remove it) or let it go back to being one that can be removed."""
	if not isinstance(body.get("pinned"), bool):
		raise ApiError(422, "Say whether to pin it.", "gallery")
	store, _ = _store(cm)
	if not store.pin(_item_id(item_id), body["pinned"]):
		raise _no_such_picture()
	_tell(request, "gallery-pinned", "A Gallery picture was pinned." if body["pinned"] else "A Gallery picture was unpinned.")
	return { "success": True }

@gallery_router.delete("/items/{item_id}", **answers(Done))
def remove_item(item_id: str, request: Request, cm: CM):
	"""Remove a picture, pinned or not."""
	store, _ = _store(cm)
	if not store.remove(_item_id(item_id)):
		raise _no_such_picture()
	_tell(request, "gallery-removed", "A picture was removed from the Gallery.")
	return { "success": True }

def _kept(request: Request, cm: CM, image: Image.Image, title: str, origin: str) -> dict:
	"""Keep a picture the person gave (or the panel showed) and say what came of it."""
	store, dscm = _store(cm)
	_, settings = dscm.open().get()
	maximum, max_bytes = bounds(settings)
	result: Kept = store.keep(encode(image), { "title": title[:MAX_TITLE] or None, "origin": origin, "width": image.width, "height": image.height },
		get_time_of_day(request).current_time(), maximum, max_bytes)
	if result.reason == "too-big":
		raise ApiError(413, "The picture is larger than the whole Gallery's size limit.", "gallery")
	if result.reason == "changed":
		raise ApiError(409, "The Gallery was changed while the picture was kept: try again.", "gallery")
	if result.kept:
		_tell(request, "gallery-kept", f"A picture was added to the Gallery ({origin}); it holds {result.count}.", bytes=result.bytes, count=result.count)
		if result.evicted:
			_tell(request, "gallery-evicted", f"The Gallery let {result.evicted} older picture(s) go to stay within its limits.", count=result.count)
	return { "success": True, "kept": result.kept, "id": result.id, "message": "Kept in the Gallery." if result.kept else "That picture is already in the Gallery." }

async def _upload_body(request: Request) -> bytes:
	return await read_limited(request, "gallery")

@gallery_router.post("/items", **answers(KeepAnswer), openapi_extra={ "requestBody": { "required": True, "content": { kind: { "schema": { "type": "string", "format": "binary" } }
		for kind in ("image/png", "image/jpeg", "image/gif", "image/webp") } } })
def add_item(request: Request, cm: CM, picture: bytes = Depends(_upload_body), title: str = Query("", max_length=MAX_TITLE)):
	"""Add a picture: the request's body is the picture itself (PNG, JPEG, GIF or WEBP, at most 10 MB, checked by its content). It is kept as a JPEG, whole, and fitted to the panel when it is shown."""
	try:
		image = open_picture(picture)
	except ValueError as e:
		raise ApiError(415 if "not a picture" in str(e) else 422, str(e), "gallery") from None
	return _kept(request, cm, image, title.strip(), "upload")

@gallery_router.post("/items/from-display", **answers(KeepAnswer), openapi_extra=json_body(SaveBody))
def save_shown(request: Request, cm: CM, body: dict[str, Any] = Body(...)):
	"""Keep a picture the panel showed lately (its digest is in the telemetry), as it was shown: with any caption or overlay drawn on it, not the photograph alone."""
	digest, title = body.get("digest"), body.get("title", "")
	if not isinstance(digest, str) or not _DIGEST.match(digest) or not isinstance(title, str):
		raise ApiError(422, "Say which picture the panel showed.", "gallery")
	isp = get_container(request)
	hub = isp.get_service(TelemetryHub) if isp is not None else None
	image = hub.snapshot(digest) if hub is not None else None
	if image is None:
		raise ApiError(404, "The device no longer has that picture: it keeps only the last few it showed.", "gallery")
	return _kept(request, cm, image, title.strip() or "Shown on the panel", "display")
