"""
Push buttons on the header's GPIO pins: each wired between its pin and ground (the pin's internal pull-up holds it high; a press pulls it low), with a short debounce. A pin the settings
leave empty has no button. gpiozero (the device dependency group, Linux) is imported only when a button is opened.
"""
import logging
from typing import Any, Callable, Mapping

from .base import Emit
from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.05
# a press held this long is also a `long-press`
LONG_PRESS_SECONDS = 1.0
# the inputs: the name in events, the setting that holds its pin, what it is called to a person
INPUTS = (
	("play-stop", "buttonPlayStop", "play/stop button"),
	("next", "buttonNext", "next button"),
	("stop", "buttonStop", "stop button"),
)
LABELS: Mapping[str, str] = { name: label for name, _, label in INPUTS }

def load_button() -> Any:
	"""gpiozero's `Button`, or a `PermanentError` that says, in our words, what to do."""
	try:
		from gpiozero import Button
	except ImportError as e:
		raise PermanentError("The buttons need the device libraries (`uv sync --group device`, Raspberry Pi only). On another machine leave the button pins empty in the Devices settings.") from e
	return Button

def _callback(emit: Emit, name: str, gesture: str) -> Callable[[], None]:
	# gpiozero looks at the number of parameters a callback takes: this one takes none
	def called() -> None:
		emit(name, gesture)
	return called

class Buttons:
	"""`factory` makes a gpiozero-style button (a test gives a fake one); by default it is gpiozero's."""
	id = "buttons"

	def __init__(self, factory: Callable[..., Any]|None = None):
		self._factory = factory
		self._buttons: list[Any] = []

	def pins(self, config: Mapping[str, Any]) -> dict[str, int]:
		found: dict[str, int] = {}
		for name, key, _ in INPUTS:
			pin = config.get(key)
			if isinstance(pin, int) and not isinstance(pin, bool):
				found[name] = pin
		return found

	def open(self, emit: Emit, config: Mapping[str, Any]) -> None:
		pins = self.pins(config)
		factory = self._factory or load_button()
		try:
			for name, pin in pins.items():
				button = factory(pin, pull_up=True, bounce_time=DEBOUNCE_SECONDS, hold_time=LONG_PRESS_SECONDS)
				self._buttons.append(button)
				button.when_pressed = _callback(emit, name, "press")
				button.when_held = _callback(emit, name, "long-press")
				logger.info(f"The {LABELS[name]} is on pin {pin}.")
		except Exception as e:
			self.close()
			logger.error(f"A button could not be opened: {e}", exc_info=True)
			raise PermanentError("A button could not be opened. Check that nothing else uses its pin, the wiring and that GPIO is available to the app. The log has the detail.") from e

	def close(self) -> None:
		buttons, self._buttons = self._buttons, []
		for button in buttons:
			try:
				button.close()
			except Exception:
				logger.debug("a button did not close cleanly", exc_info=True)
