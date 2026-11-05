"""
An LED on one of the header's GPIO pins, wired from the pin through a resistor to ground (the Inky Impression has one on GPIO 13, at the top centre edge of the board). It is the device's
only fast signal: a panel refresh takes about 30 seconds, so the LED says at once that a button was pressed, while the panel draws, and when something needs a look (#885).

It plays a pattern for each event, as the GPIO settings choose (`led*`): a gesture (a press, a long press) plays its pattern once; a state (drawing, a problem) plays its pattern for as long as
the state lasts. One LED plays one pattern at a time: a gesture interrupts, then the state underneath goes on; a problem outranks drawing; in the quiet hours it is dark (a Test still plays).
An LED is on or off (no brightness), so a pattern is only times: on for so long, off for so long.

gpiozero (the device dependency group, Linux) is imported only when the LED is opened.
"""
from dataclasses import dataclass
from datetime import datetime
import logging
import threading
from typing import Any, Callable, Mapping

from .base import Emit
from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Pattern:
	"""What the LED does: each step on for its first time and off for its second, in order; `repeat` plays them again until something else is chosen (a state's pattern), else once."""
	title: str
	steps: tuple[tuple[float, float], ...]
	repeat: bool

BLINK = (0.15, 0.25)

# the patterns a person chooses from, by the value stored in the settings; the order is the list's in the form (the schema's `ledPatterns` lookup says the same titles)
PATTERNS: Mapping[str, Pattern] = {
	"off": Pattern("Off", (), False),
	"blink-1": Pattern("One blink", (BLINK,), False),
	"blink-2": Pattern("Two blinks", (BLINK, BLINK), False),
	"blink-3": Pattern("Three blinks", (BLINK, BLINK, BLINK), False),
	"steady": Pattern("Steady", ((1.0, 0.0),), True),
	"slow": Pattern("Slow blink", ((1.0, 1.0),), True),
	"fast": Pattern("Fast blink", ((0.25, 0.25),), True),
	"heartbeat": Pattern("Heartbeat", ((0.12, 0.12), (0.12, 0.8)), True),
}

# what each event of the settings is, its field and the pattern when the field is not set (the schema's defaults)
GESTURES: Mapping[str, tuple[str, str]] = { "press": ("ledPress", "blink-1"), "long-press": ("ledLongPress", "blink-2") }
# the states, the more urgent first
STATES: tuple[tuple[str, str, str], ...] = (("problem", "ledProblem", "off"), ("drawing", "ledDrawing", "steady"))
# what each state is called in the telemetry
STATE_WORDS: Mapping[str, str] = { "problem": "a problem", "drawing": "the panel drawing" }

def led_pin(config: Mapping[str, Any]) -> int|None:
	pin = config.get("ledPin")
	return pin if isinstance(pin, int) and not isinstance(pin, bool) else None

def pattern_of(config: Mapping[str, Any], field: str, fallback: str) -> str:
	"""The pattern a field of the settings chooses: its value when it is one of `PATTERNS`, else the field's default."""
	value = config.get(field)
	return value if isinstance(value, str) and value in PATTERNS else fallback

def quiet(config: Mapping[str, Any], now: datetime) -> bool:
	"""In the quiet hours: from `ledQuietFrom` (an hour, 0 to 23) up to `ledQuietTo`, across midnight when it is earlier; either unset is never quiet, and the same hour is never quiet."""
	def hour_of(name: str) -> int|None:
		value = config.get(name)
		return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23 else None
	start, end = hour_of("ledQuietFrom"), hour_of("ledQuietTo")
	if start is None or end is None or start == end:
		return False
	hour = now.hour
	return start <= hour < end if start < end else hour >= start or hour < end

def state_pattern(config: Mapping[str, Any], states: set[str]) -> tuple[str|None, str]:
	"""What the states that are on play: the most urgent one whose pattern is not Off, and its pattern; (None, "off") when none."""
	for state, field, fallback in STATES:
		if state in states:
			chosen = pattern_of(config, field, fallback)
			if chosen != "off":
				return state, chosen
	return None, "off"

def load_led() -> Any:
	"""gpiozero's `LED`, or a `PermanentError` that says, in our words, what to do."""
	try:
		from gpiozero import LED
	except ImportError as e:
		raise PermanentError("The LED needs the device libraries (`uv sync --group device`, Raspberry Pi only). On another machine leave the LED's pin empty in the GPIO settings.") from e
	return LED

