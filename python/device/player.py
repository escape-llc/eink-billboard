"""
One output's compositor (#891), like the panel's: layers back to front, and one cue at a time on the output.

- Background: the states that are on (`STATES`: the more urgent first), each with the cue the feedback rows give it on this output.
- Foreground: a gesture (a press, a long press) plays its cue once over the background, which then goes on.
- Priority: a Test plays now, over everything; a task's cue (a timer task's, the Clock Chime's strikes) plays once, as a gesture does.
- Post-processing: the quiet hours (one setting for every output) keep the output still; a Test passes through.

What plays is drawn by a `Renderer`, the output's own medium (an LED, the haptic motor, the sound card). A renderer that holds (an LED) plays a state's cue for as long as the state lasts when
the cue repeats; one that does not (a click, a tone) plays a state's cue once, when it begins, as the panel draws a new image only when something changed.
"""
from datetime import datetime
import logging
import threading
from typing import Any, Callable, Mapping, Protocol

from .cues import CUES, ENDED, GESTURES, HAPPENINGS, PLAYABLE, QUIET, STATES, Steps
from ..plugins.plugin_base import PermanentError

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
	the device's own, in its zone); `on_play` is told the title of each cue that starts and why, and Off when a state an output that holds showed is over, for the live view (from the player's own thread).
	`on_fault` is told, once, in our words, that its hardware went (a sound card pulled out: the renderer's `PermanentError`), until a cue plays again.
	"""
	# a cue that repeats is played this long by a Test
	TEST_SECONDS = 4.0
	# still, the player looks again this often whether the quiet hours began or ended
	IDLE_SECONDS = 60.0
	# the pause between two strikes of a cue played more than once (the hour's count)
	STRIKE_SECONDS = 0.3

	def __init__(self, name: str, renderer: Renderer, cues: Mapping[str, str], config: Mapping[str, Any], clock: Callable[[], datetime], on_play: Callable[[str, str], None]|None = None):
		self.name = name
		self._renderer = renderer
		self._cues = dict(cues)
		self._config = dict(config)
		self.clock = clock
		self.on_play = on_play
		self.on_fault: Callable[[str], None]|None = None
		self._lock = threading.Lock()
		# set when anything changes (a state, a cue to play once), and when a cue to play once arrives (it cuts short what plays; a state's change does not cut short a gesture)
		self._wake = threading.Event()
		self._urgent = threading.Event()
		self._states: set[str] = set()
		# cues to play once, ahead of the states: (each cue with its count, why, ignores the quiet hours, a Test's options)
		self._once: tuple[Steps, str, bool, Mapping[str, Any]|None]|None = None
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
			self._play_once(((cue, 1),), GESTURES[gesture], False, None)

	def happened(self, event: str) -> None:
		"""Something happened on the device (`started`, `pushed`, `failed`): its cue, once."""
		cue = self._cues.get(event)
		if event in HAPPENINGS and cue is not None:
			self._play_once(((cue, 1),), HAPPENINGS[event], False, None)

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
			self._play_once(((cue, 1),), "a test", True, options)

	def play(self, steps: Steps, why: str) -> None:
		"""Play cues once, in turn, each as many times as it says (a task's cue; the Clock Chime's changes and strikes), unless it is the quiet hours. `why` is said in the live view."""
		known = tuple((cue, max(1, count)) for cue, count in steps if cue in PLAYABLE and cue != "off")
		if known:
			self._play_once(known, why, False, None)

	def _play_once(self, steps: Steps, why: str, loud: bool, options: Mapping[str, Any]|None) -> None:
		with self._lock:
			self._once = (steps, why, loud, options)
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
		return self._renderer.holds and PLAYABLE[cue].repeat

	def _play_steps(self, steps: Steps, why: str, options: Mapping[str, Any]|None) -> None:
		"""On the player's thread: each cue in turn, its count of times, a pause between strikes; anything played once that arrives meanwhile cuts it short."""
		for cue, count in steps:
			if cue == "off":
				continue
			self._report(PLAYABLE[cue].title + (f" ×{count}" if count > 1 else ""), why)
			for strike in range(count):
				if strike > 0 and self._urgent.wait(self.STRIKE_SECONDS):
					return
				if self._renderer.play(cue, self._urgent, self.TEST_SECONDS if self._repeats(cue) else 0.0, options):
					return

	# ---- the player's own thread ------------------------------------------------------------------------------------------------------------------------

	def _run(self) -> None:
		renderer = self._renderer
		# whatever a run before this one left going (an LED lit, a sequence on the motor's chip) stops first: an app stopped hard and started again starts still
		try:
			renderer.off()
		except Exception:
			logger.warning(f"The output '{self.name}' could not be stilled when it opened", exc_info=True)
		# the state cue last reported, while it shows (the live view hears of a change, not of each cycle), and a once-only state cue already played
		reported: tuple[str, str]|None = None
		played: tuple[str, str]|None = None
		# the state cue being played (a once-only one that fails is not tried again: it would sound long after its state began), and what was last said of the hardware going
		trying: tuple[str, str]|None = None
		fault: str|None = None
		while not self._closing:
			self._wake.clear()
			with self._lock:
				once, self._once = self._once, None
				states = set(self._states)
			try:
				if once is not None:
					self._urgent.clear()
					steps, why, loud, options = once
					if loud or not quiet(self._config, self.clock()):
						self._play_steps(steps, why, options)
						fault = None
					# the state underneath is told again when it plays on
					reported = None
					continue
				state, cue = self._state_cue(states)
				quieted = cue != "off" and quiet(self._config, self.clock())
				if quieted:
					state, cue = None, "off"
				key = (cue, state or "")
				if cue == "off" or (not self._repeats(cue) and played == key):
					renderer.off()
					if cue == "off":
						played = None
						# what showed is over: said by an output that held it (a click or a tone already ended), and a state that begins again is said again
						if reported is not None:
							if renderer.holds:
								self._report(CUES["off"].title, QUIET if quieted else ENDED.get(reported[1], ""))
							reported = None
					self._wake.wait(self.IDLE_SECONDS)
					continue
				if reported != key:
					self._report(CUES[cue].title, STATES.get(state or "", ""))
					reported = key
				trying = key
				interrupted = renderer.play(cue, self._wake, 0.0)
				trying, fault = None, None
				played = key if not self._repeats(cue) and not interrupted else None
			except PermanentError as e:
				# the hardware went (a sound card pulled out): said once, not each cycle; it is tried again when something plays, or after a while
				if fault != str(e):
					fault = str(e)
					self._fault(fault)
				if trying is not None and not self._repeats(trying[0]):
					played = trying
				trying = None
				self._wake.wait(self.IDLE_SECONDS)
			except Exception:
				# a medium that fails (a sound card pulled out) is said once a cycle and waited out, not a dead thread
				logger.warning(f"The output '{self.name}' could not play", exc_info=True)
				self._wake.wait(self.IDLE_SECONDS)
		try:
			renderer.off()
		except Exception:
			logger.debug(f"The output '{self.name}' could not be stilled", exc_info=True)

	def _fault(self, message: str) -> None:
		logger.warning(f"The output '{self.name}' could not play: {message}")
		if self.on_fault is None:
			return
		try:
			self.on_fault(message)
		except Exception:
			logger.debug(f"The output '{self.name}''s fault could not be said", exc_info=True)

	def _report(self, title: str, why: str) -> None:
		if self.on_play is None:
			return
		try:
			self.on_play(title, why)
		except Exception:
			logger.debug(f"The output '{self.name}''s cue could not be reported", exc_info=True)
