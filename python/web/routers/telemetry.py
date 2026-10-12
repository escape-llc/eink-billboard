"""
The telemetry link (see `python/task/telemetry_hub.py`): the recent events, a WebSocket that follows them live, and the images the panel showed.

`router` is mounted under /api with the token check of every route. The WebSocket (`ws_router`) is mounted beside it and checks for itself,
because a browser cannot add a header to a WebSocket and CORS does not cover one:
- with a token configured, the handshake must carry the session cookie (or a Bearer header, for scripts), as /api does;
- the `Origin` must be this server's own or the configured `--cors` one: otherwise any page the viewer has open could read the device's
  telemetry (cross-site WebSocket hijacking).
A refused handshake is closed with 4401 (sign in) or 4403 (origin), and says nothing more.
"""
import asyncio
import hmac
import ipaddress
import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from ...task.telemetry_hub import LOCAL_ONLY, TelemetryHub
from ..deps import SESSION_COOKIE, get_container
from ..errors import ApiError

logger = logging.getLogger(__name__)
router = APIRouter()
ws_router = APIRouter()

PING_SECONDS = 30.0
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

def _hub(app) -> TelemetryHub|None:
	isp = getattr(app.state, "root_container", None)
	return isp.get_service(TelemetryHub) if isp is not None else None

def _on_device(client) -> bool:
	"""The caller is this machine itself (the address of the connection; forwarded headers are never trusted, so a proxy on the same machine makes everyone local)."""
	host = getattr(client, "host", None)
	if not host:
		return False
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False

def _for(client, event: dict) -> dict:
	"""An event as this caller may see it: the exception in full only on the device itself."""
	if _on_device(client) or not any(k in event for k in LOCAL_ONLY):
		return event
	return { k: v for k, v in event.items() if k not in LOCAL_ONLY }

def _required_hub(request) -> TelemetryHub:
	isp = get_container(request)
	hub = isp.get_service(TelemetryHub) if isp is not None else None
	if hub is None:
		raise ApiError(503, "Telemetry is not available.")
	return hub

@router.get('/telemetry')
def recent(request: Request, since: int = Query(0, ge=0)):
	"""The kept events newer than `since`, oldest first (a first paint, a script, or catching up)."""
	return [_for(request.client, e) for e in _required_hub(request).since(since)]

@router.get('/status')
def status(request: Request):
	"""Whether the display and the two layers came up: `{ ok, components: { name: { state: ok|failed|starting, message } } }`. Our words only."""
	return _required_hub(request).status()

@router.get('/display/current')
def current(request: Request):
	"""What the panel shows now: the last `shown` event, or null before anything was drawn."""
	event = _required_hub(request).current()
	return _for(request.client, event) if event is not None else None

@router.get('/display/images/{digest}')
def image(request: Request, digest: str, size: str = Query("thumb", pattern="^(thumb|full)$")):
	"""A shown image by its digest, as PNG. The digest only selects among the images kept; it is never a path, and an unknown one is a 404."""
	png = _required_hub(request).image(digest, size) if _DIGEST.match(digest) else None
	if png is None:
		raise ApiError(404, "No such image.")
	# a digest names one image for ever
	return Response(png, media_type="image/png", headers={ "Cache-Control": "private, max-age=31536000, immutable" })

def _origin_allowed(ws: WebSocket) -> bool:
	origin = ws.headers.get("origin")
	if origin is None:
		# not a browser (a script): nothing for a page to hijack; the token check still applies
		return True
	parts = urlsplit(origin)
	own = ws.headers.get("host")
	allowed = getattr(ws.app.state, "cors_origin", None)
	return (own is not None and parts.netloc == own) or (allowed is not None and origin.rstrip("/") == allowed.rstrip("/"))

def _signed_in(ws: WebSocket) -> bool:
	token = getattr(ws.app.state, "api_token", None)
	if not token:
		return True
	scheme, _, presented = ws.headers.get("authorization", "").partition(" ")
	if scheme.lower() == "bearer" and hmac.compare_digest(presented.strip().encode(), token.encode()):
		return True
	return bool(ws.app.state.sessions.valid(ws.cookies.get(SESSION_COOKIE)))

@ws_router.websocket('/telemetry/ws')
async def follow(ws: WebSocket, since: int = 0):
	"""Send what is newer than `since`, then every event as it happens; a ping keeps proxies from closing a quiet link."""
	if not _origin_allowed(ws) or not ws.app.state.hosts.allows(ws.headers.get("host")):
		await ws.close(code=4403)
		return
	if not _signed_in(ws):
		await ws.close(code=4401)
		return
	hub = _hub(ws.app)
	if hub is None:
		await ws.close(code=1011)
		return
	await ws.accept()
	sub = hub.subscribe(asyncio.get_running_loop())
	try:
		last = max(0, since)
		for event in hub.since(last):
			await ws.send_json(_for(ws.client, event))
			last = event["seq"]
		while True:
			try:
				event = await asyncio.wait_for(sub.next(), PING_SECONDS)
			except asyncio.TimeoutError:
				await ws.send_json({ "kind": "ping", "source": "telemetry" })
				continue
			# an event the history already sent is not sent again
			if event.get("seq", last + 1) > last:
				await ws.send_json(_for(ws.client, event))
				last = event.get("seq", last)
	except WebSocketDisconnect:
		pass
	finally:
		hub.unsubscribe(sub)
