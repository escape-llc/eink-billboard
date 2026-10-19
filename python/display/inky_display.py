"""
The Pimoroni Inky panel (#281), "auto mode": the driver reads the board's EEPROM and says which Inky it is (pHAT, wHAT, Impression, Spectra...), and its size is the display's resolution.

The driver (`inky`, with `spidev`, `smbus2` and `gpiod`) is part of the `device` dependency group, Linux only: it is imported **here, when the display is made**, never at the top of a
module, so Windows, the container and a Pi without it all start (`test_pyproject`). The Display task owns this display like the others: it makes it, asks for its resolution, draws
on it (`render` is slow, an e-ink refresh takes seconds, and runs off the event loop; the driver stage guards it with a time, `panel_guard.py`) and shuts it down. When the driver cannot be loaded the display does not start, and the message
here is what the web app's status says (the messages are ours: they reach the status as they are, see `PermanentError`).
"""
import importlib
import inspect
import logging
import sys
import threading
from typing import Any, Callable

from PIL import Image

from .display_base import DisplayBase
from .panel_guard import PanelGuard
from ..model.configuration_manager import ConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import to_rgb

DEFAULT_SATURATION = 0.5
# the border colours the settings offer (python/displays/inky/display-info.json); which of them a board has is the driver's to say
BORDER_COLORS = ("white", "black", "red", "yellow", "green", "blue", "orange")
# the longest a refresh may take (the 7-color Impression takes about 35 seconds); some models wait on the busy line for good (panel_guard.py)
REFRESH_SECONDS = 180.0
START_SECONDS = 60.0

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

def border_constant(device: Any, name: str) -> int|None:
	"""
	The number the driver's `set_border` takes for a color name: the constant of that name in the **module of the board's own class** (or the one it inherits from). Not the class attribute of the same name and not
	`inky.BLACK`: each model numbers its colors differently (a pHAT has white 0 and black 1, an Impression black 0 and white 1, and the Spectra boards' class attributes disagree with their module's, which is what
	`set_border` checks), so the name is looked up in the board's own module. None when the model has no such color.
	"""
	for cls in type(device).__mro__:
		value = getattr(sys.modules.get(cls.__module__), name.upper(), None)
		if isinstance(value, int) and not isinstance(value, bool):
			return value
	return None

class InkyDisplay(DisplayBase):
	"""`loader` makes the driver's board (a test gives a fake one); by default it is `load_driver`."""
	def __init__(self, name: str, loader: Callable[[], Any]|None = None, refresh_seconds: float = REFRESH_SECONDS, start_seconds: float = START_SECONDS):
		super().__init__(name)
		self._loader = loader or load_driver
		self._refresh_seconds = refresh_seconds
		self._start_seconds = start_seconds
		self._guard = PanelGuard("inky")
		self.device: Any = None
		# the border colors already said to be unavailable on this board (said once, not at every refresh)
		self._border_noted: set[str] = set()
		self.display_settings: dict[str, Any] = {}
		self.resolution: tuple[int, int] = (0, 0)
		# one refresh at a time: the SPI bus and the busy pin are one panel's
		self._lock = threading.Lock()
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		self.logger.info(f"'{self.name}' initialize")
		_, stored = cm.settings_manager().open("display").get()
		self.display_settings = dict(stored or {})
		self.start_gate(self.display_settings)
		try:
			self.device = self._guard.run(self._loader, self._start_seconds)
		except PermanentError:
			raise
		except TimeoutError as e:
			raise PermanentError("The Inky display did not answer when it was started. Check the wiring and that SPI and I2C are enabled (raspi-config), then restart. The log has the detail.") from e
		except Exception as e:
			raise PermanentError("The Inky display could not be started. The log has the detail.") from e
		try:
			self.resolution = (int(self.device.width), int(self.device.height))
		except (AttributeError, TypeError, ValueError) as e:
			raise PermanentError("The Inky driver did not say how big the display is.") from e
		self.logger.info(f"'{self.name}' found a {self.resolution[0]}x{self.resolution[1]} panel ({type(self.device).__name__})")
		return self.resolution

	def saturation(self) -> float:
		value = self.display_settings.get("saturation", DEFAULT_SATURATION)
		return min(max(float(value), 0.0), 1.0) if isinstance(value, (int, float)) and not isinstance(value, bool) else DEFAULT_SATURATION

	def border_color(self) -> str|None:
		"""The border color the settings choose, or None when it is not set (or not one we know): the driver's own is then left as it is."""
		value = self.display_settings.get("borderColor")
		return value if isinstance(value, str) and value in BORDER_COLORS else None

	def _set_border(self, device: Any) -> None:
		"""Give the board its border color before the refresh. A board that has no such color (or no border at all) keeps the driver's own, and the log says so once: never a failed refresh."""
		name = self.border_color()
		if name is None or not callable(getattr(device, "set_border", None)):
			return
		value = border_constant(device, name)
		if value is not None:
			device.set_border(value)
		if (value is None or getattr(device, "border_colour", value) != value) and name not in self._border_noted:
			self._border_noted.add(name)
			self.logger.warning(f"'{self.name}' this board has no {name} border: its own is kept.")

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
			device = self.device
			def refresh() -> None:
				self._set_border(device)
				if "saturation" in inspect.signature(device.set_image).parameters:
					device.set_image(picture, saturation=self.saturation())
				else:
					device.set_image(picture)
				device.show()
			# the panel's rest after its last refresh: too soon is refused (TooSoon); the rest starts again when this send ends, however it ends
			self.gate.begin()
			try:
				self._guard.run(refresh, self._refresh_seconds)
			except TimeoutError:
				raise RuntimeError(f"The panel did not finish refreshing in {self._refresh_seconds:g} seconds. Check the wiring and the busy line.") from None
			finally:
				self.gate.finish()

	def shutdown(self) -> None:
		# the driver holds the SPI and GPIO lines until it is collected; the panel keeps what it shows with no power
		with self._lock:
			self.device = None
