"""
The Pimoroni Inky panel (#281), "auto mode": the driver reads the board's EEPROM and says which Inky it is (pHAT, wHAT, Impression, Spectra...), and its size is the display's resolution.

The driver (`inky`, with `spidev`, `smbus2` and `gpiod`) is part of the `device` dependency group, Linux only: it is imported **here, when the display is made**, never at the top of a
module, so Windows, the container and a Pi without it all start (`test_pyproject`). The Display task owns this display like the others: it makes it, asks for its resolution, draws
on it (`render` is slow, an e-ink refresh takes seconds, and runs off the event loop) and shuts it down. When the driver cannot be loaded the display does not start, and the message
here is what the web app's status says (the messages are ours: they reach the status as they are, see `PermanentError`).
"""
import importlib
import inspect
import logging
import threading
from typing import Any, Callable

from PIL import Image

from .display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import to_rgb

DEFAULT_SATURATION = 0.5

def load_driver() -> Any:
	"""The board the driver finds (`inky.auto.auto`), or a `PermanentError` that says, in our words, what is wrong and what to do about it."""
	try:
		auto = importlib.import_module("inky.auto").auto
	except ImportError as e:
		raise PermanentError("The Inky driver is not installed. It is part of the device install (`uv sync --group device`, Raspberry Pi only); "
			"on another machine choose the mock or tk display in the Display settings.") from e
	try:
		return auto(ask_user=False, verbose=False)
	except Exception as e:
		if "find a driver" in str(e):
			# the EEPROM answered, with a board this version of the driver has no class for (the driver's own words: "Can't find a driver this display")
			raise PermanentError("An Inky display answered, but this version of the Inky driver does not support it. Update the driver (`uv sync --group device`) and restart. The log has the detail.") from e
		# no board answered (nothing attached, or I2C is off)
		raise PermanentError("No Inky display was found. Check that it is attached and that SPI and I2C are enabled (raspi-config), then restart. The log has the detail.") from e

class InkyDisplay(DisplayBase):
	"""`loader` makes the driver's board (a test gives a fake one); by default it is `load_driver`."""
	def __init__(self, name: str, loader: Callable[[], Any]|None = None):
		super().__init__(name)
		self._loader = loader or load_driver
		self.device: Any = None
		self.display_settings: dict[str, Any] = {}
		self.resolution: tuple[int, int] = (0, 0)
		# one refresh at a time: the SPI bus and the busy pin are one panel's
		self._lock = threading.Lock()
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		self.logger.info(f"'{self.name}' initialize")
		_, stored = cm.settings_manager().open("display").get()
		self.display_settings = dict(stored or {})
		try:
			self.device = self._loader()
		except PermanentError:
			raise
		except Exception as e:
			raise PermanentError("The Inky display could not be started. The log has the detail.") from e
		try:
			self.resolution = (int(self.device.width), int(self.device.height))
		except (AttributeError, TypeError, ValueError) as e:
			raise PermanentError("The Inky driver did not say how big the display is.") from e
		self.logger.info(f"'{self.name}' found a {self.resolution[0]}x{self.resolution[1]} panel ({type(self.device).__name__})")
		return self.resolution

	def saturation(self) -> float:
		value = self.display_settings.get("inky-saturation", DEFAULT_SATURATION)
		return min(max(float(value), 0.0), 1.0) if isinstance(value, (int, float)) and not isinstance(value, bool) else DEFAULT_SATURATION

	def render(self, img: Image.Image, id: int, title: str|None = None) -> None:
		if self.device is None:
			raise RuntimeError("The Inky display was not initialized")
		self.logger.info(f"'{self.name}' render id={id} title='{title}' img={img.width}x{img.height}")
		picture = to_rgb(img)
		if picture.size != self.resolution:
			# the display task makes images of the panel's size; anything else is fitted rather than refused (the driver raises on a size that differs)
			self.logger.warning(f"'{self.name}' the image is {picture.width}x{picture.height}, the panel {self.resolution[0]}x{self.resolution[1]}: resized")
			picture = picture.resize(self.resolution, Image.Resampling.LANCZOS)
		with self._lock:
			# only the 7-colour boards take a saturation (their palette is blended with it); the others quantize to their own colors
			if "saturation" in inspect.signature(self.device.set_image).parameters:
				self.device.set_image(picture, saturation=self.saturation())
			else:
				self.device.set_image(picture)
			self.device.show()

	def shutdown(self) -> None:
		# the driver holds the SPI and GPIO lines until it is collected; the panel keeps what it shows with no power
		with self._lock:
			self.device = None
