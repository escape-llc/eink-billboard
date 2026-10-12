"""
A list that outlasts a visit (#222). A media-list data source (an RSS feed, an image folder) can keep what is left of its list between visits of a slot:
each slide takes the head of the list and saves the rest, and only when nothing is left (or the list is older than the data source's `refreshHours`) does
the data source go back to its origin for a new list. So the same source can appear in several slots, which pull from one list, and a folder too large for
one slot is spread over many.

A data source takes part by having `list_state_key(dsec, params)`: the identity of its list as a string (the feed's name and address, the folder's name
and path), or None for no state. A source whose list is made fresh every time (the calendar's and the weather's pages are views of now) has no such method,
and is never kept. The data source's settings choose: `listMode` (`continue` or `restart`, which is how it was), `refreshHours` and `staleDays`.

The state is a file of the data source's own folder, `state-<hash of the key>.json`, through its `DatasourceConfigurationManager` (the key can hold an address,
so the file name is only a hash). A reconfigured source has another key, so its old state is not found; every file records when it was last used, and a file
unused for `staleDays` is removed.
"""
import asyncio
import hashlib
import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol, runtime_checkable

from ..model.configuration_manager import ConfigurationObject, DatasourceConfigurationManager
from .data_source import DataSourceExecutionContext, MediaListAsync

logger = logging.getLogger(__name__)

STATE_PREFIX = "state-"
DEFAULT_MODE = "continue"
DEFAULT_STALE_DAYS = 30
# at most once an hour per data source: the clean-up reads every state file
PRUNE_EVERY_SECONDS = 3600.0
TRIES = 5
# taking an item is a read and a save that another task can get in between: it is tried again, after a short random wait, this many times
CLAIM_TRIES = 60
# a kept list is rewritten whole at every slide: a list too big for that is used for the visit only
MAX_STATE_BYTES = 4_000_000
# a list "fetched" after now (the clock was set back) is as good as old
CLOCK_SLACK = timedelta(hours=1)

