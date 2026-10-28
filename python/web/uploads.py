"""A picture that arrives as a request's body (the push API's, the Gallery's): read with a bound, never more than a picture may be."""
from fastapi import Request

from ..utils.upload_image import MAX_UPLOAD_BYTES
from .errors import ApiError

async def read_limited(request: Request, error_id: str) -> bytes:
	"""The request's body, refused as soon as it is larger than a picture may be (a sender that does not say how long it is is cut off at the same size)."""
	declared = request.headers.get("content-length", "")
	too_big = ApiError(413, f"The picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", error_id)
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
