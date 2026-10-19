"""
A list that outlasts a visit (#222). A plugin that shows the items of a media list (the slide show) can keep what is left of its list between the visits of a slot:
it shows the head, drops it, saves the rest, and only when nothing is left (or the list is older than the task's `refreshHours`) does it open the data source again
for a new list. So a feed shows its stories one after the other instead of the same first ones at every visit, and a folder too large for one visit is shown over many.

The list belongs to the slot (the track) that shows it, in the plugin's own folder, `list-<hash of the track's id>.json`, through its `PluginConfigurationManager`
(an id is not a file name). Nothing else reads it, so there is nothing to share and nobody to wait for: a slot runs one visit at a time. The data source knows nothing
of this; it only says in its descriptor (`keepsList`) that its list is a real one. A source whose list is made fresh every time (the calendar's and the weather's pages
are views of now) is never kept.

The file carries a fingerprint of what the slot shows (the data source and the task's settings that choose the list, and the data source's own settings), so a slot that
was pointed at another feed starts with a new list. Every file records `last_used`, and one unused for the plugin's `staleDays` (a deleted track's) is removed.
A list that cannot be kept (too big, not JSON, a disk that cannot be written) is used from memory: a slide is never lost to the disk.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from ..datasources.keeping import CLOCK_SLACK, DEFAULT_STALE_DAYS, aware, number, parse_moment, prune_stale_sometimes
from ..model.configuration_manager import ConfigurationObject, PluginConfigurationManager
from ..model.migrations import migrate_file

logger = logging.getLogger(__name__)

LIST_PREFIX = "list-"
# a kept list is rewritten whole at every slide: a list too big for that is used for the visit only
MAX_LIST_BYTES = 4_000_000
# the version of a kept list's file (it has no source schema: python/model/schema_versions.py); raised, with a step in `migrate_file`, if its content changes shape
KEPT_LIST_VERSION = 1

class NoItem:
	"""`KeptList.head` has nothing left."""
NO_ITEM = NoItem()

def list_file_name(slot: str) -> str:
	return LIST_PREFIX + hashlib.sha256(slot.encode("utf-8")).hexdigest()[:16]

def fingerprint_of(*parts: Any) -> str:
	return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()

def _read(cob: ConfigurationObject) -> tuple[str|None, dict]:
	"""The kept document, or an empty one when there is none, it cannot be read, or it is not what we wrote: a damaged file is a list that is used up."""
	try:
		rev, doc = cob.get()
	except Exception as e:
		logger.warning(f"A kept list could not be read ({type(e).__name__}); making a new one.")
		return None, {}
	if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
		return rev, {}
	# no source schema: an integer `_version`. One from a newer version is not ours to read (it is replaced by the next list, as a damaged one is)
	doc, _ = migrate_file(doc, KEPT_LIST_VERSION)
	return rev, doc if doc is not None else {}

class KeptList:
	"""The items of a slot's visit: `head()` is the next one and `drop()` takes it off and saves the rest. Never raises for the disk's sake."""
	def __init__(self, items: list[Any], cob: ConfigurationObject|None = None, rev: str|None = None, doc: dict|None = None, now: datetime|None = None, used_up: bool = False):
		self._items = list(items)
		# a visit that was entered again after a stop found the slot's list already used up: there is nothing left to continue (see `open_list`)
		self.used_up = used_up
		self._cob = cob
		self._rev = rev
		self._doc = doc or {}
		self._now = now
	def head(self) -> Any|NoItem:
		return self._items[0] if self._items else NO_ITEM
	def drop(self) -> None:
		if not self._items:
			return
		self._items.pop(0)
		if self._cob is None:
			return
		doc = { **self._doc, "items": self._items, "last_used": (self._now or datetime.now().astimezone()).isoformat() }
		for _ in range(2):
			try:
				ok, rev = self._cob.save(self._rev, doc)
			except Exception as e:
				logger.warning(f"A kept list could not be saved ({type(e).__name__}); carrying on without keeping it.")
				break
			if ok:
				self._rev = rev
				self._doc = doc
				return
			# the file changed under us (an edit by hand): ours is the list, written over what is there
			self._rev, _ = _read(self._cob)
		self._cob = None

def _too_old(doc: dict, now: datetime, max_age: timedelta) -> bool:
	if max_age <= timedelta(0):
		return False
	fetched = parse_moment(doc.get("fetched_at"))
	return fetched is None or now - fetched >= max_age or fetched - now > CLOCK_SLACK

async def open_list(pcm: PluginConfigurationManager|None, slot: str, fingerprint: str, now: datetime, fetch: Callable[[], Awaitable[list]],
		keep: bool, refresh_hours: Any, stale_days: Any, resumed: bool = False) -> KeptList:
	"""
	The list of this visit of `slot`: the kept one when `keep` and it is for the same `fingerprint`, not used up and not older than `refresh_hours`
	(0: only when it is used up), else `await fetch()` (the data source's `open_async`), kept for the next visit. `keep` false is the old way: a new list every time.
	`resumed` (the visit is the same one, entered again after a stop): a list that is for this `fingerprint` and used up is not fetched again, the list comes back
	empty and `used_up`, so the plugin can pass on to the next track; no list kept yet (or another one) is a visit like any other.
	"""
	if not keep or pcm is None:
		return KeptList(await fetch())
	now = aware(now)
	prune_stale_sometimes(pcm, (LIST_PREFIX,), number(stale_days, DEFAULT_STALE_DAYS), now)
	cob = pcm.file(list_file_name(slot))
	rev, doc = _read(cob)
	if resumed and doc.get("fingerprint") == fingerprint and doc.get("items") == []:
		return KeptList([], used_up=True)
	mine = doc.get("fingerprint") == fingerprint and bool(doc.get("items"))
	if mine and not _too_old(doc, now, timedelta(hours=number(refresh_hours, 0))):
		return KeptList(doc["items"], cob, rev, doc, now)
	try:
		items = await fetch()
	except Exception:
		if not mine:
			raise
		# an old list is better than none: the origin is not answering, and what is left is still good
		logger.warning(f"'{slot}' could not get a new list; continuing with the old one.")
		return KeptList(doc["items"], cob, rev, doc, now)
	try:
		too_big = len(json.dumps(items)) > MAX_LIST_BYTES
	except (TypeError, ValueError):
		logger.warning(f"'{slot}' its list cannot be kept (not JSON); using it for this visit only.")
		return KeptList(items)
	if too_big:
		logger.warning(f"'{slot}' its list is too big to keep; using it for this visit only.")
		return KeptList(items)
	if not items:
		return KeptList([])
	fresh = { "_version": KEPT_LIST_VERSION, "fingerprint": fingerprint, "items": items, "fetched_at": now.isoformat(), "last_used": now.isoformat() }
	try:
		ok, saved_rev = cob.save(rev, fresh)
		if not ok:
			rev, _ = _read(cob)
			ok, saved_rev = cob.save(rev, fresh)
	except Exception as e:
		logger.warning(f"A kept list could not be saved ({type(e).__name__}); carrying on without keeping it.")
		return KeptList(items)
	return KeptList(items, cob, saved_rev, fresh, now) if ok else KeptList(items)
