"""
Thunderforest as an API data source (`DataSourceApi`, #428): the key and the maps it keeps, shared by every task, and nothing drawn. `open_async` answers the picture the Static Maps API
makes for a style, a position, a zoom and a size; the Thunderforest Map page source asks it with `dsec.use` and draws it with its attribution.

The key is in the address (`apikey=`), so it is hidden in the `httpx` log lines and never in a message or in what is kept; a failure says what happened ("refused the key", "the quota is
used up"), in our words. A map comes through the kept-downloads pool (`download_for`): a place and a zoom hardly change, so one call a week keeps the free plan's quota for new places.
Thunderforest allows caching on the device; it asks for an honest `User-Agent`.
"""
import logging
import re
from typing import Any, Mapping
from urllib.parse import quote

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context
from ..content_cache import download_for
from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext

API = "https://api.thunderforest.com/static"
# the styles the descriptor offers (a style is part of the address, so only these are ever put in it)
STYLES = ("transport", "cycle", "outdoors", "landscape", "atlas")
# the service's largest picture, and ours: a map for a panel is a few hundred kilobytes
MAX_SIDE = 2560
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# a place and a zoom hardly change: kept for a week (the service's own headers can shorten that)
DEFAULT_CONTENT_HOURS = 168.0
HEADERS = { "User-Agent": "eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/)", "Accept": "image/png" }
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

class HideKey(logging.Filter):
	"""Thunderforest takes the key in the address, and the HTTP client logs addresses: the key is hidden in what it logs."""
	_KEY = re.compile(r"(apikey=)[^&\s\"']+", re.IGNORECASE)
	def filter(self, record: logging.LogRecord) -> bool:
		try:
			text = record.getMessage()
		except Exception:
			return True
		if "apikey=" in text.lower():
			record.msg, record.args = self._KEY.sub(r"\g<1>***", text), None
		return True

for _name in ("httpx", "httpcore"):
	logging.getLogger(_name).addFilter(HideKey())

logger = logging.getLogger(__name__)

def map_address(style: str, latitude: float, longitude: float, zoom: int, size: tuple[int, int], key: str) -> str:
	"""The Static Maps address. Only our own values reach it: the style from `STYLES`, numbers formatted here, the size clamped, the key encoded."""
	if style not in STYLES:
		raise PermanentError("Choose the map style in the task's settings.")
	width, height = (max(1, min(MAX_SIDE, int(side))) for side in size)
	return f"{API}/{style}/{longitude:.5f},{latitude:.5f},{max(0, min(22, int(zoom)))}/{width}x{height}.png?apikey={quote(key, safe='')}"

def refusal(status: int) -> Exception:
	"""What a status of the service comes to, in our words (never its text, which can quote the key)."""
	if status in (401, 403):
		return PermanentError("Thunderforest refused the API key. Check it in the Thunderforest settings (a new key can take a few minutes to start working).")
	if status in (402, 429):
		return RuntimeError("Thunderforest says its quota for this key is used up. The map is shown again when the quota renews.")
	return RuntimeError(f"Thunderforest answered {status}.")

async def check_key(key: str) -> dict[str, Any]:
	"""Ask for the smallest map with this key and say what came of it: `{ ok, message }`, in our words (the address holds the key)."""
	async with httpx.AsyncClient(timeout=TIMEOUT, transport=AsyncHttpWorkerPool.default_transport, verify=tls_context(), headers=HEADERS) as client:
		try:
			response = await client.get(map_address("transport", 0.0, 0.0, 1, (64, 64), key))
		except httpx.HTTPError as ex:
			logger.warning(f"Testing a Thunderforest key could not reach the service ({type(ex).__name__}).")
			return { "ok": False, "message": "Thunderforest could not be reached. Is the device on the internet?" }
	if response.status_code != 200:
		return { "ok": False, "message": str(refusal(response.status_code)) }
	return { "ok": True, "message": "Thunderforest accepts this key." }

def stored_key(dscm: DatasourceConfigurationManager) -> str:
	_, settings = dscm.open().get()
	key = (settings or {}).get("apiKey")
	if not isinstance(key, str) or not key.strip():
		raise PermanentError("The Thunderforest API key is not set. Add it in the Thunderforest settings (it is free).")
	return key.strip()

class ThunderforestApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)`: the map of `params` as PNG `bytes`, kept for `contentCacheHours` and shared by every task: `style` (one of `STYLES`), `latitude`, `longitude`, `zoom`
	and `size` (width, height; at most `MAX_SIDE`). A missing or refused key is a PermanentError naming the settings; a used-up quota is a failure that is tried again.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> bytes:
		key = stored_key(dsec.provider.required(DatasourceConfigurationManager))
		url = map_address(str(params.get("style") or "transport"), float(params["latitude"]), float(params["longitude"]), int(params.get("zoom") or 12), params["size"], key)
		try:
			buffer = await download_for(dsec, url, default_hours=DEFAULT_CONTENT_HOURS, headers=HEADERS, ctok=lambda ct: ct.startswith("image/"), max_bytes=MAX_IMAGE_BYTES)
		except httpx.HTTPStatusError as bad:
			# its text names the address, which holds the key
			raise refusal(bad.response.status_code) from None
		except (PermanentError, RuntimeError):
			raise
		except Exception as ex:
			logger.error(f"'{self.name}' could not get the map ({type(ex).__name__}).")
			raise RuntimeError(f"'{self.name}' could not get the map ({type(ex).__name__}).") from None
		return buffer.getvalue()
