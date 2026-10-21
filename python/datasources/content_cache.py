"""
A data source's downloads (pictures, feeds), kept for a while (#400). Like `response_cache.py` it belongs to the data source as a whole: every task and every address under that
data source shares one pool, in the source's own folder, through its `DatasourceConfigurationManager` (`blob-<hash of the address>.json` describes the download, `.bin` is its bytes).

How long a download is trusted comes from the origin: `Cache-Control` (`max-age`, `no-cache`, `no-store`) and `Expires`, never longer than the data source's `contentCacheHours`, which is also
the time used when the origin says nothing. While a download is fresh it is read from disk and **nothing is sent**: no HEAD, no conditional request. When it has expired the next use asks
again with the `ETag` and `Last-Modified` the origin gave (`If-None-Match`, `If-Modified-Since`): a 304 keeps the bytes and starts a new fresh period, a 200 replaces them. An origin that does
not answer gives the old bytes (an address the URL guard refuses never does: that is the user's to fix). 0 hours keeps nothing.

The pool is bounded: `contentCacheMB` (oldest use first), and files unused for `staleDays` are removed. A source that loads a list (a feed's stories) tells the cache which addresses
the list still holds (`retain`), so what dropped out of the feed goes at once and nothing needs a timer.

`fetch_cached` is called from several threads at once (the playlist and the timer layers each have their own): one at a time asks the origin for an address, the others wait for it. A cache
that cannot be read or written is no cache: the download comes from the origin as if there were none.
"""
import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any, Callable, Mapping

from httpx import AsyncClient

from ..model.configuration_manager import DatasourceConfigurationManager
from ..model.time_of_day import TimeOfDay
from ..task.async_http_worker_pool import client_var
from ..plugins.plugin_base import PermanentError
from ..task.message_router import MessageRouter
from ..task.messages import Telemetry
from ..utils.image_utils import DEFAULT_MAX_DOWNLOAD_BYTES, download, stream_to_buffer
from ..utils.url_guard import UrlRefused
from .data_source import DataSourceExecutionContext
from .metering import METER, metered_as
from .keeping import DEFAULT_STALE_DAYS, CLOCK_SLACK, REFILL_WAIT_SECONDS, aware, number, parse_moment, prune_stale_sometimes, refill_lock
from .response_cache import note_use, save_quietly

logger = logging.getLogger(__name__)

BLOB_PREFIX = "blob-"
Reporter = Callable[[str, int], None]
DEFAULT_CACHE_MB = 64.0

def blob_name(url: str) -> str:
	"""What a download is called on disk: a hash, so the address (which can carry a key) is not in a file name or in the file."""
	return BLOB_PREFIX + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]

@dataclass(frozen=True)
class Freshness:
	"""What the origin's headers say about keeping a download: `keep` False for `no-store`, else how long it is trusted without asking."""
	keep: bool
	lifetime: timedelta

def freshness(headers: Mapping[str, str], now: datetime, ceiling: timedelta) -> Freshness:
	"""`Cache-Control` first, then `Expires`; an origin that says nothing (or something unreadable) gets the ceiling. Never longer than the ceiling, never negative."""
	lowered = { k.lower(): v for k, v in headers.items() }
	directives: dict[str, str] = {}
	for part in lowered.get("cache-control", "").split(","):
		name, _, value = part.strip().partition("=")
		if name:
			directives[name.lower()] = value.strip().strip('"')
	if "no-store" in directives:
		return Freshness(False, timedelta(0))
	if "no-cache" in directives:
		return Freshness(True, timedelta(0))
	life: timedelta|None = None
	if "max-age" in directives:
		try:
			age = int(lowered.get("age", "0") or 0)
		except ValueError:
			age = 0
		try:
			life = timedelta(seconds=int(directives["max-age"]) - max(0, age))
		except (ValueError, OverflowError):
			life = None
	elif "expires" in lowered:
		try:
			expires = aware(parsedate_to_datetime(lowered["expires"]))
			try:
				sent = aware(parsedate_to_datetime(lowered["date"])) if "date" in lowered else now
			except (TypeError, ValueError):
				sent = now
			life = expires - sent
		except (TypeError, ValueError, OverflowError):
			# "Expires: 0" and the like mean already expired
			life = timedelta(0)
	if life is None:
		life = ceiling
	return Freshness(True, max(timedelta(0), min(life, ceiling)))

