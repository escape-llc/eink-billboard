"""
Comic Vine as an API data source (`DataSourceApi`): the API key, the series search and the issues of a series with their covers; nothing drawn.

The Comic Vine Covers source (`comic_vine`) asks it with `dsec.use`: the key and the kept answers are this source's settings and files, so every task shares
them and the site's rate limit is spent on new answers only.

Comic Vine takes the key in the address (`api_key=`) and refuses an HTTP client's own User-Agent. The address is hidden in what the HTTP client logs, and a failure
says what happened, never what was asked: the address holds the key.
"""
import logging
import re
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager
from ...plugins.plugin_base import PermanentError
from ..metering import metered_client
from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext
from ..response_cache import cached

API = "https://comicvine.gamespot.com/api"
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "application/json" }
# the most issues one call answers
PAGE = 100
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 20.0
# the cover sizes Comic Vine offers, the one that fits a panel first (`super` is about 480 pixels wide, the original can be several megabytes)
COVER_SIZES = ("super_url", "original_url", "medium_url")
MAX_QUERY = 100
DEFAULT_VOLUME_HOURS = 168.0
DEFAULT_ISSUES_HOURS = 24.0

class HideKey(logging.Filter):
	"""Comic Vine takes the key in the address, and the HTTP client logs addresses: the key is hidden in what it logs."""
	_KEY = re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE)
	def filter(self, record: logging.LogRecord) -> bool:
		try:
			text = record.getMessage()
		except Exception:
			return True
		if "api_key=" in text.lower():
			record.msg, record.args = self._KEY.sub(r"\g<1>***", text), None
		return True

for _name in ("httpx", "httpcore"):
	logging.getLogger(_name).addFilter(HideKey())

logger = logging.getLogger(__name__)

def comicvine_client() -> httpx.AsyncClient:
	return metered_client("comicvine-api", timeout=TIMEOUT, headers=HEADERS, follow_redirects=False)

def stored_api_key(dscm: DatasourceConfigurationManager) -> str:
	_, settings = dscm.open().get()
	key = (settings or {}).get("apiKey")
	if not isinstance(key, str) or not key.strip():
		raise PermanentError("The Comic Vine API key is not set. Add it in the Comic Vine settings.")
	return key.strip()

def api_error(status: int, code: Any = None) -> BaseException:
	"""What an HTTP status or a Comic Vine status code means for the slot, in our own words (never the address, which holds the key)."""
	if status in (401, 403) or code == 100:
		return PermanentError("Comic Vine refused the API key. Check it in the Comic Vine settings.")
	if status in (420, 429) or code == 107:
		return RuntimeError("Comic Vine says too many requests were made (its limit is per hour); it will be tried again.")
	if status == 200 and isinstance(code, int):
		return RuntimeError(f"Comic Vine answered with status code {code}.")
	return RuntimeError(f"Comic Vine answered {status}.")

async def fetch(client: httpx.AsyncClient, path: str, key: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
	"""One call of the API: the JSON object it answers. Failures say what happened and never what was asked."""
	try:
		response = await client.get(f"{API}/{path}/", params={ "api_key": key, "format": "json", **params })
	except httpx.TimeoutException:
		raise RuntimeError("Comic Vine did not answer in time.") from None
	except httpx.HTTPError as ex:
		raise RuntimeError(f"Comic Vine could not be reached ({type(ex).__name__}).") from None
	if len(response.content) > MAX_BYTES:
		raise RuntimeError("Comic Vine's answer is too large.")
	body: Any = None
	try:
		body = response.json()
	except ValueError:
		pass
	code = body.get("status_code") if isinstance(body, dict) else None
	if response.status_code != 200 or (isinstance(code, int) and code != 1):
		raise api_error(response.status_code, code)
	if not isinstance(body, dict):
		raise RuntimeError("Comic Vine's answer is not what was expected.")
	return body

def _text(value: Any, limit: int = 120) -> str:
	return str(value).strip()[:limit] if isinstance(value, (str, int)) else ""

def parse_volume(body: Mapping[str, Any]) -> dict[str, Any]:
	"""The best match of a series search: what is known of it (`issues` is how many issues it has), or a PermanentError when nothing matches."""
	results = [r for r in body.get("results") or [] if isinstance(r, dict) and isinstance(r.get("id"), int)]
	if not results:
		raise PermanentError("Comic Vine has no series that matches the search. Try other words.")
	found = results[0]
	publisher = found.get("publisher")
	issues = found.get("count_of_issues")
	return { "id": found["id"], "name": _text(found.get("name")) or "Untitled", "year": _text(found.get("start_year"), 4),
		"issues": issues if isinstance(issues, int) and issues >= 0 else 0, "publisher": _text(publisher.get("name")) if isinstance(publisher, dict) else "" }

def parse_issues(body: Mapping[str, Any]) -> dict[str, Any]:
	"""One page of a series' issues: the ones with a cover, as `{ number, name, date, cover }` (and how many the series has)."""
	issues = []
	for entry in body.get("results") or []:
		if not isinstance(entry, dict) or not isinstance(entry.get("image"), dict):
			continue
		cover = next((u for u in (entry["image"].get(size) for size in COVER_SIZES) if isinstance(u, str) and u.startswith("https://")), None)
		if cover is None:
			continue
		issues.append({ "number": _text(entry.get("issue_number"), 20), "name": _text(entry.get("name")), "date": _text(entry.get("cover_date"), 10), "cover": cover })
	total = body.get("number_of_total_results")
	return { "total": total if isinstance(total, int) and total >= 0 else len(issues), "issues": issues }

class ComicVineApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)` by `params["request"]`:
	- `volume` (`query`): the series the search matches best, `{ id, name, year, issues, publisher }` (kept for `volumeCacheHours`);
	- `issues` (`volume`, `offset`): one page of up to 100 issues of the series, `{ total, issues: [{ number, name, date, cover }] }` (kept for `issuesCacheHours`).
	A missing key is a PermanentError naming the settings; a refused one too. Every answer comes through this source's kept answers.
	"""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		_, settings = dscm.open().get()
		settings = settings or {}
		key = stored_api_key(dscm)
		request = params.get("request")
		async with comicvine_client() as client:
			if request == "volume":
				query = " ".join(str(params.get("query") or "").split())[:MAX_QUERY]
				if not query:
					raise PermanentError("Enter the series to search for.")
				async def search() -> Mapping[str, Any]:
					return parse_volume(await fetch(client, "search", key, { "query": query, "resources": "volume", "limit": 5 }))
				# the key is not part of what is kept or what it is called: an answer is the same whoever asks
				return await cached(dscm, settings, f"volume|{query.lower()}", dsec.timestamp, search, DEFAULT_VOLUME_HOURS, "volumeCacheHours")
			if request == "issues":
				volume, offset = params.get("volume"), params.get("offset", 0)
				if not isinstance(volume, int) or isinstance(volume, bool) or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
					raise PermanentError("Unknown Comic Vine series.")
				async def listing() -> Mapping[str, Any]:
					return parse_issues(await fetch(client, "issues", key, { "filter": f"volume:{volume}", "limit": PAGE, "offset": offset,
						"field_list": "issue_number,name,cover_date,image" }))
				return await cached(dscm, settings, f"issues|{volume}|{offset}", dsec.timestamp, listing, DEFAULT_ISSUES_HOURS, "issuesCacheHours")
		raise PermanentError(f"Unknown Comic Vine request: {request!r}")
