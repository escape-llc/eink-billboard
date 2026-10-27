"""
API metering (#440): what each API data source asks of its service, counted so a quota is something you can see before it runs out.

Per data source (by its declared id) and per day, counts only, never an address, a key, a query or a body:
- the network calls sent, by exact HTTP status code, and the ones that got no status (`timeout`, `connect`, `tls`, `error`);
- the bytes of the bodies sent and received (as they went over the wire: compressed, if the origin compressed them; headers are not counted);
- the cache outcomes (`hit`, `miss`, `stale`, `coalesced`, `revalidated`, `bypass`, from `cached` and `fetch_cached`) and the bytes they answered, so the cache's benefit is a number.

An API data source makes its HTTP client with `metered_client(source_id, ...)`, which counts every call (a redirect's hops each count: each is a request the service sees; the OpenAI SDK's retries too).
`test_api_metering` fails for an API data source that makes a client any other way.

The counts live in memory behind a lock (a data source is called from several threads) and are written to the storage's `state/api-usage.json` about once a minute by a thread of their own, and on quit:
never per call (a Pi's SD card). A crash loses at most the last minute. A file that cannot be read or written is no history, and never stops a call.
"""
import contextlib
import logging
import ssl
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator, Mapping

import httpx

from ..model.migrations import migrate_file
from ..model.schema_versions import stamped
from ..task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context

logger = logging.getLogger(__name__)

# the version of the file (it has no source schema to take one from: python/model/schema_versions.py); raised, with a step in `migrate_file`, if its content changes shape
USAGE_VERSION = 1
STATE_NAME = "api-usage"
KEEP_DAYS = 31
FLUSH_SECONDS = 60.0

# a cache lookup is answered without a download when it is one of these
ANSWERED = ("hit", "coalesced", "revalidated")
# ... and these are the lookups there were (a `bypass` is a cache that was off)
LOOKUPS = ("hit", "coalesced", "revalidated", "miss", "stale")

def _bucket() -> dict[str, Any]:
	return { "calls": 0, "status": {}, "sent": 0, "received": 0, "cache": {}, "cacheBytes": {} }

def _bump(counts: dict[str, int], key: str, amount: int = 1) -> None:
	counts[key] = counts.get(key, 0) + amount

def _count(value: Any) -> int:
	return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

def _clean_counts(value: Any) -> dict[str, int]:
	return { str(k): _count(v) for k, v in value.items() if _count(v) } if isinstance(value, dict) else {}

def _clean_bucket(value: Any) -> dict[str, Any]:
	value = value if isinstance(value, dict) else {}
	return { "calls": _count(value.get("calls")), "status": _clean_counts(value.get("status")), "sent": _count(value.get("sent")), "received": _count(value.get("received")),
		"cache": _clean_counts(value.get("cache")), "cacheBytes": _clean_counts(value.get("cacheBytes")) }