class Led:
	"""
	`factory` makes a gpiozero-style LED (`on()`, `off()`, `close()`; a test gives a fake one); by default it is gpiozero's. `clock` says the time for the quiet hours (the DeviceIO task gives the device's own, in its zone).
	`on_play` is told the title of each pattern that starts and why, for the live view (from the LED's own thread).
	"""
	id = "led"

	def __init__(self, factory: Callable[..., Any]|None = None, clock: Callable[[], datetime]|None = None):
		self._factory = factory
		self.clock: Callable[[], datetime] = clock or (lambda: datetime.now().astimezone())
		self.on_play: Callable[[str, str], None]|None = None
		self._config: Mapping[str, Any] = {}
		self._led: Any = None
		self._lock = threading.Lock()
		# set when anything changes (a state, a pattern to play once), and when a pattern to play once arrives (it cuts short what plays, a state's change does not cut short a gesture)
		self._wake = threading.Event()
		self._urgent = threading.Event()
		self._states: set[str] = set()
		# a pattern to play once, ahead of the states: (pattern, why, ignores the quiet hours)
		self._once: tuple[str, str, bool]|None = None
		self._thread: threading.Thread|None = None
		self._closing = False

	def pins(self, config: Mapping[str, Any]) -> dict[str, int]:
		pin = led_pin(config)
		return { "led": pin } if pin is not None else {}

	def open(self, emit: Emit, config: Mapping[str, Any]) -> None:
		pin = led_pin(config)
		if pin is None:
			return
		factory = self._factory or load_led()
		try:
			self._led = factory(pin)
			self._led.off()
		except Exception as e:
			self.close()
			logger.error(f"The LED could not be opened: {e}", exc_info=True)
			raise PermanentError("The LED could not be opened. Check that nothing else uses its pin, the wiring and that GPIO is available to the app. The log has the detail.") from e
		self._config = dict(config)
		self._closing = False
		self._thread = threading.Thread(target=self._run, name="led", daemon=True)
		self._thread.start()
		logger.info(f"The LED on pin {pin} is open.")

	def close(self) -> None:
		self._closing = True
		self._wake.set()
		self._urgent.set()
		thread, self._thread = self._thread, None
		if thread is not None:
			thread.join(timeout=2.0)
		led, self._led = self._led, None
		if led is not None:
			try:
				led.off()
				led.close()
			except Exception:
				logger.debug("The LED did not close cleanly", exc_info=True)

	# ---- what the DeviceIO task tells it (any thread) ---------------------------------------------------------------------------------------------------

	def gesture(self, gesture: str) -> None:
		"""A button was pressed (`press`) or held (`long-press`): its pattern, once."""
		chosen = GESTURES.get(gesture)
		if chosen is not None:
			self._play_once(pattern_of(self._config, *chosen), "a press" if gesture == "press" else "a long press", False)

	def state(self, name: str, on: bool) -> None:
		"""A state began or ended (`drawing`, `problem`)."""
		with self._lock:
			before = set(self._states)
			if on:
				self._states.add(name)
			else:
				self._states.discard(name)
			if self._states == before:
				return
		self._wake.set()

	def test(self, pattern: str) -> None:
		"""Play a pattern once now, the quiet hours or not (the settings' Test): a pattern that repeats plays for `TEST_SECONDS`."""
		if pattern in PATTERNS:
			self._play_once(pattern, "a test", True)

	def _play_once(self, pattern: str, why: str, loud: bool) -> None:
		with self._lock:
			self._once = (pattern, why, loud)
		self._urgent.set()
		self._wake.set()

	# ---- the LED's own thread ---------------------------------------------------------------------------------------------------------------------------

	# a pattern that repeats is played this long by a Test
	TEST_SECONDS = 4.0
	# dark, the LED looks again this often whether the quiet hours began or ended
	IDLE_SECONDS = 60.0

	def _run(self) -> None:
		led = self._led
		# the state pattern last reported (the live view hears of a change, not of each cycle), and a once-only state pattern already played
		reported: tuple[str, str]|None = None
		played: tuple[str, str]|None = None
		while not self._closing and led is not None:
			self._wake.clear()
			with self._lock:
				once, self._once = self._once, None
				states = set(self._states)
			if once is not None:
				self._urgent.clear()
				chosen, why, loud = once
				pattern = PATTERNS[chosen]
				if pattern.steps and (loud or not quiet(self._config, self.clock())):
					self._report(pattern.title, why)
					self._play(led, pattern, self._urgent, self.TEST_SECONDS if pattern.repeat else 0.0)
				# the state underneath is told again when it plays on
				reported = None
				continue
			state, chosen = state_pattern(self._config, states)
			if quiet(self._config, self.clock()):
				state, chosen = None, "off"
			pattern = PATTERNS[chosen]
			key = (chosen, state or "")
			if not pattern.steps or (not pattern.repeat and played == key):
				led.off()
				if not pattern.steps:
					played = None
				self._wake.wait(self.IDLE_SECONDS)
				continue
			if reported != key:
				self._report(pattern.title, STATE_WORDS.get(state or "", ""))
				reported = key
			interrupted = self._play(led, pattern, self._wake, 0.0)
			played = key if not pattern.repeat and not interrupted else None
		if led is not None:
			try:
				led.off()
			except Exception:
				logger.debug("The LED could not be switched off", exc_info=True)

	def _report(self, title: str, why: str) -> None:
		if self.on_play is None:
			return
		try:
			self.on_play(title, why)
		except Exception:
			logger.debug("The LED's pattern could not be reported", exc_info=True)

	@staticmethod
	def _play(led: Any, pattern: Pattern, stop: threading.Event, seconds: float) -> bool:
		"""One cycle of `pattern`'s steps, or cycles for `seconds`; True when `stop` was set meanwhile (the LED is left off)."""
		played = 0.0
		while True:
			for on_time, off_time in pattern.steps:
				led.on()
				if stop.wait(on_time):
					led.off()
					return True
				if off_time > 0:
					led.off()
					if stop.wait(off_time):
						return True
				played += on_time + off_time
			if played >= seconds:
				if pattern is not PATTERNS["steady"]:
					led.off()
				return False
