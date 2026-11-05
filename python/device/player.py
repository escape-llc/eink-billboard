"""
One output's compositor (#891), like the panel's: layers back to front, and one cue at a time on the output.

- Background: the states that are on (`STATES`: the more urgent first), each with the cue the feedback rows give it on this output.
- Foreground: a gesture (a press, a long press) plays its cue once over the background, which then goes on.
- Priority: a Test plays now, over everything.
- Post-processing: the quiet hours (one setting for every output) keep the output still; a Test passes through.

What plays is drawn by a `Renderer`, the output's own medium (an LED, the haptic motor, the sound card). A renderer that holds (an LED) plays a state's cue for as long as the state lasts when
the cue repeats; one that does not (a click, a tone) plays a state's cue once, when it begins, as the panel draws a new image only when something changed.
"""
from datetime import datetime
import logging
import threading
from typing import Any, Callable, Mapping, Protocol

from .cues import CUES, GESTURES, STATES

logger = logging.getLogger(__name__)

class Renderer(Protocol):
	"""An output's medium. `play` draws a cue (once, or for `seconds` when it repeats) and answers True when `stop` cut it short; `options` are a Test's (an LED's `speed`, a sound's `volume`)."""
	# a state's repeating cue goes on while the state lasts (an LED); else every cue plays once
	holds: bool
	def play(self, cue: str, stop: threading.Event, seconds: float, options: Mapping[str, Any]|None = None) -> bool:
		...
	def off(self) -> None:
		...
	def close(self) -> None:
		...

def hour_of(value: object) -> int|None:
	return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23 else None

def quiet(config: Mapping[str, Any], now: datetime) -> bool:
	"""In the quiet hours: from `quietFrom` (an hour, 0 to 23) up to `quietTo`, across midnight when it is earlier; either unset is never quiet, and the same hour is never quiet."""
	start, end = hour_of(config.get("quietFrom")), hour_of(config.get("quietTo"))
	if start is None or end is None or start == end:
		return False
	hour = now.hour
	return start <= hour < end if start < end else hour >= start or hour < end

class Player:
	"""
	`cues` is what this output plays for each event (the feedback rows that name it; an event with none plays nothing). `clock` says the time for the quiet hours (the DeviceIO task gives
	the device's own, in its zone); `on_play` is told the title of each cue that starts and why, for the live view (from the player's own thread).
	"""
	# a cue that repeats is played this long by a Test
	TEST_SECONDS = 4.0
	# still, the player looks again this often whether the quiet hours began or ended
	IDLE_SECONDS = 60.0

	def __init__(self, name: str, renderer: Renderer, cues: Mapping[str, str], config: Mapping[str, Any], clock: Callable[[], datetime], on_play: Callable[[str, str], None]|None = None):
		self.name = name
		self._renderer = renderer
		self._cues = dict(cues)
		self._config = dict(config)
		self.clock = clock
		self.on_play = on_play
		self._lock = threading.Lock()
		# set when anything changes (a state, a cue to play once), and when a cue to play once arrives (it cuts short what plays; a state's change does not cut short a gesture)
		self._wake = threading.Event()
		self._urgent = threading.Event()
		self._states: set[str] = set()
		# a cue to play once, ahead of the states: (cue, why, ignores the quiet hours, a Test's options)
		self._once: tuple[str, str, bool, Mapping[str, Any]|None]|None = None
		self._closing = False
		self._thread = threading.Thread(target=self._run, name=f"output-{name}", daemon=True)

	def start(self) -> None:
		self._thread.start()

	def close(self) -> None:
		self._closing = True
		self._wake.set()
		self._urgent.set()
		if self._thread.is_alive():
			self._thread.join(timeout=2.0)
		try:
			self._renderer.off()
			self._renderer.close()
		except Exception:
			logger.debug(f"The output '{self.name}' did not close cleanly", exc_info=True)

	# ---- what the Outputs device tells it (any thread) ----------------------------------------------------------------------------------------------------

	def gesture(self, gesture: str) -> None:
		"""A button was let go (`press`, `long-press`): its cue, once."""
		cue = self._cues.get(gesture)
		if gesture in GESTURES and cue is not None:
			self._play_once(cue, GESTURES[gesture], False, None)

	def state(self, name: str, on: bool) -> None:
		"""A state began or ended (`holding`, `problem`, `drawing`)."""
		with self._lock:
			before = set(self._states)
			if on:
				self._states.add(name)
			else:
				self._states.discard(name)
			if self._states == before:
				return
		self._wake.set()

	def test(self, cue: str, options: Mapping[str, Any]|None = None) -> None:
		"""Play a cue once now, the quiet hours or not (the settings' Test): a cue that repeats plays for `TEST_SECONDS` on an output that holds. `options` are the form's (a speed)."""
		if cue in CUES:
			self._play_once(cue, "a test", True, options)

	def _play_once(self, cue: str, why: str, loud: bool, options: Mapping[str, Any]|None) -> None:
		with self._lock:
			self._once = (cue, why, loud, options)
		self._urgent.set()
		self._wake.set()

	def _state_cue(self, states: set[str]) -> tuple[str|None, str]:
		"""What the states that are on play here: the most urgent one whose cue is not Off, and its cue; (None, "off") when none."""
		for state in STATES:
			cue = self._cues.get(state, "off")
			if state in states and cue != "off":
				return state, cue
		return None, "off"

	def _repeats(self, cue: str) -> bool:
		return self._renderer.holds and CUES[cue].repeat

	# ---- the player's own thread ------------------------------------------------------------------------------------------------------------------------

	def _run(self) -> None:
		renderer = self._renderer
		# the state cue last reported (the live view hears of a change, not of each cycle), and a once-only state cue already played
		reported: tuple[str, str]|None = None
		played: tuple[str, str]|None = None
		while not self._closing:
			self._wake.clear()
			with self._lock:
				once, self._once = self._once, None
				states = set(self._states)
			try:
				if once is not None:
					self._urgent.clear()
					cue, why, loud, options = once
					if cue != "off" and (loud or not quiet(self._config, self.clock())):
						self._report(CUES[cue].title, why)
						renderer.play(cue, self._urgent, self.TEST_SECONDS if self._repeats(cue) else 0.0, options)
					# the state underneath is told again when it plays on
					reported = None
					continue
				state, cue = self._state_cue(states)
				if quiet(self._config, self.clock()):
					state, cue = None, "off"
				key = (cue, state or "")
				if cue == "off" or (not self._repeats(cue) and played == key):
					renderer.off()
					if cue == "off":
						played = None
					self._wake.wait(self.IDLE_SECONDS)
					continue
				if reported != key:
					self._report(CUES[cue].title, STATES.get(state or "", ""))
					reported = key
				interrupted = renderer.play(cue, self._wake, 0.0)
				played = key if not self._repeats(cue) and not interrupted else None
			except Exception:
				# a medium that fails (a sound card pulled out) is said once a cycle and waited out, not a dead thread
				logger.warning(f"The output '{self.name}' could not play", exc_info=True)
				self._wake.wait(self.IDLE_SECONDS)
		try:
			renderer.off()
		except Exception:
			logger.debug(f"The output '{self.name}' could not be stilled", exc_info=True)

	def _report(self, title: str, why: str) -> None:
		if self.on_play is None:
			return
		try:
			self.on_play(title, why)
		except Exception:
			logger.debug(f"The output '{self.name}''s cue could not be reported", exc_info=True)
