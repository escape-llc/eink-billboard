"""
The telemetry link: what the tasks report (`Telemetry` on the `telemetry` route) kept for a live view in the web app.

The hub is the route's sink. It turns each message into a small JSON **event** `{ seq, ts, source, kind, message?, values }`:
- `seq` grows by one per event, so a page that reconnects asks only for what it missed;
- `ts` carries its offset (dates crossing the API name their zone);
- `kind` is a short stable name (`track-played`, `track-failed`, `task-ran`, `waiting`, `faulted`, `shown`, ...);
- `message` is our own sentence, and `values` only JSON scalars, short lists and small objects: an object becomes its title or its type's name.
Telemetry leaves the device, so it is a response like any other: it never holds raw exception text (the layers send `safe_reason`: an actionable reason with addresses and secrets removed).

The last events are kept in a ring; each WebSocket client has a bounded queue, and a client too slow to keep up loses its oldest events and
gets a `gap` event instead, so a slow page never holds up the device. `accept` is called on the sending task's thread.

A `shown` event from the display carries the image the panel now shows: the hub keeps the last few by their digest (`image(digest, size)`)
and the event holds only the digest, so pictures go to the browser over plain HTTP, never through the link.
"""
import asyncio
import collections
import io
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping

from PIL import Image

from .configure_event import ConfigureNotify
from .messages import BasicMessage, Telemetry
from .protocols import MessageSink

MAX_EVENTS = 200
MAX_IMAGES = 8
QUEUE_SIZE = 100
THUMB_WIDTH = 320
MAX_TEXT = 300
MAX_ITEMS = 20
MAX_DETAIL = 2000
# event fields that leave the device only to a viewer on the device itself
LOCAL_ONLY = ("detail",)

# the steps that bring the device up, as ConfigureEvent names them
COMPONENTS = ("display", "playlist-layer", "timer-layer")

# a state the layers report, as the kind of event it is (when the values do not say)
_KINDS = {
	("playlist_layer", "playing"): "track-ended",
	("timer_layer", "playing"): "task-ended",
	("timer_layer", "waiting"): "waiting",
}

def _instant(when: Any) -> str|None:
	if not isinstance(when, datetime):
		return None
	return (when if when.tzinfo is not None else when.astimezone()).isoformat()

