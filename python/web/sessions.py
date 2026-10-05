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