def _read(dscm: DatasourceConfigurationManager, name: str) -> tuple[Any, str|None, dict, bytes|None]:
	"""The description and bytes kept under `name`; the bytes only when they are the size the description says (a half-written pair is a miss)."""
	cob = dscm.file(name)
	try:
		rev, doc = cob.get()
	except Exception:
		rev, doc = None, None
	doc = doc if isinstance(doc, dict) else {}
	body = dscm.read_blob(name) if isinstance(doc.get("size"), int) else None
	if body is not None and len(body) != doc.get("size"):
		body = None
	return cob, rev, doc, body

def _is_fresh(doc: Mapping[str, Any], now: datetime) -> bool:
	until, fetched = parse_moment(doc.get("fresh_until")), parse_moment(doc.get("fetched_at"))
	if until is None or fetched is None:
		return False
	# fetched after now: the clock was set back, and the download is only as good as the slack allows
	if fetched - now > CLOCK_SLACK:
		return False
	return now < until

def _validators(doc: Mapping[str, Any]) -> dict[str, str]:
	found: dict[str, str] = {}
	if isinstance(doc.get("etag"), str) and doc["etag"]:
		found["If-None-Match"] = doc["etag"]
	if isinstance(doc.get("last_modified"), str) and doc["last_modified"]:
		found["If-Modified-Since"] = doc["last_modified"]
	return found

async def fetch_cached(dscm: DatasourceConfigurationManager, settings: Mapping[str, Any], client: AsyncClient, url: str, now: datetime, *,
		headers: Mapping[str, str]|None = None, ctok: Callable[[str], bool]|None = None, max_bytes: int|None = DEFAULT_MAX_DOWNLOAD_BYTES, guarded: bool = True,
		default_hours: float = 0.0, scope: str = "", setting: str = "contentCacheHours", report: Reporter|None = None) -> BytesIO:
	"""
	The bytes at `url`: the kept ones while they are fresh (nothing is sent), else what the origin answers (kept, unless it says `no-store`).
	`default_hours` is the data source's own default for its `setting` (0 keeps nothing); `scope` names the list the address belongs to (`retain`).
	`report(outcome, size)` is told what happened: `hit` (read from disk, nothing sent), `revalidated` (asked, 304), `miss` (downloaded), `stale` (the origin did not answer, the old bytes were used), `bypass` (kept nothing: 0 hours, or `no-store`).
	"""
	source = dscm.datasource_id
	waited = False
	def tell(outcome: str, size: int) -> None:
		# the meter tells a download another task made while we waited for it from a hit of the cache's; the web app's report does not
		METER.cache(source, "coalesced" if outcome == "hit" and waited else outcome, size)
		if report is not None:
			report(outcome, size)
	now = aware(now)
	hours = number(settings.get(setting), default_hours)
	if hours <= 0:
		plain = (await download(client, url, headers, ctok, max_bytes, guarded)).body or BytesIO()
		tell("bypass", plain.getbuffer().nbytes)
		return plain
	ceiling = timedelta(hours=hours)
	prune_stale_sometimes(dscm, (BLOB_PREFIX,), number(settings.get("staleDays"), DEFAULT_STALE_DAYS), now, dscm.delete_blob)
	name = blob_name(url)
	for _ in range(5):
		cob, rev, doc, body = _read(dscm, name)
		if body is not None and _is_fresh(doc, now):
			note_use(cob, rev, doc, now)
			tell("hit", len(body))
			return BytesIO(body)
		lock = refill_lock(f"{dscm.datasource_id}:{name}")
		if not lock.acquire(blocking=False):
			# another task is asking the origin for this: wait for its answer without holding up our loop
			waited = True
			deadline = time.monotonic() + REFILL_WAIT_SECONDS
			while time.monotonic() < deadline:
				await asyncio.sleep(0.05)
				if lock.acquire(blocking=False):
					lock.release()
					break
			continue
		try:
			sent = dict(headers or {})
			asking = _validators(doc) if body is not None else {}
			sent.update(asking)
			try:
				got = await download(client, url, sent, ctok, max_bytes, guarded, conditional=bool(asking))
			except (PermanentError, UrlRefused):
				raise
			except Exception as e:
				if body is not None:
					logger.warning(f"'{dscm.datasource_id}' could not refresh a kept download ({type(e).__name__}); using the old one.")
					tell("stale", len(body))
					return BytesIO(body)
				raise
			if got.status == 304 and body is not None:
				fresh = freshness(got.headers, now, ceiling)
				keep = { **doc, "fetched_at": now.isoformat(), "fresh_until": (now + fresh.lifetime).isoformat(), "last_used": now.isoformat() }
				for key, header in (("etag", "etag"), ("last_modified", "last-modified")):
					value = { k.lower(): v for k, v in got.headers.items() }.get(header)
					if value:
						keep[key] = value
				save_quietly(cob, rev, keep)
				tell("revalidated", len(body))
				return BytesIO(body)
			assert got.body is not None
			data = got.body.getvalue()
			kept = _keep(dscm, name, rev, data, got.headers, now, ceiling, scope, number(settings.get("contentCacheMB"), DEFAULT_CACHE_MB))
			tell("miss" if kept else "bypass", len(data))
			return BytesIO(data)
		finally:
			lock.release()
	# what was kept kept changing under us: ask the origin and leave the cache alone
	return (await download(client, url, headers, ctok, max_bytes, guarded)).body or BytesIO()

