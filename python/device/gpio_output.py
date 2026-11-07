"""
A GPIO output (#885, #891): an LED wired from a header pin through a resistor to ground (the Inky Impression has one on GPIO 13, at the top centre edge of the board), or an active
piezo buzzer the same way. On or off, no brightness, so a cue is only times: on for so long, off for so long. It holds: a state's repeating cue goes on while the state lasts.

The output's `speed` (one of `SPEEDS`: the seconds one blink takes) stretches every cue's times by its ratio to `NORMAL_BLINK`, so a cue keeps its rhythm.
gpiozero (the device dependency group, Linux) is imported only when the output is opened.
"""
import logging
import threading
from typing import Any, Callable, Mapping

from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

BLINK = (0.15, 0.25)
# one blink's on and off together: the patterns are written for it, and the speed stretches them all by its ratio to this
NORMAL_BLINK = 0.4
# the speeds a person chooses from (the schema's `speeds` lookup), the seconds one blink takes
SPEEDS = ("0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8")

# each cue as steps: on for the first time, off for the second
PATTERNS: Mapping[str, tuple[tuple[float, float], ...]] = {
	"off": (),
	"one": (BLINK,),
	"two": (BLINK, BLINK),
	"three": (BLINK, BLINK, BLINK),
	"steady": ((1.0, 0.0),),
	"slow": ((1.0, 1.0),),
	"fast": ((0.25, 0.25),),
	"heartbeat": ((0.12, 0.12), (0.12, 0.8)),
	# a clock's strike, and a Westminster change as its rhythm: three short blinks and a long one
	"bell": ((0.6, 0.6),),
	**{ f"change-{n}": ((0.15, 0.15), (0.15, 0.15), (0.15, 0.15), (0.3, 0.6)) for n in range(1, 6) },
}

def scale_of(speed: object) -> float:
	"""How much a speed (one of `SPEEDS`) stretches every cue's times; anything else is the normal speed (1)."""
	return float(speed) / NORMAL_BLINK if isinstance(speed, str) and speed in SPEEDS else 1.0

def load_led() -> Any:
	"""gpiozero's `LED`, or a `PermanentError` that says, in our words, what to do."""
	try:
		from gpiozero import LED
	except ImportError as e:
		raise PermanentError("A GPIO output needs the device libraries (`uv sync --group device`, Raspberry Pi only). On another machine leave its pin empty in the GPIO settings.") from e
	return LED

class GpioRenderer:
	"""`factory` makes a gpiozero-style LED (`on()`, `off()`, `close()`; a test gives a fake one); by default it is gpiozero's."""
	holds = True

	def __init__(self, pin: int, speed: object = None, factory: Callable[..., Any]|None = None):
		self.pin = pin
		self._scale = scale_of(speed)
		make = factory or load_led()
		try:
			self._led = make(pin)
			self._led.off()
		except Exception as e:
			logger.error(f"The output on pin {pin} could not be opened: {e}", exc_info=True)
			raise PermanentError(f"The output on pin {pin} could not be opened. Check that nothing else uses the pin, the wiring and that GPIO is available to the app. The log has the detail.") from e

	def play(self, cue: str, stop: threading.Event, seconds: float, options: Mapping[str, Any]|None = None) -> bool:
		"""One cycle of the cue's steps, or cycles for `seconds`; True when `stop` was set meanwhile (left off). A Test's `speed` replaces the output's."""
		steps = PATTERNS.get(cue, ())
		if not steps:
			self._led.off()
			return False
		scale = scale_of(options.get("speed")) if options is not None and options.get("speed") is not None else self._scale
		played = 0.0
		while True:
			for on_time, off_time in ((on * scale, off * scale) for on, off in steps):
				self._led.on()
				if stop.wait(on_time):
					self._led.off()
					return True
				if off_time > 0:
					self._led.off()
					if stop.wait(off_time):
						return True
				played += on_time + off_time
			if played >= seconds:
				# a steady state stays lit until something else is chosen
				if cue != "steady":
					self._led.off()
				return False

	def off(self) -> None:
		self._led.off()

	def close(self) -> None:
		self._led.close()
