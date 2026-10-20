"""
A coarse location from the device's public IP address (#426), for the Location field's "Locate by IP" button. The device asks ipapi.co (a fixed host, no key) from here, because the
browser may be on another network and a browser's call would meet CORS. **It only answers**: nothing is saved, the person decides whether to keep it. The service sees the device's public
address (the button says so). Always our words: never the service's text, and an answer that is not two sane numbers is a refusal.
"""
import logging
from typing import Any

import httpx

from ..task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context

logger = logging.getLogger(__name__)

API = "https://ipapi.co/json/"
MAX_BYTES = 64 * 1024

def describe(response: httpx.Response) -> dict[str, Any]:
	"""What an answer of the service comes to: `{ ok, message, latitude?, longitude? }`, in our words."""
	if response.status_code == 429:
		return { "ok": False, "message": "The location service says too many requests were made today. Try again later, or choose the place on the map." }
	if response.status_code != 200 or len(response.content) > MAX_BYTES:
		return { "ok": False, "message": f"The location service answered {response.status_code}." if response.status_code != 200 else "The location service's answer is too large." }
	try:
		body = response.json()
		latitude, longitude = body["latitude"], body["longitude"]
		ok = isinstance(body, dict) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (latitude, longitude)) and -90 <= latitude <= 90 and -180 <= longitude <= 180
	except (ValueError, KeyError, TypeError):
		ok = False
	if not ok:
		# the service answers 200 with an error for some refusals (a reserved address, a limit): no position
		return { "ok": False, "message": "The location service gave no position for this device's address." }
	return { "ok": True, "message": "A rough position from this device's public IP address (about the city). Move the marker if it is not right, then save.", "latitude": round(float(latitude), 4), "longitude": round(float(longitude), 4) }

async def locate() -> dict[str, Any]:
	"""Ask the service about the caller's own address: `{ ok, message, latitude?, longitude? }`."""
	async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), transport=AsyncHttpWorkerPool.default_transport, verify=tls_context()) as client:
		try:
			response = await client.get(API, headers={ "Accept": "application/json", "User-Agent": "eink-billboard" })
		except httpx.HTTPError as ex:
			logger.warning(f"The location lookup could not reach the service ({type(ex).__name__}).")
			return { "ok": False, "message": "The location service could not be reached. Is the device on the internet?" }
	return describe(response)
