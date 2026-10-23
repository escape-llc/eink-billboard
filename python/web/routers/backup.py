"""
Back up the storage to an encrypted file, and restore it (#368, `docs/development.md`'s "Backup and Restore"). The file holds the settings with their API keys, so it is always encrypted with a passphrase of its
own (not the device password); the device password is never in it. Both routes need a **claimed** device: an unclaimed one has no owner to ask. The passphrase and the archive travel in the body of
the request only, are never stored or logged, and the answer is never cached.
"""
import base64
import binascii
import json
import logging
from datetime import datetime

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ...model.configuration_manager import RestoreFailed
from ...utils.backup_archive import MAX_ARCHIVE_BYTES, NOT_OPENED, BackupError, passphrase_problem, seal, unseal
from ..backup import MANIFEST, MANIFEST_FORMAT, check_documents, make_manifest, summarize, take_manifest
from ..deps import CM
from ..errors import ApiError
from ..openapi import Answer, answers, json_body
from .session import client_of, too_many_tries, wrong_try
from .transport import application_of

logger = logging.getLogger(__name__)
router = APIRouter()

# the archive travels as base64 inside the JSON body: a third larger than the file
MAX_BODY_BYTES = MAX_ARCHIVE_BYTES * 4 // 3 + 4096

async def _json_body(request: Request) -> dict:
	"""The request's JSON body, refused as soon as it is larger than a backup may be (a sender that does not say how long it is is cut off at the same size)."""
	too_big = ApiError(413, "That file is larger than a backup of this device can be.", "backup")
	declared = request.headers.get("content-length", "")
	if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
		raise too_big
	chunks: list[bytes] = []
	total = 0
	async for chunk in request.stream():
		total += len(chunk)
		if total > MAX_BODY_BYTES:
			raise too_big
		chunks.append(chunk)
	try:
		body = json.loads(b"".join(chunks))
	except ValueError:
		raise ApiError(400, "The request is not JSON.", "backup") from None
	if not isinstance(body, dict):
		raise ApiError(400, "The request is not JSON.", "backup")
	return body

class BackupBody(BaseModel):
	"""The passphrase of this backup, typed twice."""
	passphrase: str
	confirm: str

class RestoreBody(BaseModel):
	"""The backup file (base64), its passphrase, and whether to write it (without, only what would change)."""
	archive: str
	passphrase: str
	apply: bool = False

class RestoreFile(Answer):
	name: str
	label: str
	status: Literal["new", "changed"]

class Upgraded(Answer):
	"""A document from an older version: the versions it is brought from and to."""
	name: str
	label: str
	# "from" is a keyword
	from_: int = Field(alias="from")
	to: int

class RestoreSummary(Answer):
	"""What a restore would do (or did), by name: never a value."""
	success: bool
	applied: bool
	written: int | None = None
	files: list[RestoreFile]
	unchanged: int
	upgraded: list[Upgraded]
	restartNeeded: bool
	leftOut: int
	madeAt: str | None

def _claimed(request: Request):
	"""The application, when the device has been claimed; a backup holds the keys, and a restore changes everything: both are the owner's."""
	application = application_of(request)
	if not application.claimed():
		raise ApiError(403, "This device has not been claimed yet: enter the setup code (on the panel and in the log) in the web app first.", "backup")
	return application

@router.post("/backup", openapi_extra={ **json_body(BackupBody), "responses": { "200": { "description": "The encrypted backup file", "content": { "application/octet-stream": { "schema": { "type": "string", "format": "binary" } } } } } })
def make_backup(request: Request, cm: CM, body: dict = Depends(_json_body)):
	"""
	The storage as one encrypted file (`{ "passphrase": ..., "confirm": ... }`, the passphrase of this backup: at least 12 characters, typed twice). Answers the file itself (`application/octet-stream`).
	Not a point-in-time snapshot: each file is whole, and they are read while the device runs.
	"""
	_claimed(request)
	passphrase = body.get("passphrase")
	problem = passphrase_problem(passphrase)
	if problem:
		raise ApiError(422, problem, "backup", errors=[{ "path": ["passphrase"], "message": problem }])
	if not isinstance(passphrase, str) or body.get("confirm") != passphrase:
		raise ApiError(422, "The two passphrases are not the same.", "backup", errors=[{ "path": ["confirm"], "message": "Not the same" }])
	try:
		files = cm.backup_files()
		files[MANIFEST] = make_manifest(files)
		blob = seal(files, passphrase)
	except BackupError as e:
		raise ApiError(422, e.message, "backup") from None
	logger.info("A backup was made.")
	stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")
	return Response(blob, media_type="application/octet-stream", headers={
		"Content-Disposition": f'attachment; filename="eink-billboard-{stamp}.einkbackup"', "Cache-Control": "no-store" })

@router.post("/restore", **answers(RestoreSummary), openapi_extra=json_body(RestoreBody))
def restore_backup(request: Request, cm: CM, body: dict = Depends(_json_body)):
	"""
	Open a backup (`{ "archive": <base64>, "passphrase": ..., "apply": false|true }`). Without `apply` it only says what would change, by name (the summary the person confirms); with it the files
	are written. Every document is checked by the rules of the route that would have saved it; with any problem nothing is written. The device password is never touched (a backup does not hold it), and
	nothing is deleted: a file in the storage that the backup does not have stays.
	"""
	application = _claimed(request)
	busy = too_many_tries(request)
	if busy is not None:
		return busy
	try:
		archive = base64.b64decode(body.get("archive") or "", validate=True)
	except (binascii.Error, ValueError, TypeError):
		raise ApiError(422, "That is not a backup file.", "backup") from None
	try:
		files = unseal(archive, body.get("passphrase"))
	except BackupError as e:
		if e.message == NOT_OPENED:
			wrong_try(request, "restore")
			raise ApiError(403, e.message, "backup", errors=[{ "path": ["passphrase"], "message": "Not right" }]) from None
		raise ApiError(422, e.message, "backup") from None
	request.app.state.throttle.succeeded(client_of(request))
	manifest = take_manifest(files)
	if manifest is not None and manifest.format > MANIFEST_FORMAT:
		raise ApiError(422, "That backup was made by a newer version of the app than this one: update the app, then restore it.", "backup")
	documents, unreadable = cm.backup_documents(files)
	accepted, left_out, problems, upgraded = check_documents(cm, documents)
	if problems:
		raise ApiError(422, "The backup holds documents this version cannot take. Nothing was changed.", "backup", errors=problems)
	summary = summarize(cm, accepted, upgraded)
	summary["leftOut"] = len(left_out) + len(unreadable)
	summary["madeAt"] = manifest.created if manifest is not None else None
	if body.get("apply") is not True:
		return { "success": True, "applied": False, **summary }
	refused = application.begin_restore()
	if refused is not None:
		raise ApiError(409, refused, "backup")
	written: list[str] = []
	ok = False
	try:
		changed = { f["name"] for f in summary["files"] }
		written = cm.write_backup({ name: document for name, document in accepted.items() if name in changed })
		ok = True
	except RestoreFailed:
		raise ApiError(500, "A file could not be written, so the files written before it were put back. Nothing was changed.", "backup") from None
	finally:
		# always: the Application holds the change notifications back until it hears this
		application.end_restore(ok, len(written))
	logger.info(f"A backup was restored: {len(written)} files.")
	return { "success": True, "applied": True, "written": len(written), **summary }
