"""
A pretend Raspberry Pi with a Waveshare panel for the `app-waveshare` container (#281's twin for Waveshare): `python -m scripts.fake_waveshare <the server's options>`.

The vendored Waveshare driver (`python/display/waveshare_epd/`) really runs. Its `epdconfig` looks at the board when it is imported (it asks `/proc/cpuinfo` whether this is a Raspberry Pi,
and on anything else builds the Jetson's pins, which fails), then drives the panel through `gpiozero` pins and a `spidev` bus. A container has none of these, so this module answers for
them: the shell's `cat /proc/cpuinfo | grep Raspberry`, `spidev.SpiDev` and `gpiozero.LED`/`Button` (the busy line), then starts the server as `python -m python.eink-billboard` does.
Choose `waveshare` as the Display Type and a model in the Display settings, then restart.

`EINK_FAKE_WAVESHARE` says what the pretend panel does:
- `ok`: the panel draws at once; the last image the driver was given is saved as `fake-waveshare-last.png` in `EINK_FAKE_WAVESHARE_OUT` (default `/tmp/fake-waveshare`);
- `busy-stuck`: the busy line stays low, so a driver that waits for it to rise (the 7.3 inch `epd7in3e` is one) waits for good, as it would on a panel that never answers: the display
  gives the refresh a time, reports it and refuses the next ones;
- `spi-off`: the SPI bus does not exist (the interface is not enabled): the display fails to start;
- anything else, or nothing: no pretending: the driver finds no Raspberry Pi and says so.

Nothing here is imported by the application: it is only in the `app-waveshare` service's command.
"""
import functools
import importlib
import logging
import os
import runpy
import subprocess
import sys
import time
from typing import Any

MODES = ("ok", "busy-stuck", "spi-off")

logger = logging.getLogger("fake_waveshare")

def mode_of(value: str|None) -> str|None:
	"""The pretend panel's mode, or None for no pretending (an unknown word included)."""
	return value if value in MODES else None

def install(mode: str, out_dir: str) -> None:
	"""Put the pretend board in place; call it before the server starts (the driver looks at the board when its module is imported)."""
	import gpiozero
	import spidev

	real_popen = subprocess.Popen

	class FakeProcess:
		def communicate(self, *a: Any, **k: Any) -> tuple[str, None]:
			return "Hardware\t: BCM2835\nModel\t\t: Raspberry Pi 4 Model B (pretend)\n", None

	def popen(args: Any, *a: Any, **k: Any) -> Any:
		# the one question epdconfig asks the shell at import: is this a Raspberry Pi?
		if isinstance(args, str) and "cpuinfo" in args and "Raspberry" in args:
			return FakeProcess()
		return real_popen(args, *a, **k)
	subprocess.Popen = popen  # type: ignore[misc,assignment]

	class FakeSpi:
		max_speed_hz = 0
		mode = 0
		def open(self, bus: int, channel: int) -> None:
			if mode == "spi-off":
				raise FileNotFoundError(2, f"No such file or directory: /dev/spidev{bus}.{channel}")
			logger.info("SPI %s.%s opened (pretend)", bus, channel)
		def writebytes(self, data: Any) -> None:
			pass
		def writebytes2(self, data: Any) -> None:
			pass
		def readbytes(self, n: int) -> list[int]:
			return [0] * n
		def close(self) -> None:
			pass

	class FakeLed:
		def __init__(self, pin: int):
			self.pin = pin
		def on(self) -> None:
			pass
		def off(self) -> None:
			pass
		def close(self) -> None:
			pass

	class FakeButton:
		"""The busy line. Read after read it is low, then high: a driver that waits for either level gets it (and `busy-stuck` leaves it low for good)."""
		def __init__(self, pin: int, pull_up: bool = False):
			self.pin = pin
			self._reads = 0
		@property
		def value(self) -> int:
			if mode == "busy-stuck":
				return 0
			self._reads += 1
			return self._reads % 2
		def close(self) -> None:
			pass

	spidev.SpiDev = FakeSpi  # type: ignore[misc]
	gpiozero.LED = FakeLed  # type: ignore[misc,assignment]
	gpiozero.Button = FakeButton  # type: ignore[misc,assignment]

	real_import = importlib.import_module
	def import_module(name: str, package: str|None = None) -> Any:
		module = real_import(name, package)
		model = getattr(module, "EPD", None)
		if name.rsplit(".", 1)[-1].startswith("epd") and not name.endswith("epdconfig") and model is not None and not getattr(model, "_pretend", False):
			remember(model)
		return module
	importlib.import_module = import_module

	def remember(model: Any) -> None:
		"""Keep the picture the display gives the driver (`getbuffer`), and say when a refresh starts and ends."""
		getbuffer, display = model.getbuffer, model.display
		@functools.wraps(getbuffer)
		def saving(self: Any, image: Any, *a: Any, **k: Any) -> Any:
			try:
				os.makedirs(out_dir, exist_ok=True)
				image.convert("RGB").save(os.path.join(out_dir, "fake-waveshare-last.png"), "PNG")
			except (OSError, AttributeError) as e:
				logger.warning("The last image could not be saved (%s).", type(e).__name__)
			return getbuffer(self, image, *a, **k)
		@functools.wraps(display)
		def timed(self: Any, *buffers: Any) -> Any:
			started = time.monotonic()
			logger.info("refresh started (pretend)")
			try:
				return display(self, *buffers)
			finally:
				logger.info("refresh ended after %.1fs (pretend)", time.monotonic() - started)
		model.getbuffer, model.display, model._pretend = saving, timed, True

def main() -> None:
	mode = mode_of(os.environ.get("EINK_FAKE_WAVESHARE"))
	# the application configures logging itself once it starts; these lines come before it
	if mode is None:
		print(f"fake_waveshare: EINK_FAKE_WAVESHARE is not one of {', '.join(MODES)}: no pretend board, the driver will find no Raspberry Pi.", file=sys.stderr, flush=True)
	else:
		print(f"fake_waveshare: pretend Raspberry Pi with a Waveshare panel, mode '{mode}'.", file=sys.stderr, flush=True)
		install(mode, os.environ.get("EINK_FAKE_WAVESHARE_OUT", "/tmp/fake-waveshare"))
	sys.argv[0] = "python.eink-billboard"
	runpy.run_module("python.eink-billboard", run_name="__main__")

if __name__ == "__main__":
	main()
