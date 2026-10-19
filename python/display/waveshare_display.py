"""
A Waveshare e-Paper panel: one of the 65 models whose official drivers are vendored in `python/display/waveshare_epd/` (VENDORED.md). Unlike an Inky there is no auto-detect: the Display
settings name the model (`model`, Waveshare's own module name: `epd7in3e`, `epd4in2_V2`, ...).

The drivers import `RPi.GPIO`, `gpiozero` and `spidev`, which only a Raspberry Pi has (the `device` dependency group, Linux): the model's module is imported **here, when the display is made**,
never at the top of a module, so Windows, the container and a Pi without them all start (`test_pyproject`). The module's name comes from our own list of the vendored files (`MODELS`), never from
the setting's text. The Display task owns this display like the others; when it cannot start, the messages here are ours and are the status the web app shows.

A Waveshare driver waits for the panel's busy line with a loop that has no end of its own: a panel that never answers would hold the Display task's drawing thread for good. `render` therefore
gives a refresh a time (`REFRESH_SECONDS`) and, once one has not come back, refuses the next ones with a message instead of piling threads on a stuck bus.
"""
import importlib
import inspect
import logging
import os
import re
import threading
from typing import Any, Callable

from PIL import Image

from .display_base import DisplayBase
from .panel_guard import PanelGuard
from ..model.configuration_manager import ConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import to_rgb

EPD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "waveshare_epd")
# the longest a refresh may take: the slowest panels (color, large) take about 30 seconds
REFRESH_SECONDS = 180.0
# and to start (it waits for the busy line too): the device is not held up longer than this by a panel that is not there
START_SECONDS = 60.0

def model_names() -> tuple[str, ...]:
	"""The models the vendored drivers have (`epd7in3e`, ...): the files of the folder, not the setting."""
	found = [f[:-3] for f in os.listdir(EPD_FOLDER) if re.fullmatch(r"epd\d[0-9a-zA-Z_]*\.py", f)]
	return tuple(sorted(found))

MODELS = model_names()

def load_model(model: Any) -> Any:
	"""The driver module of the model (a name from `MODELS`), or a `PermanentError` that says, in our words, what to do."""
	chosen = next((m for m in MODELS if m == model), None)
	if chosen is None:
		raise PermanentError("Choose the Waveshare display's model in the Display settings (Waveshare Model), then restart." if not model
			else "That is not one of the Waveshare models this device has drivers for. Choose one in the Display settings (Waveshare Model), then restart.")
	try:
		return importlib.import_module(f"{__package__}.waveshare_epd.{chosen}")
	except ImportError as e:
		raise PermanentError(f"The Waveshare driver for {chosen} could not be loaded: it needs the device libraries (`uv sync --group device`, Raspberry Pi only). "
			"On another machine choose the mock or tk display in the Display settings.") from e
	except Exception as e:
		# the driver looks at its board when it is imported (epdconfig): on a machine that is none of the boards it knows it fails with what it likes (a RuntimeError about a library, an OSError)
		raise PermanentError(f"The Waveshare driver for {chosen} could not start here: it is made for a Raspberry Pi and found none. "
			"On another machine choose the mock or tk display in the Display settings. The log has the detail.") from e

def split_for_bi_color(image: Image.Image) -> tuple[Image.Image, Image.Image]:
	"""A black-white-red panel takes two 1-bit layers: the black ink and the red ink, each 0 where the ink goes."""
	palette = Image.new("P", (1, 1))
	palette.putpalette([0, 0, 0, 255, 255, 255, 255, 0, 0])
	indexed = image.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
	black = indexed.point(lambda p: 0 if p == 0 else 1, mode="1")
	red = indexed.point(lambda p: 0 if p == 2 else 1, mode="1")
	return black, red