def _keep(dscm: DatasourceConfigurationManager, name: str, rev: str|None, data: bytes, headers: Mapping[str, str], now: datetime, ceiling: timedelta, scope: str, cap_mb: float) -> bool:
	"""Keep the download; False when it was not kept (`no-store`, bigger than the pool, or the disk said no)."""
	fresh = freshness(headers, now, ceiling)
	cap = int(cap_mb * 1024 * 1024)
	if not fresh.keep or len(data) > cap:
		return False
	lowered = { k.lower(): v for k, v in headers.items() }
	doc = { "scope": scope, "size": len(data), "fetched_at": now.isoformat(), "fresh_until": (now + fresh.lifetime).isoformat(), "last_used": now.isoformat(),
		"etag": lowered.get("etag"), "last_modified": lowered.get("last-modified"), "content_type": lowered.get("content-type") }
	try:
		# the description first: a description without its bytes is a miss, bytes without a description would be nobody's
		dscm.file(name).save(rev, doc)
		dscm.write_blob(name, data)
	except Exception as e:
		logger.warning(f"A download could not be kept ({type(e).__name__}); carrying on without it.")
		try:
			dscm.delete_blob(name)
		except Exception:
			pass
		return False
	_enforce_cap(dscm, name, cap)
	return True

def _enforce_cap(dscm: DatasourceConfigurationManager, just_kept: str, cap: int) -> None:
	"""The pool is no bigger than `cap` bytes: the one used longest ago goes first, never the one just kept."""
	try:
		kept = []
		for name in dscm.list_files(BLOB_PREFIX):
			_, doc = dscm.file(name).get()
			doc = doc if isinstance(doc, dict) else {}
			size: int = doc["size"] if isinstance(doc.get("size"), int) else 0
			kept.append((parse_moment(doc.get("last_used")) or datetime.min.replace(tzinfo=aware(datetime.now()).tzinfo), name, size))
		total = sum(size for _, _, size in kept)
		for _, name, size in sorted(kept):
			if total <= cap:
				break
			if name == just_kept:
				continue
			dscm.delete_blob(name)
			total -= size
	except Exception as e:
		logger.warning(f"A download pool could not be trimmed ({type(e).__name__}).")