@runtime_checkable
class ListStateKey(Protocol):
	"""
	A media-list data source that can keep what is left of its list: the identity of the list it would return for these settings (None: not kept).
	Like `open_async` it can be called at the same time from several threads (the playlist and the timer layers each have their own): a data source keeps no
	mutable state on itself, or guards it.
	"""
	def list_state_key(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> str|None:
		...

def state_file_name(key: str) -> str:
	return STATE_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

def aware(moment: datetime) -> datetime:
	return moment if moment.tzinfo is not None else moment.astimezone()

def parse_moment(text: Any) -> datetime|None:
	try:
		return aware(datetime.fromisoformat(text)) if isinstance(text, str) else None
	except ValueError:
		return None

def number(value: Any, default: float) -> float:
	"""A setting that is a number of zero or more; anything else is the default."""
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else default

_last_prune: dict[str, float] = {}
_prune_lock = threading.Lock()
# one refill at a time per list: the playlist and the timer layers run on their own threads, and two slots that find a list used up at once should fetch it once
_refill_locks: dict[str, threading.Lock] = {}
_refill_locks_guard = threading.Lock()
REFILL_WAIT_SECONDS = 120.0

def refill_lock(name: str) -> threading.Lock:
	with _refill_locks_guard:
		return _refill_locks.setdefault(name, threading.Lock())

def prune_stale(dscm: DatasourceConfigurationManager, prefixes: tuple[str, ...], stale_days: float, now: datetime) -> list[str]:
	"""Remove the data source's files (`state-...`, `cache-...`) not used for `stale_days` days (0: never). Returns the names removed."""
	if stale_days <= 0:
		return []
	removed: list[str] = []
	limit = aware(now) - timedelta(days=stale_days)
	for prefix in prefixes:
		for name in dscm.list_files(prefix):
			_, doc = dscm.file(name).get()
			used = parse_moment((doc or {}).get("last_used"))
			# a file that cannot say when it was used is as old as it can be
			if used is None or used < limit:
				dscm.delete_file(name)
				removed.append(name)
	if removed:
		logger.info(f"'{dscm.datasource_id}' removed {len(removed)} unused file(s).")
	return removed

def prune_stale_sometimes(dscm: DatasourceConfigurationManager, prefixes: tuple[str, ...], stale_days: float, now: datetime) -> None:
	with _prune_lock:
		last = _last_prune.get(dscm.datasource_id)
		if last is not None and time.monotonic() - last < PRUNE_EVERY_SECONDS:
			return
		_last_prune[dscm.datasource_id] = time.monotonic()
	try:
		prune_stale(dscm, prefixes, stale_days, now)
	except Exception as e:
		# a clean-up is never worth a slide
		logger.warning(f"'{dscm.datasource_id}' could not remove its unused files ({type(e).__name__}).")

class NoItem:
	"""`ListCursor.next` has nothing left."""
NO_ITEM = NoItem()

class ListCursor:
	"""The items of one visit: `next()` is the next item of the list, or NO_ITEM."""
	async def next(self) -> Any|NoItem:
		raise NotImplementedError

class LocalCursor(ListCursor):
	"""The list as a visit has always had it: fetched now, thrown away after."""
	def __init__(self, items: list[Any]):
		self._items = list(items)
	async def next(self) -> Any|NoItem:
		return self._items.pop(0) if self._items else NO_ITEM

def _read(cob: ConfigurationObject) -> tuple[str|None, dict]:
	"""The kept list's document, or an empty one when there is none, it cannot be read, or it is not what we wrote: a damaged file is a list that is used up."""
	try:
		rev, doc = cob.get()
	except Exception as e:
		logger.warning(f"A kept list could not be read ({type(e).__name__}); making a new one.")
		return None, {}
	if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
		return rev, {}
	return rev, doc

def _save(cob: ConfigurationObject, rev: str|None, doc: dict) -> bool|None:
	"""True when saved, False when the file had changed (try again), None when it cannot be written at all (a full or read-only disk: carry on without keeping the list)."""
	try:
		return cob.save(rev, doc)[0]
	except Exception as e:
		logger.warning(f"A kept list could not be saved ({type(e).__name__}); carrying on without keeping it.")
		return None

class StateCursor(ListCursor):
	"""The list kept in a file: `next()` takes the head and saves the rest, safe against another slot doing the same (a save over a changed file is refused and tried again).
	When the file cannot be written the rest of the list is used from memory, so a slide is never lost to the disk."""
	def __init__(self, cob: ConfigurationObject, now: datetime):
		self._cob = cob
		self._now = now
		self._memory: LocalCursor|None = None
	async def next(self) -> Any|NoItem:
		if self._memory is not None:
			return await self._memory.next()
		for attempt in range(CLAIM_TRIES):
			rev, doc = _read(self._cob)
			items = list(doc.get("items") or [])
			if not items:
				return NO_ITEM
			saved = _save(self._cob, rev, { **doc, "items": items[1:], "last_used": self._now.isoformat() })
			if saved:
				return items[0]
			if saved is None:
				self._memory = LocalCursor(items[1:])
				return items[0]
			# the file changed under us: wait a moment (a different one for each task, so they do not collide again) and look again
			await asyncio.sleep(random.uniform(0, 0.002 * (attempt + 1)))
		# somebody else keeps taking from it faster than we can: this visit is over
		logger.warning("A kept list is in use by another task; ending this visit.")
		return NO_ITEM

def _too_old(doc: dict, now: datetime, max_age: timedelta) -> bool:
	if max_age <= timedelta(0):
		return False
	fetched = parse_moment(doc.get("fetched_at"))
	return fetched is None or now - fetched >= max_age or fetched - now > CLOCK_SLACK

async def open_cursor(dsec: DataSourceExecutionContext, source: MediaListAsync, params: Mapping[str, Any]) -> ListCursor:
	"""The items of a visit of a slot: from the kept list when the source keeps one and the data source's settings say `continue`, else a new list as before."""
	key = source.list_state_key(dsec, params) if isinstance(source, ListStateKey) else None
	if key is None:
		return LocalCursor(await source.open_async(dsec, params))
	dscm = dsec.provider.get_service(DatasourceConfigurationManager)
	_, settings = dscm.open().get() if dscm is not None else (None, None)
	settings = settings if isinstance(settings, dict) else {}
	if dscm is None or settings.get("listMode", DEFAULT_MODE) != "continue":
		return LocalCursor(await source.open_async(dsec, params))
	now = aware(dsec.timestamp)
	prune_stale_sometimes(dscm, (STATE_PREFIX,), number(settings.get("staleDays"), DEFAULT_STALE_DAYS), now)
	cob = dscm.file(state_file_name(key))
	max_age = timedelta(hours=number(settings.get("refreshHours"), 0))
	for _ in range(TRIES):
		rev, doc = _read(cob)
		empty = not doc.get("items")
		if not empty and not _too_old(doc, now, max_age):
			return StateCursor(cob, now)
		# the list is used up (or too old): back to the origin. One task at a time does that; the others wait for its list (without holding up their loop)
		lock = refill_lock(cob.moniker)
		if not lock.acquire(blocking=False):
			deadline = time.monotonic() + REFILL_WAIT_SECONDS
			while time.monotonic() < deadline:
				await asyncio.sleep(0.05)
				if lock.acquire(blocking=False):
					lock.release()
					break
			continue
		try:
			items = await source.open_async(dsec, params)
		except Exception:
			if empty:
				raise
			# an old list is better than none: the origin is not answering, and what is left is still good
			logger.warning(f"'{dscm.datasource_id}' could not get a new list; continuing with the old one.")
			return StateCursor(cob, now)
		finally:
			lock.release()
		try:
			too_big = len(json.dumps(items)) > MAX_STATE_BYTES
		except (TypeError, ValueError):
			logger.warning(f"'{dscm.datasource_id}' its list cannot be kept (not JSON); using it for this visit only.")
			return LocalCursor(items)
		if too_big:
			logger.warning(f"'{dscm.datasource_id}' its list is too big to keep; using it for this visit only.")
			return LocalCursor(items)
		if not items:
			return LocalCursor([])
		saved = _save(cob, rev, { "items": items, "fetched_at": now.isoformat(), "last_used": now.isoformat() })
		if saved:
			return StateCursor(cob, now)
		if saved is None:
			return LocalCursor(items)
		# another slot made a new list first: use that one
	return StateCursor(cob, now)