class UsageMeter:
	"""The counters. One process-wide instance (`METER`); a test makes its own."""
	def __init__(self, clock: Callable[[], datetime]|None = None):
		self._clock = clock or (lambda: datetime.now().astimezone())
		self._lock = threading.Lock()
		# source id -> { "days": { "YYYY-MM-DD": bucket }, "lastLimited": ISO moment|None }
		self._sources: dict[str, dict[str, Any]] = {}
		self._cm: Any = None
		self._dirty = False
		self._stop = threading.Event()
		self._thread: threading.Thread|None = None

	# --- counting

	def _today(self, source: str) -> dict[str, Any]:
		now = self._clock()
		entry = self._sources.setdefault(source, { "days": {}, "lastLimited": None })
		self._dirty = True
		return entry["days"].setdefault(now.date().isoformat(), _bucket())

	def call(self, source: str, status: int|None, failure: str|None, sent: int, received: int) -> None:
		"""A call that went to the service: `status` is its HTTP status, or None and `failure` says why there was none."""
		with self._lock:
			day = self._today(source)
			day["calls"] += 1
			_bump(day["status"], str(status) if status is not None else (failure or "error"))
			day["sent"] += max(0, sent)
			day["received"] += max(0, received)
			if status == 429:
				self._sources[source]["lastLimited"] = self._clock().isoformat()

	def received(self, source: str, size: int) -> None:
		"""The body of a streamed answer, counted when it was closed."""
		with self._lock:
			self._today(source)["received"] += max(0, size)

	def cache(self, source: str, outcome: str, size: int) -> None:
		with self._lock:
			day = self._today(source)
			_bump(day["cache"], outcome)
			_bump(day["cacheBytes"], outcome, max(0, size))

	# --- keeping

	def attach(self, cm: Any, clock: Callable[[], datetime]|None = None) -> None:
		"""Keep the counts in `cm`'s state folder from now on: what was counted before the start is read, what is counted now is added, and a thread writes it."""
		if clock is not None:
			self._clock = clock
		with self._lock:
			self._cm = cm
			self._merge(self._load())
		if self._thread is None:
			self._stop.clear()
			self._thread = threading.Thread(target=self._run, name="api-metering", daemon=True)
			self._thread.start()

	def _load(self) -> dict[str, Any]:
		try:
			_, content = self._cm.state_file(STATE_NAME).get()
			content, found = migrate_file(content, USAGE_VERSION)
			if content is None:
				if found == "newer":
					logger.warning("The API usage counts were written by a newer version: starting without them.")
				return {}
			sources = content.get("sources")
			return sources if isinstance(sources, dict) else {}
		except Exception:
			logger.warning("The API usage counts could not be read: starting without them.", exc_info=True)
			return {}

	def _merge(self, stored: Mapping[str, Any]) -> None:
		for source, entry in stored.items():
			days = entry.get("days") if isinstance(entry, dict) else None
			if not isinstance(days, dict):
				continue
			mine = self._sources.setdefault(str(source), { "days": {}, "lastLimited": None })
			for day, raw in days.items():
				old = _clean_bucket(raw)
				now = mine["days"].setdefault(str(day), _bucket())
				now["calls"] += old["calls"]
				now["sent"] += old["sent"]
				now["received"] += old["received"]
				for field in ("status", "cache", "cacheBytes"):
					for key, n in old[field].items():
						_bump(now[field], key, n)
			limited = entry.get("lastLimited")
			if isinstance(limited, str) and (mine["lastLimited"] is None or limited > mine["lastLimited"]):
				mine["lastLimited"] = limited

	def _run(self) -> None:
		while not self._stop.wait(FLUSH_SECONDS):
			self.flush()

	def _snapshot(self) -> dict[str, Any]:
		today = self._clock().date()
		oldest = (today - timedelta(days=KEEP_DAYS - 1)).isoformat()
		sources: dict[str, Any] = {}
		for source, entry in self._sources.items():
			entry["days"] = { day: b for day, b in entry["days"].items() if day >= oldest }
			if entry["days"]:
				sources[source] = { "days": { day: _clean_bucket(b) for day, b in entry["days"].items() }, "lastLimited": entry["lastLimited"] }
		return stamped({ "sources": sources }, USAGE_VERSION)

	def flush(self) -> None:
		"""Write the counts if any changed since the last write."""
		with self._lock:
			cm = self._cm
			if cm is None or not self._dirty:
				return
			document = self._snapshot()
			self._dirty = False
		try:
			cob = cm.state_file(STATE_NAME)
			rev, _ = cob.get()
			cob.save(rev, document)
		except Exception:
			with self._lock:
				self._dirty = True
			logger.warning("The API usage counts could not be saved: a restart will lose the last minutes.", exc_info=True)

	def close(self) -> None:
		"""Write what is counted and stop the writer (the application is quitting)."""
		self._stop.set()
		thread, self._thread = self._thread, None
		if thread is not None:
			thread.join(timeout=5)
		self.flush()

	def reset(self) -> None:
		"""Forget everything in memory (a test's)."""
		with self._lock:
			self._sources.clear()
			self._dirty = False

	# --- reporting

	def report(self, quotas: Mapping[str, "Quota"]|None = None) -> list[dict[str, Any]]:
		"""
		For the System page: for every data source that has made a call or used a cache, its counts for today, the last seven days and the calendar month so far (the device's days),
		the cache hit rate and the bytes the cache saved, and when the service last said "too many requests". Numbers only: the page names the source from its descriptor.
		A source in `quotas` (the plan the user says they have, #586) also gets its calls in the plan's period, even before it has made one.
		"""
		quotas = quotas or {}
		with self._lock:
			today = self._clock().date()
			days = { "today": {today.isoformat()}, "week": {(today - timedelta(days=n)).isoformat() for n in range(7)} }
			month = today.strftime("%Y-%m")
			result = []
			for source in sorted(set(self._sources) | set(quotas)):
				entry = self._sources.get(source) or { "days": {}, "lastLimited": None }
				periods = { name: _total([b for day, b in entry["days"].items() if day in wanted]) for name, wanted in days.items() }
				periods["month"] = _total([b for day, b in entry["days"].items() if day.startswith(month)])
				quota = quotas.get(source)
				result.append({ "id": source, **periods, "lastLimited": entry["lastLimited"],
					"quota": None if quota is None else quota.used(today, sum(b["calls"] for day, b in entry["days"].items() if quota.period(today)[0].isoformat() <= day <= today.isoformat())) })
			return result

@dataclass(frozen=True)
class Quota:
	"""The calls a plan allows in a period that starts on `reset_day` of each month (1 to 28, so every month has it)."""
	limit: int
	reset_day: int = 1

	def period(self, today: date) -> tuple[date, date]:
		"""The first day of the period `today` is in, and the first day of the next one."""
		start = today.replace(day=self.reset_day) if today.day >= self.reset_day else _previous_month(today).replace(day=self.reset_day)
		return start, _next_month(start).replace(day=self.reset_day)

	def used(self, today: date, calls: int) -> dict[str, Any]:
		since, resets = self.period(today)
		return { "limit": self.limit, "resetDay": self.reset_day, "used": calls, "percent": round(calls / self.limit * 100, 1), "since": since.isoformat(), "resets": resets.isoformat() }