def safe_value(value: Any, depth: int = 0) -> Any:
	"""A value as JSON that says no more than it should: scalars (text cut short), times with their offset, small lists and objects."""
	if value is None or isinstance(value, (bool, int, float)):
		return value
	if isinstance(value, str):
		return value if len(value) <= MAX_TEXT else value[:MAX_TEXT - 1] + "…"
	if isinstance(value, datetime):
		return _instant(value)
	if isinstance(value, timedelta):
		return value.total_seconds()
	# an event's values, a list in them (the shown layers), the objects of that list, and their origins (a list of them for the overlays): deeper is not needed
	if depth >= 5:
		return type(value).__name__
	if isinstance(value, Mapping):
		return { str(k): safe_value(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS] }
	if isinstance(value, (list, tuple)):
		return [safe_value(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
	# a schedule item, a playlist: its title or name says which, the rest stays on the device
	for name in ("title", "name"):
		label = getattr(value, name, None)
		if isinstance(label, str):
			return safe_value(label)
	return type(value).__name__

def _named(value: Any) -> Any:
	"""A playlist (a loader's dict or an object) by its name."""
	if isinstance(value, Mapping):
		info = value.get("info")
		return safe_value(getattr(info, "name", None) or value.get("name") or (info.get("name") if isinstance(info, Mapping) else None))
	return safe_value(value)

def _is_ours(error: Any) -> bool:
	"""A failure whose message is ours to show (a `PermanentError`, as `safe_reason` treats it: it says what is wrong and what to do)."""
	# imported here: plugin_base imports half the application
	from ..plugins.plugin_base import PermanentError
	return isinstance(error, PermanentError)

def _ours(error: Any) -> str:
	"""The failure's own words after a colon when they are ours to show, else nothing (the caller ends the sentence)."""
	return f": {str(error).rstrip('.')}" if _is_ours(error) else ""

@dataclass(eq=False)
class Subscriber:
	"""One WebSocket client: events reach its queue on its own loop; `missed` counts what a full queue dropped."""
	loop: asyncio.AbstractEventLoop
	queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
	missed: int = 0

	def push(self, event: dict) -> None:
		"""On the subscriber's loop: a full queue drops its oldest event."""
		if self.queue.full():
			self.queue.get_nowait()
			self.missed += 1
		self.queue.put_nowait(event)

	async def next(self) -> dict:
		"""The next event; a `gap` first when some were dropped since the last one."""
		if self.missed:
			missed, self.missed = self.missed, 0
			return { "kind": "gap", "source": "telemetry", "missed": missed, "message": f"{missed} events were missed." }
		return await self.queue.get()

@dataclass
class Snapshot:
	digest: str
	image: Image.Image
	png: dict[str, bytes] = field(default_factory=dict)

class TelemetryHub(MessageSink):
	"""The `telemetry` route's sink: a ring of recent events, live subscribers, and the images the panel showed last."""
	def __init__(self, max_events: int = MAX_EVENTS, max_images: int = MAX_IMAGES):
		self._lock = threading.Lock()
		self._events: collections.deque[dict] = collections.deque(maxlen=max_events)
		self._seq = 0
		# `seq` starts again at every start: a page that followed the last run tells it by this, and asks for everything (see the WebSocket's `hello`)
		self.run = secrets.token_hex(6)
		self._subscribers: set[Subscriber] = set()
		self._images: collections.OrderedDict[str, Snapshot] = collections.OrderedDict()
		self._max_images = max_images
		self._current: dict|None = None
		self._status: dict[str, str] = {}
		# why a component failed, when the failure is ours to word (see _is_ours)
		self._reasons: dict[str, Any] = {}

	# ---- in ----
	def accept(self, msg: BasicMessage) -> None:
		if isinstance(msg, ConfigureNotify) and msg.token in COMPONENTS:
			with self._lock:
				self._status[msg.token] = "failed" if msg.error else "ok"
				self._reasons[msg.token] = msg.content if msg.error and _is_ours(msg.content) else None
		event = self._event(msg)
		if event is None:
			return
		with self._lock:
			self._seq += 1
			event = { "seq": self._seq, **event }
			self._events.append(event)
			if event["kind"] == "shown":
				self._current = event
			subscribers = list(self._subscribers)
		for sub in subscribers:
			try:
				sub.loop.call_soon_threadsafe(sub.push, event)
			except RuntimeError:
				# its loop has closed: the client is gone
				self.unsubscribe(sub)

	def _event(self, msg: BasicMessage) -> dict|None:
		if isinstance(msg, ConfigureNotify):
			if not msg.error:
				return None
			return { "ts": _instant(msg.timestamp), "source": "application", "kind": "configure-failed", "message": f"'{msg.token}' could not be configured{_ours(msg.content)}.", "values": {} }
		if not isinstance(msg, Telemetry):
			return None
		values = dict(msg.values or {})
		image = values.pop("image", None)
		message = values.pop("message", None)
		detail = values.pop("detail", None)
		kind = values.pop("kind", None) or _KINDS.get((msg.name, str(values.get("state"))), str(values.get("state") or "event"))
		for key in ("current_playlist",):
			if key in values:
				values[key] = _named(values[key])
		event = { "ts": _instant(msg.timestamp), "source": msg.name, "kind": str(kind), "values": safe_value(values) }
		if isinstance(message, str) and message:
			event["message"] = safe_value(message)
		# the exception in full: the telemetry route sends it only to a viewer on the device itself (LOCAL_ONLY)
		if isinstance(detail, str) and detail:
			event["detail"] = detail[:MAX_DETAIL]
		if kind == "shown" and isinstance(image, Image.Image) and isinstance(values.get("digest"), str):
			self._keep_image(values["digest"], image)
		return event

	def _keep_image(self, digest: str, image: Image.Image) -> None:
		with self._lock:
			if digest in self._images:
				self._images.move_to_end(digest)
				return
			self._images[digest] = Snapshot(digest, image.copy())
			while len(self._images) > self._max_images:
				self._images.popitem(last=False)

	# ---- out ----
	def latest(self) -> int:
		"""The `seq` of the newest event (0 before any): what a link sends after its `hello` up to this number is history, not news."""
		with self._lock:
			return self._seq

	def since(self, seq: int = 0) -> list[dict]:
		"""The kept events newer than `seq`, oldest first."""
		with self._lock:
			return [e for e in self._events if e["seq"] > seq]

	def status(self) -> dict:
		"""How bringing each component up went: `ok`, `failed`, or `starting` (not reported yet, or waiting for the display). The words are ours, never the error's."""
		with self._lock:
			state = dict(self._status)
			reasons = dict(self._reasons)
		components = {}
		for name in COMPONENTS:
			current = state.get(name, "starting")
			if current == "failed":
				message = f"Could not be set up{_ours(reasons.get(name))}. See the log, fix the settings, then restart."
			elif current == "ok":
				message = "Running."
			elif name != "display" and state.get("display") == "failed":
				message = "Waiting for the display."
			else:
				message = "Starting."
			components[name] = { "state": current, "message": message }
		return { "ok": all(c["state"] == "ok" for c in components.values()), "components": components }

	def current(self) -> dict|None:
		"""The last `shown` event: what the panel shows now (None until something was drawn)."""
		with self._lock:
			return self._current

	def image(self, digest: str, size: str = "thumb") -> bytes|None:
		"""A kept image as PNG, full size or a thumbnail (made once). None when the digest is not one of ours."""
		with self._lock:
			snap = self._images.get(digest)
		if snap is None:
			return None
		if size not in snap.png:
			picture = snap.image.copy()
			if size == "thumb":
				picture.thumbnail((THUMB_WIDTH, THUMB_WIDTH), Image.Resampling.LANCZOS)
			out = io.BytesIO()
			picture.save(out, "PNG")
			snap.png[size] = out.getvalue()
		return snap.png[size]

	def subscribe(self, loop: asyncio.AbstractEventLoop) -> Subscriber:
		sub = Subscriber(loop)
		with self._lock:
			self._subscribers.add(sub)
		return sub

	def unsubscribe(self, sub: Subscriber) -> None:
		with self._lock:
			self._subscribers.discard(sub)

	def __len__(self) -> int:
		with self._lock:
			return len(self._events)
