"""
Sign-ins of the web app, kept on the server.

The browser stores nothing but the theme. When the API requires a token, the web app sends the token once to
`POST /api/session`; the server remembers the sign-in here and gives the browser an HttpOnly cookie holding only
an unguessable session ID, which scripts in the page cannot read. The sessions live in memory: a restart signs everyone out.
"""
import secrets
import threading
import time
from typing import Callable

class SessionStore:
	def __init__(self, ttl_seconds: float = 7 * 24 * 3600, max_sessions: int = 64, clock: Callable[[], float] = time.monotonic):
		self.ttl = int(ttl_seconds)
		self._max = max_sessions
		self._clock = clock
		self._expires: dict[str, float] = {}
		# the endpoints are plain functions that run on a thread pool
		self._lock = threading.Lock()

	def _purge(self, now: float) -> None:
		for sid in [s for s, expires in self._expires.items() if expires <= now]:
			del self._expires[sid]

	def create(self) -> str:
		"""A new session ID. When there are too many sessions the oldest ones are dropped."""
		with self._lock:
			now = self._clock()
			self._purge(now)
			while len(self._expires) >= self._max:
				del self._expires[min(self._expires, key=self._expires.__getitem__)]
			sid = secrets.token_urlsafe(32)
			self._expires[sid] = now + self.ttl
			return sid

	def valid(self, sid: str|None) -> bool:
		if not sid:
			return False
		with self._lock:
			expires = self._expires.get(sid)
			if expires is None:
				return False
			if expires <= self._clock():
				del self._expires[sid]
				return False
			return True

	def delete(self, sid: str|None) -> None:
		if sid:
			with self._lock:
				self._expires.pop(sid, None)

class SignInThrottle:
	"""
	Slows down guessing at the sign-in. Each client address gets a few free failures; every failure after that closes the door for twice as long as the
	one before (2 s, 4 s, ... at most 5 minutes), and a success, or a quiet quarter of an hour, forgets them. The answer is "try again in N seconds",
	not a wait on a server thread, so guessing cannot also tie up the server. In memory: a restart forgets.
	"""
	FREE = 3
	MAX_WAIT = 300.0
	FORGET_AFTER = 900.0

	def __init__(self, clock: Callable[[], float] = time.monotonic, max_clients: int = 256):
		self._clock = clock
		self._max = max_clients
		self._lock = threading.Lock()
		# who -> (failures in a row, when the last one was, when the door opens again)
		self._state: dict[str, tuple[int, float, float]] = {}

	def wait(self, who: str) -> float:
		"""Seconds before this client may try again (0 when it may now)."""
		with self._lock:
			entry = self._state.get(who)
			if entry is None:
				return 0.0
			now = self._clock()
			if now - entry[1] > self.FORGET_AFTER:
				del self._state[who]
				return 0.0
			return max(0.0, entry[2] - now)

	def failed(self, who: str) -> int:
		"""Count a failure; returns how many in a row."""
		with self._lock:
			now = self._clock()
			count = self._state.get(who, (0, now, now))[0] + 1
			wait = min(2.0 ** (count - self.FREE), self.MAX_WAIT) if count > self.FREE else 0.0
			if who not in self._state and len(self._state) >= self._max:
				oldest = min(self._state, key=lambda w: self._state[w][1])
				del self._state[oldest]
			self._state[who] = (count, now, now + wait)
			return count

	def succeeded(self, who: str) -> None:
		with self._lock:
			self._state.pop(who, None)