class WaveshareDisplay(DisplayBase):
	"""`loader` gives the model's driver module (a test gives a fake one); by default it is `load_model`."""
	def __init__(self, name: str, loader: Callable[[Any], Any]|None = None, refresh_seconds: float = REFRESH_SECONDS, start_seconds: float = START_SECONDS):
		super().__init__(name)
		self._loader = loader or load_model
		self._refresh_seconds = refresh_seconds
		self._start_seconds = start_seconds
		self.module: Any = None
		self.epd: Any = None
		self.resolution: tuple[int, int] = (0, 0)
		# a refresh that has not come back (a panel that never says it is done): nothing else is sent to the bus until it has
		self._guard = PanelGuard("waveshare")
		self._lock = threading.Lock()
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		self.logger.info(f"'{self.name}' initialize")
		_, settings = cm.settings_manager().open("display").get()
		model = (settings or {}).get("model")
		self.start_gate(settings)
		self.module = self._loader(model)
		try:
			self.epd = self.module.EPD()
			start = getattr(self.epd, "init", None) or getattr(self.epd, "Init", None)
			if not callable(start):
				raise PermanentError("The Waveshare driver has no way to start the panel.")
			self._guard.run(start, self._start_seconds)
			self.resolution = (int(self.epd.width), int(self.epd.height))
		except PermanentError:
			raise
		except TimeoutError as e:
			# the driver waits for the panel's busy line with a loop that has no end: a panel that is not there, or wired wrong, never lets it go
			raise PermanentError("The Waveshare panel did not answer when it was started. Check the wiring and the busy line, that SPI is enabled and that the model is the right one, then restart. The log has the detail.") from e
		except Exception as e:
			raise PermanentError("The Waveshare display could not be started. Check the wiring and that SPI is enabled (raspi-config), then restart. The log has the detail.") from e
		self.logger.info(f"'{self.name}' {model}: {self.resolution[0]}x{self.resolution[1]}")
		return self.resolution

	def _buffers(self, picture: Image.Image) -> tuple[Callable[..., Any], list[Any]]:
		"""The driver's `display` and what it takes: one buffer, or the black and the red layers of a three-color panel."""
		display = getattr(self.epd, "display", None) or getattr(self.epd, "display_1Gray", None)
		if not callable(display):
			raise RuntimeError("The Waveshare driver has no `display`.")
		# the buffers it takes (a bound method: `self` is not counted; a wrapper that says what it wraps counts as what it wraps)
		if len(inspect.signature(display).parameters) == 2:
			black, red = split_for_bi_color(picture)
			return display, [self.epd.getbuffer(black), self.epd.getbuffer(red)]
		return display, [self.epd.getbuffer(picture)]

	def render(self, img: Image.Image, id: int, title: str|None = None) -> None:
		if self.epd is None:
			raise RuntimeError("The Waveshare display was not initialized")
		self.logger.info(f"'{self.name}' render id={id} title='{title}' img={img.width}x{img.height}")
		picture = to_rgb(img).convert("RGB")
		if picture.size != self.resolution:
			self.logger.warning(f"'{self.name}' the image is {picture.width}x{picture.height}, the panel {self.resolution[0]}x{self.resolution[1]}: resized")
			picture = picture.resize(self.resolution, Image.Resampling.LANCZOS)
		with self._lock:
			display, buffers = self._buffers(picture)
			def refresh() -> None:
				# the panel is started again for each picture (a model that sleeps between pictures needs it) and put to sleep after (an e-paper keeps its picture with no power)
				start = getattr(self.epd, "init", None) or getattr(self.epd, "Init", None)
				if callable(start):
					start()
				display(*buffers)
				sleep = getattr(self.epd, "sleep", None)
				if callable(sleep):
					sleep()
			# the panel's rest after its last refresh: too soon is refused (TooSoon); the rest starts again when this send ends, however it ends
			self.gate.begin()
			try:
				self._guard.run(refresh, self._refresh_seconds)
			except TimeoutError:
				raise RuntimeError(f"The panel did not finish refreshing in {self._refresh_seconds:g} seconds. Check the wiring and the busy line.") from None
			finally:
				self.gate.finish()

	def shutdown(self) -> None:
		with self._lock:
			epdconfig = getattr(self.module, "epdconfig", None)
			try:
				if epdconfig is not None and callable(getattr(epdconfig, "module_exit", None)):
					epdconfig.module_exit()
			except Exception:
				self.logger.debug("the Waveshare bus could not be released", exc_info=True)
			self.epd = None
