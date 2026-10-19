"""
What a device connected to the Pi's own lines (GPIO, I2C, SPI) looks like to the `DeviceIO` task, which owns those lines. A device is asked for its pins first (so they can be checked against the
panel's), then opened with a function to report what happens at it, and closed. The libraries that talk to the hardware are imported only inside `open` (the device dependency group).
"""
from typing import Any, Callable, Mapping, Protocol

# what a device calls when something happens at one of its inputs: the input's name and the gesture. May be called from any thread.
type Emit = Callable[[str, str], None]

class InputDevice(Protocol):
	# the device's name in events (`InputEvent.source`) and in the settings
	id: str
	def pins(self, config: Mapping[str, Any]) -> dict[str, int]:
		"""The GPIO pins the settings give this device, by the name of the input (none when it is not set up). Nothing is opened to tell."""
		...
	def open(self, emit: Emit, config: Mapping[str, Any]) -> None:
		"""Start listening. Raises (a `PermanentError` in our words for a missing library or an input that cannot be opened) and leaves nothing open when it does."""
		...
	def close(self) -> None:
		...
