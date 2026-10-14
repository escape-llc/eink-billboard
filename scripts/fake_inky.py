"""
A pretend Inky board for the `app-inky` container (#281), to troubleshoot what the device does when the driver gets farther than "no board": `python -m scripts.fake_inky <the server's options>`.

The real `inky` driver is installed in that image (the `device` dependency group) and really runs: `inky.auto.auto()` reads the board's EEPROM over I2C, the driver sets up its GPIO
lines and its SPI bus, sends the image and waits for the busy line. A container has none of these, so this module replaces the four things that touch hardware (`smbus2.SMBus`,
`gpiodevice`'s chip and edge wait, `spidev.SpiDev`) with objects that answer like a board would, then starts the server as `python -m python.eink-billboard` does.

`EINK_FAKE_INKY` says what the pretend board does:
- `ok`: a 7-color Impression (600x448, EEPROM variant 14) that draws; the last image it was given is saved as `fake-inky-last.png` in `EINK_FAKE_INKY_OUT` (default `/tmp/fake-inky`: not the storage, whose watcher would hear of it; `podman cp` it out);
- `busy-stuck`: the same, but its busy line is held high, so every refresh waits out the driver's timeout (the driver warns "Busy Wait: Held high"): a slow panel;
- `spi-off`: the EEPROM answers, but the SPI bus does not exist (the interface is not enabled): the display starts, and the first draw fails;
- `unknown-board`: an EEPROM variant this driver version has no class for ("Can't find a driver this display"): the display says the board is not supported;
- anything else, or nothing: no fakes at all, the driver finds no board (a Pi with the board unplugged or I2C off).

Nothing here is imported by the application: it is only in the `app-inky` image's command.
"""
import logging
import os
import runpy
import struct
import sys
import time
from typing import Any

MODES = ("ok", "busy-stuck", "spi-off", "unknown-board")
# EEPROM display variants that matter here: (width, height) of the board the driver builds for them
VARIANT_7_COLOUR = 14
UNKNOWN_VARIANT = 99
COLOUR_7 = 5

logger = logging.getLogger("fake_inky")

def eeprom_bytes(variant: int, width: int, height: int, colour: int = COLOUR_7, pcb: int = 1) -> list[int]:
	"""The 29 bytes `inky.eeprom.EPDType.from_bytes` reads: width, height, colour, PCB variant, display variant and a write time (a Pascal string of 22)."""
	return list(struct.pack("<HHBBB22p", width, height, colour, pcb, variant, b"2026-01-01 00:00:00"))

def mode_of(value: str|None) -> str|None:
	"""The pretend board's mode, or None for no pretending (an unknown word included)."""
	return value if value in MODES else None

def install(mode: str, out_dir: str) -> None:
	"""Put the pretend hardware in place; call it before the server starts (the driver looks the pieces up when it is used)."""
	import gpiod.line as line
	import gpiodevice
	import smbus2
	import spidev

	variant = UNKNOWN_VARIANT if mode == "unknown-board" else VARIANT_7_COLOUR

	class FakeSMBus:
		def __init__(self, bus: int = 1):
			logger.info("I2C bus %s opened (pretend)", bus)
		def write_i2c_block_data(self, address: int, register: int, data: list[int]) -> None:
			pass
		def read_i2c_block_data(self, address: int, register: int, length: int) -> list[int]:
			return eeprom_bytes(variant, 600, 448)[:length]

	class FakeLines:
		def set_value(self, pin: int, value: Any) -> None:
			pass
		def get_value(self, pin: int) -> Any:
			# a busy line held high is what the driver treats as "no signal from the board": it waits out the whole timeout
			return line.Value.ACTIVE if mode == "busy-stuck" else line.Value.INACTIVE

	class FakeChip:
		def line_offset_from_id(self, pin: int) -> int:
			return pin
		def request_lines(self, consumer: str, config: dict) -> FakeLines:
			logger.info("GPIO lines requested by %s: %s (pretend)", consumer, sorted(config))
			return FakeLines()

	class FakeSpi:
		no_cs = False
		max_speed_hz = 0
		def open(self, bus: int, channel: int) -> None:
			if mode == "spi-off":
				raise FileNotFoundError(2, f"No such file or directory: /dev/spidev{bus}.{channel}")
			logger.info("SPI %s.%s opened (pretend)", bus, channel)
		def xfer3(self, values: list[int]) -> None:
			pass
		def close(self) -> None:
			pass

	smbus2.SMBus = FakeSMBus  # type: ignore[misc]
	spidev.SpiDev = FakeSpi  # type: ignore[misc]
	gpiodevice.find_chip_by_platform = lambda *a, **k: FakeChip()  # type: ignore[assignment]
	gpiodevice.check_pins_available = lambda *a, **k: True  # type: ignore[assignment]
	# a rising edge on the busy line, at once: the refresh "finished"
	gpiodevice.wait_for_edge = lambda lines, pin, timeout: object()  # type: ignore[assignment]

	from inky import inky_uc8159
	board = inky_uc8159.Inky
	set_image, show = board.set_image, board.show
	def remember(self: Any, image: Any, saturation: float = 0.5) -> None:
		set_image(self, image, saturation)
		try:
			os.makedirs(out_dir, exist_ok=True)
			image.save(os.path.join(out_dir, "fake-inky-last.png"), "PNG")
		except OSError as e:
			logger.warning("The last image could not be saved (%s).", type(e).__name__)
	def timed(self: Any, busy_wait: bool = True) -> None:
		started = time.monotonic()
		logger.info("refresh started (pretend)")
		show(self, busy_wait)
		logger.info("refresh done after %.1fs (pretend)", time.monotonic() - started)
	board.set_image = remember  # type: ignore[method-assign]
	board.show = timed  # type: ignore[method-assign]

def main() -> None:
	mode = mode_of(os.environ.get("EINK_FAKE_INKY"))
	# the application configures logging itself once it starts; these two lines come before it
	if mode is None:
		print(f"fake_inky: EINK_FAKE_INKY is not one of {', '.join(MODES)}: no pretend hardware, the driver will find no board.", file=sys.stderr, flush=True)
	else:
		print(f"fake_inky: pretend Inky board, mode '{mode}'.", file=sys.stderr, flush=True)
		install(mode, os.environ.get("EINK_FAKE_INKY_OUT", "/tmp/fake-inky"))
	sys.argv[0] = "python.eink-billboard"
	runpy.run_module("python.eink-billboard", run_name="__main__")

if __name__ == "__main__":
	main()
