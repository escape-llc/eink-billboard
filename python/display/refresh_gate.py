"""
The driver stage's rest between panel refreshes (the "blanking period").

An e-ink panel is refreshed at most once per rest: the image has time to settle, and the panel is not worn by a stream of refreshes. The rest starts when a refresh **ends** (or fails, or times out:
the panel may have been driven all the same), so a slow refresh does not eat into it. The gate lives in the driver stage, beside `PanelGuard`, because whatever sends an image to a panel
goes through the display class: a second caller of `render` is held to the same rest as the Display task.

Timing in the process is monotonic. The last end is also kept as a wall-clock time (`RefreshState`) so a restart inside the rest waits it out: that time is clamped, because a Pi with no
clock set yet (it has no battery) can read any date at boot, and a stale future time must never hold the panel for longer than one rest.
"""
import logging
import time
from typing import Any, Callable

from ..model.configuration_manager import ConfigurationManager
from ..model.migrations import migrate_file
from ..model.schema_versions import stamped

logger = logging.getLogger(__name__)

# the rest when the display settings do not say (the settings schema's default is the same)
DEFAULT_REST_SECONDS = 60.0

class TooSoon(RuntimeError):
	"""The panel was asked for a refresh before its rest was over."""

class RefreshGate:
	def __init__(self, rest_seconds: float = DEFAULT_REST_SECONDS, floor_seconds: float = 0.0, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
		self._clock = clock
		self._wall = wall
		# a model may say it must not be refreshed more often than this, whatever the setting says
		self.rest_seconds = max(float(rest_seconds), float(floor_seconds), 0.0)
		self._ready_at = 0.0
		self._sending = False
		self.last_end_wall: float|None = None

	def restore(self, last_end_wall: float|None) -> None:
		"""A restart: the rest that was left of the one the last run started. Never more than one rest, whatever the stored time says."""
		if last_end_wall is None or self.rest_seconds <= 0:
			return
		left = last_end_wall + self.rest_seconds - self._wall()
		left = min(max(left, 0.0), self.rest_seconds)
		self.last_end_wall = last_end_wall
		self._ready_at = self._clock() + left

	def ready_in(self) -> float:
		"""Seconds until a refresh may be sent: 0 when it may be now. While a send is on its way the answer is a whole rest, so nobody waits for nothing."""
		if self._sending:
			return max(self.rest_seconds, 1.0)
		return max(self._ready_at - self._clock(), 0.0)

	def begin(self) -> None:
		"""A refresh is about to be sent. Raises `TooSoon` when the rest is not over (the message says how long)."""
		wait = self.ready_in()
		if wait > 0:
			raise TooSoon(f"The panel is resting after its last refresh: not sending another for {wait:.0f} more seconds.")
		self._sending = True

	def finish(self) -> float|None:
		"""The send is over, however it went: the rest starts now. Returns the wall-clock end, for `RefreshState`."""
		self._sending = False
		if self.rest_seconds <= 0:
			return None
		self._ready_at = self._clock() + self.rest_seconds
		self.last_end_wall = self._wall()
		return self.last_end_wall

# the version of the file (it has no source schema to take one from: python/model/schema_versions.py); raised, with a step in `migrate_file`, if its content changes shape
REFRESH_VERSION = 1

class RefreshState:
	"""
	What survives a restart: when the last refresh ended and a digest of the image the panel shows. A file of its own in the storage's `state` folder (through the configuration manager,
	like every file); a file that cannot be read or written is no state, and never stops the panel.
	"""
	NAME = "refresh"
	def __init__(self, cm: ConfigurationManager|None):
		self._cm = cm
		self.last_end: float|None = None
		self.digest: str|None = None

	def load(self) -> None:
		try:
			if self._cm is None:
				return
			_, content = self._cm.state_file(self.NAME).get()
			content, found = migrate_file(content, REFRESH_VERSION)
			if content is None:
				if found == "newer":
					logger.warning("The refresh state was written by a newer version: starting without it.")
				return
			end, digest = content.get("lastEnd"), content.get("digest")
			if isinstance(end, (int, float)) and not isinstance(end, bool):
				self.last_end = float(end)
			if isinstance(digest, str) and digest:
				self.digest = digest
		except Exception:
			logger.warning("The refresh state could not be read: starting without it.", exc_info=True)

	def save(self, last_end: float|None, digest: str|None) -> None:
		"""`digest` is None when the panel's content is not known (a refresh that failed): the next page is drawn whatever it is."""
		self.last_end, self.digest = last_end, digest
		try:
			if self._cm is None:
				return
			cob = self._cm.state_file(self.NAME)
			rev, _ = cob.get()
			document: dict[str, Any] = stamped({ "lastEnd": last_end, "digest": digest }, REFRESH_VERSION)
			cob.save(rev, document)
		except Exception:
			logger.warning("The refresh state could not be saved: a restart will not know when the panel was last refreshed.", exc_info=True)
