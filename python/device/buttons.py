"""
Push buttons on the header's GPIO pins: each wired between its pin and ground (the pin's internal pull-up holds it high; a press pulls it low), with a short debounce. There is a button for
each row of the GPIO settings' `triggers` (its pin; what it does is the row's `action`, decided by the Application, not here). A button is named for its pin (`gpio-5`).
gpiozero (the device dependency group, Linux) is imported only when a button is opened.
"""
import logging
from typing import Any, Callable, Mapping

from .base import Emit
from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.05
# a press held this long is also a `long-press`
LONG_PRESS_SECONDS = 1.0

def input_name(pin: int) -> str:
	"""The name of the button on `pin` in events (`InputEvent.name`) and in the pin checks."""
	return f"gpio-{pin}"

def input_label(name: str) -> str:
	"""What a button is called to a person: `gpio-5` is "button on pin 5"."""
	return f"button on pin {name.removeprefix('gpio-')}" if name.startswith("gpio-") else name

def physical_words(name: str, gesture: str) -> str:
	"""What a pin did, in our words, before anything decides what it means (`pressed`, `released`, `held`): the live view of the wiring."""
	what = { "press": "pressed", "release": "released", "long-press": "held" }.get(gesture, gesture)
	return f"{name.replace('gpio-', 'GPIO ', 1) if name.startswith('gpio-') else name}: {what}"

def load_button() -> Any:
	"""gpiozero's `Button`, or a `PermanentError` that says, in our words, what to do."""
	try:
		from gpiozero import Button
	except ImportError as e:
		raise PermanentError("The buttons need the device libraries (`uv sync --group device`, Raspberry Pi only). On another machine leave the button pins empty in the GPIO settings.") from e
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
		rows = config.get("triggers")
		for row in rows if isinstance(rows, list) else []:
			pin = row.get("pin") if isinstance(row, dict) else None
			if isinstance(pin, int) and not isinstance(pin, bool):
				found[input_name(pin)] = pin
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
				button.when_released = _callback(emit, name, "release")
				logger.info(f"The {input_label(name)} is open.")
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
