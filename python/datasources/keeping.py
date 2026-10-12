"""
Files a data source or a plugin keeps for a while (#222): a data source's answers from its origin (`response_cache.py`) and the lists a plugin keeps for a slot
(`plugins/kept_list.py`). What they share is here: reading a moment or a setting that may be wrong, the one-at-a-time lock, and the clean-up of files nobody uses
(every file records `last_used`; a file unused for `staleDays` is removed).
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from ..model.configuration_manager import DatasourceConfigurationManager, PluginConfigurationManager

logger = logging.getLogger(__name__)

DEFAULT_STALE_DAYS = 30
# at most once an hour per owner: the clean-up reads every file
PRUNE_EVERY_SECONDS = 3600.0
# a kept file dated after now (the clock was set back) is as good as old
CLOCK_SLACK = timedelta(hours=1)

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
# one question to the origin at a time per answer: the playlist and the timer layers run on their own threads
_refill_locks: dict[str, threading.Lock] = {}
_refill_locks_guard = threading.Lock()
REFILL_WAIT_SECONDS = 120.0

def refill_lock(name: str) -> threading.Lock:
	with _refill_locks_guard:
		return _refill_locks.setdefault(name, threading.Lock())

def owner_id(manager: DatasourceConfigurationManager|PluginConfigurationManager) -> str:
	return manager.datasource_id if isinstance(manager, DatasourceConfigurationManager) else manager.plugin_id

def prune_key(manager: DatasourceConfigurationManager|PluginConfigurationManager) -> str:
	return f"{type(manager).__name__}:{owner_id(manager)}"

def prune_stale(dscm: DatasourceConfigurationManager|PluginConfigurationManager, prefixes: tuple[str, ...], stale_days: float, now: datetime) -> list[str]:
	"""Remove the data source's or plugin's files (`state-...`, `cache-...`) not used for `stale_days` days (0: never). Returns the names removed."""
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
		logger.info(f"'{owner_id(dscm)}' removed {len(removed)} unused file(s).")
	return removed

def prune_stale_sometimes(dscm: DatasourceConfigurationManager|PluginConfigurationManager, prefixes: tuple[str, ...], stale_days: float, now: datetime) -> None:
	with _prune_lock:
		last = _last_prune.get(prune_key(dscm))
		if last is not None and time.monotonic() - last < PRUNE_EVERY_SECONDS:
			return
		_last_prune[prune_key(dscm)] = time.monotonic()
	try:
		prune_stale(dscm, prefixes, stale_days, now)
	except Exception as e:
		# a clean-up is never worth a slide
		logger.warning(f"'{owner_id(dscm)}' could not remove its unused files ({type(e).__name__}).")