def _previous_month(day: date) -> date:
	first = day.replace(day=1)
	return (first - timedelta(days=1)).replace(day=1)

def _next_month(day: date) -> date:
	return (day.replace(day=1) + timedelta(days=32)).replace(day=1)

def _total(buckets: list[dict[str, Any]]) -> dict[str, Any]:
	total = _bucket()
	for b in buckets:
		total["calls"] += b["calls"]
		total["sent"] += b["sent"]
		total["received"] += b["received"]
		for field in ("status", "cache", "cacheBytes"):
			for key, n in b[field].items():
				_bump(total[field], key, n)
	lookups = sum(total["cache"].get(k, 0) for k in LOOKUPS)
	answered = sum(total["cache"].get(k, 0) for k in ANSWERED)
	total["hitRate"] = round(answered / lookups, 3) if lookups else None
	total["bytesSaved"] = sum(total["cacheBytes"].get(k, 0) for k in ANSWERED)
	return total

METER = UsageMeter()

# --- the client

def failure_kind(error: BaseException) -> str:
	"""Why a call got no answer, in a word that says nothing of the address: `timeout`, `tls`, `connect` or `error`."""
	if isinstance(error, httpx.TimeoutException):
		return "timeout"
	if isinstance(error, httpx.ConnectError):
		cause: BaseException|None = error
		while cause is not None:
			if isinstance(cause, ssl.SSLError):
				return "tls"
			cause = cause.__cause__ or cause.__context__
		return "connect"
	return "error"

def _sent(request: httpx.Request) -> int:
	try:
		return len(request.content)
	except httpx.RequestNotRead:
		pass
	try:
		return max(0, int(request.headers.get("content-length", 0)))
	except ValueError:
		return 0

def _received(response: httpx.Response) -> int:
	"""What came over the wire for the body (compressed, if it was); a transport that hands over an answer already read (the tests' fake internet) never streamed it, so its body's length is the size."""
	if response.num_bytes_downloaded:
		return response.num_bytes_downloaded
	try:
		return len(response.content)
	except httpx.ResponseNotRead:
		return 0

# the data source a shared client's calls are counted under, for as long as it is set (`metered_as`): the download pool's client belongs to no source,
# and `download_for` names the one it downloads for. A context variable, so each task and thread names its own.
current_source: ContextVar[str|None] = ContextVar("metering_source", default=None)

@contextlib.contextmanager
def metered_as(source: str) -> Iterator[None]:
	"""Count the calls of a shared client (one made with no source) under `source` until the block ends."""
	token = current_source.set(source)
	try:
		yield
	finally:
		current_source.reset(token)

class MeteredClient(httpx.AsyncClient):
	"""
	An `httpx.AsyncClient` that counts every call it sends (`get`, `post` and `stream` all go through `send`): under its own source, or, for a shared client
	made with none (the download pool's), under the source `metered_as` names at the time; a call with neither is not counted.
	"""
	def __init__(self, source: str|None, meter: UsageMeter|None = None, **kwargs: Any):
		super().__init__(**kwargs)
		self._source = source
		self._meter = meter or METER

	async def send(self, request: httpx.Request, *, stream: bool = False, **kwargs: Any) -> httpx.Response:
		source = self._source or current_source.get()
		if source is None:
			return await super().send(request, stream=stream, **kwargs)
		try:
			response = await super().send(request, stream=stream, **kwargs)
		except httpx.HTTPError as e:
			self._meter.call(source, None, failure_kind(e), _sent(request), 0)
			raise
		for hop in response.history:
			self._meter.call(source, hop.status_code, None, _sent(hop.request), _received(hop))
		if not stream:
			self._meter.call(source, response.status_code, None, _sent(request), _received(response))
			return response
		# a streamed body is not here yet: its size is counted when it is closed
		self._meter.call(source, response.status_code, None, _sent(request), 0)
		closed = False
		original = response.aclose
		meter = self._meter
		async def aclose() -> None:
			nonlocal closed
			try:
				await original()
			finally:
				if not closed:
					closed = True
					meter.received(source, _received(response))
		response.aclose = aclose  # type: ignore[method-assign]
		return response

def metered_client(source: str, **kwargs: Any) -> MeteredClient:
	"""
	The HTTP client of an API data source, by its declared id: our TLS context (`tls_context`), in the tests the fake internet, and every call counted. `kwargs` are an `httpx.AsyncClient`'s
	(`timeout`, `headers`, `follow_redirects`).
	"""
	kwargs.setdefault("transport", AsyncHttpWorkerPool.default_transport)
	kwargs.setdefault("verify", tls_context())
	return MeteredClient(source, **kwargs)
