"""
A data source's answers from its origin, kept for a while (#222): the weather's API answer is the same for every slot and every visit for hours, and the free plan counts calls.
The cache is a file of the data source's own folder, `cache-<hash of the key>.json`, through its `DatasourceConfigurationManager`, and it belongs to the data source as a
whole (its settings, not a task's): every task and every data source that asks for the same thing shares one answer.

`cached(...)` is called from several threads at once (the playlist and the timer layers each have their own): one task at a time goes to the origin for a given answer,
the others wait for it. An answer older than `hours` is fetched again; when the origin does not answer, the old one is used (unless it is a `PermanentError`: a refused
key is never hidden). A cache that cannot be read or written is no cache: the answer comes from the origin as if there were none. Files unused for `staleDays` are removed
(keeping.prune_stale_sometimes).
"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Mapping

from ..model.configuration_manager import DatasourceConfigurationManager
from ..plugins.plugin_base import PermanentError
from .metering import METER
from .keeping import DEFAULT_STALE_DAYS, CLOCK_SLACK, REFILL_WAIT_SECONDS, aware, number, parse_moment, prune_stale_sometimes, refill_lock

logger = logging.getLogger(__name__)

CACHE_PREFIX = "cache-"
MAX_CACHE_BYTES = 4_000_000

def cache_file_name(key: str) -> str:
	return CACHE_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

def _fresh(doc: Mapping[str, Any], now: datetime, ttl: timedelta) -> bool:
	fetched = parse_moment(doc.get("fetched_at"))
	if fetched is None or "data" not in doc:
		return False
	age = now - fetched
	# "fetched" after now: the clock was set back, and the answer is only as good as the slack allows
	return -age <= CLOCK_SLACK if age < timedelta(0) else age < ttl

async def cached(dscm: DatasourceConfigurationManager, settings: Mapping[str, Any], key: str, now: datetime,
		fetch: Callable[[], Awaitable[Mapping[str, Any]]], default_hours: float = 0.0, setting: str = "cacheHours") -> Mapping[str, Any]:
	"""
	The answer for `key`: the kept one if it is younger than the data source's `setting` (`cacheHours`; a source with several kinds of answer has one setting for each,
	as the Weather's current and forecast), else `fetch()`'s (and kept).
	"""
	now = aware(now)
	hours = number(settings.get(setting), default_hours)
	source = dscm.datasource_id
	if hours <= 0:
		METER.cache(source, "bypass", 0)
		return await fetch()
	ttl = timedelta(hours=hours)
	waited = False
	prune_stale_sometimes(dscm, (CACHE_PREFIX,), number(settings.get("staleDays"), DEFAULT_STALE_DAYS), now)
	cob = dscm.file(cache_file_name(key))
	for _ in range(5):
		try:
			rev, doc = cob.get()
		except Exception:
			rev, doc = None, None
		doc = doc if isinstance(doc, dict) else {}
		if _fresh(doc, now, ttl):
			note_use(cob, rev, doc, now)
			# an answer another task fetched while we waited for it is not a hit of the cache's: it saved a call all the same, and the two are told apart
			METER.cache(source, "coalesced" if waited else "hit", _size(doc))
			return doc["data"]
		lock = refill_lock(cob.moniker)
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
			try:
				data = await fetch()
			except PermanentError:
				raise
			except Exception as e:
				if isinstance(doc.get("data"), dict):
					logger.warning(f"'{dscm.datasource_id}' could not get a new answer ({type(e).__name__}); using the old one.")
					METER.cache(source, "stale", _size(doc))
					return doc["data"]
				raise
			size = 0
			try:
				size = len(json.dumps(data))
				if size <= MAX_CACHE_BYTES:
					save_quietly(cob, rev, { "data": data, "fetched_at": now.isoformat(), "last_used": now.isoformat(), "size": size })
			except (TypeError, ValueError):
				pass
			METER.cache(source, "miss", size)
			return data
		finally:
			lock.release()
	# the answer kept changing under us: ask the origin and leave the cache alone
	return await fetch()

def _size(doc: Mapping[str, Any]) -> int:
	"""The size of a kept answer, as it was written when it was kept (an older file has none: its bytes are not counted)."""
	size = doc.get("size")
	return size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else 0

def save_quietly(cob: Any, rev: str|None, doc: dict) -> None:
	try:
		cob.save(rev, doc)
	except Exception as e:
		logger.warning(f"A cached answer could not be saved ({type(e).__name__}); carrying on without it.")

def note_use(cob: Any, rev: str|None, doc: dict, now: datetime) -> None:
	"""Note that the answer was used (the clean-up goes by it); not worth failing for, nor for losing a race."""
	last = parse_moment(doc.get("last_used"))
	if last is not None and now - last < timedelta(hours=1):
		return
	save_quietly(cob, rev, { **doc, "last_used": now.isoformat() })
