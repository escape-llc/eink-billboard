"""
Uniform error responses for the web API.

Every non-2xx response has the body `{ "success": false, "message": str, "id": str|None }`
(plus `rev` on a revision conflict and `errors` on a validation failure), so the web app only has one shape to handle.
"""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

class ApiError(Exception):
	"""Raise from a route to produce the uniform error response."""
	def __init__(self, status_code: int, message: str, id: str|None = None, **extra: Any):
		super().__init__(message)
		self.status_code = status_code
		self.message = message
		self.id = id
		self.extra = extra

def error_response(status_code: int, message: str, id: str|None = None, **extra: Any) -> JSONResponse:
	body = { "success": False, "message": message, "id": id, **extra }
	return JSONResponse(status_code=status_code, content=body)

def install_error_handlers(app: FastAPI) -> None:
	@app.exception_handler(ApiError)
	async def _api_error(request: Request, exc: ApiError):
		return error_response(exc.status_code, exc.message, exc.id, **exc.extra)

	@app.exception_handler(RequestValidationError)
	async def _validation_error(request: Request, exc: RequestValidationError):
		errors = [{ "path": [str(p) for p in e.get("loc", ())], "message": e.get("msg", "") } for e in exc.errors()]
		return error_response(422, "Request validation failed", None, errors=errors)

	@app.exception_handler(StarletteHTTPException)
	async def _http_error(request: Request, exc: StarletteHTTPException):
		headers = getattr(exc, "headers", None)
		resp = error_response(exc.status_code, str(exc.detail))
		if headers:
			resp.headers.update(headers)
		return resp

	@app.exception_handler(Exception)
	async def _unhandled(request: Request, exc: Exception):
		# full details stay in the log; the client only sees a generic message
		logger.error(f"{request.method} {request.url.path}: unhandled exception", exc_info=exc)
		return error_response(500, "An internal error has occurred.")