def retain(dscm: DatasourceConfigurationManager, scope: str, urls: list[str]) -> int:
	"""
	A list of `scope` was just loaded and holds `urls`: what was kept for that scope and is not in it any more is removed. Other scopes (another feed of the same data source) are not touched.
	Returns how many were removed. Never fails: a clean-up is not worth a slide.
	"""
	removed = 0
	try:
		wanted = { blob_name(u) for u in urls }
		for name in dscm.list_files(BLOB_PREFIX):
			_, doc = dscm.file(name).get()
			if isinstance(doc, dict) and doc.get("scope") == scope and name not in wanted:
				dscm.delete_blob(name)
				removed += 1
	except Exception as e:
		logger.warning(f"'{dscm.datasource_id}' could not clean up its kept downloads ({type(e).__name__}).")
	return removed

async def download_for(dsec: DataSourceExecutionContext, url: str, *, default_hours: float, headers: Mapping[str, str]|None = None, ctok: Callable[[str], bool]|None = None,
		max_bytes: int|None = DEFAULT_MAX_DOWNLOAD_BYTES, scope: str = "", setting: str = "contentCacheHours", client: AsyncClient|None = None) -> BytesIO:
	"""
	`setting` names the setting that holds the time (a data source with feeds and pictures keeps each for its own time).
	`client` is the HTTP client to ask with: an API data source passes its metered one (`metered_client`, #440), so the call counts against its service; else the pool's.
	What a data source calls to download a picture or a feed from its own context: kept in the data source's own pool (`fetch_cached`) with the data source's settings, or
	downloaded and forgotten when the context has no data source folder (a test's, a tool's). The address goes through the URL guard either way.
	"""
	client = client if client is not None else client_var.get()
	dscm = dsec.provider.get_service(DatasourceConfigurationManager)
	# a context without the data source's folder (a test's stand-in, a tool's) downloads and keeps nothing
	if not isinstance(dscm, DatasourceConfigurationManager):
		return await stream_to_buffer(client, url, headers, ctok, max_bytes)
	_, settings = dscm.open().get()
	# the pool's client belongs to no data source: its calls are counted under this one while it downloads (a client of the data source's own counts under its own)
	with metered_as(dscm.datasource_id):
		return await fetch_cached(dscm, settings or {}, client, url, dsec.timestamp, headers=headers, ctok=ctok, max_bytes=max_bytes, default_hours=default_hours, scope=scope, setting=setting,
			report=_telemetry(dsec, dscm.datasource_id))

def _telemetry(dsec: DataSourceExecutionContext, source_id: str) -> Reporter:
	"""
	What a download tells the web app (`cache-<outcome>`): the data source and the size, never the address (it can carry a key). Said with the time it happens,
	not the slot's, on the device's clock (`TimeOfDay`: the device's zone), as every other event is: the process's own zone is UTC in a container.
	"""
	router = dsec.provider.get_service(MessageRouter)
	clock = dsec.provider.get_service(TimeOfDay)
	def tell(outcome: str, size: int) -> None:
		if router is None:
			return
		try:
			now = clock.current_time() if clock is not None else datetime.now().astimezone()
			router.send("telemetry", Telemetry(now, "data-source", { "kind": f"cache-{outcome}", "datasource": source_id, "bytes": size,
				"message": CACHE_WORDS[outcome].format(source=source_id, size=_kb(size)) }))
		except Exception as e:
			logger.warning(f"A cache event could not be sent ({type(e).__name__}).")
	return tell

CACHE_WORDS = {
	"hit": "'{source}' used a kept download ({size}); nothing was sent.",
	"revalidated": "'{source}' asked, and its kept download ({size}) is still good.",
	"miss": "'{source}' downloaded and kept {size}.",
	"stale": "'{source}' could not be reached; it used its old download ({size}).",
	"bypass": "'{source}' downloaded {size} and kept nothing.",
}

def _kb(size: int) -> str:
	return f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} bytes"
