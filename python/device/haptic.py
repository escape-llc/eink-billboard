"""
A haptic output (#867, #891): a vibration motor driven by a TI DRV2605 (or DRV2605L) on the Pi's I²C bus, such as Seeed's Grove Haptic Motor on the Inky Impression's Qw/ST socket. It is
felt only while touching the device, so it suits the buttons. It does not hold: every cue plays once, from the chip's own library of effects (a click, a double click, a buzz).

The chip is reached with `smbus2` (pure Python, already brought by the `inky` package; the device dependency group, Linux), imported only when the output is opened. Its registers are the
datasheet's (TI SLOS854): the motor is an ERM (eccentric rotating mass), so the ERM library and open loop are chosen.

A module unplugged while open (#906) makes a cue raise our `PermanentError` (the player says it once); plugged in again it starts with the chip's own defaults, so its settings are
written again before the next cue.
"""
import logging
import threading
from typing import Any, Callable, Mapping

from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

# the Pi's I²C bus on the header (pins 2 and 3), and the chip's fixed address
BUS = 1
ADDRESS = 0x5A
# the chip's registers
STATUS, MODE, RTP, LIBRARY, SEQUENCE, GO, FEEDBACK, CONTROL3 = 0x00, 0x01, 0x02, 0x03, 0x04, 0x0C, 0x1A, 0x1D
# STATUS bits 7..5 say which chip answered: DRV2605, DRV2604, DRV2604L, DRV2605L
CHIP_IDS = (3, 4, 6, 7)
# MODE: internal trigger (a write to GO plays the sequence), or standby
INTERNAL_TRIGGER, STANDBY = 0x00, 0x40
# LIBRARY 1: the ERM library A
ERM_LIBRARY = 1
# the sequence has eight slots; a slot with its top bit set is a wait of (its value x 10 ms)
SLOTS = 8
def wait(ms: int) -> int:
	return 0x80 | min(ms // 10, 0x7F)

# each cue as the library's effects (the datasheet's list: 1 strong click, 10 double click, 12 triple click, 14 strong buzz, 47 buzz, 52 pulsing strong)
EFFECTS: Mapping[str, tuple[int, ...]] = {
	"off": (),
	"one": (1,),
	"two": (10,),
	"three": (12,),
	"steady": (14,),
	"slow": (52,),
	"fast": (47, wait(100), 47, wait(100), 47),
	"heartbeat": (1, wait(120), 1),
	# a clock's strike, and a Westminster change as four clicks (eight slots: the waits are slots too)
	"bell": (1, wait(600)),
	**{ f"change-{n}": (1, wait(150), 1, wait(150), 1, wait(150), 1, wait(500)) for n in range(1, 6) },
}
# how long a sequence may take before the chip is told to stop (the longest is about a second)
LONGEST_SECONDS = 3.0
POLL_SECONDS = 0.01

def load_bus() -> Callable[[int], Any]:
	"""smbus2's `SMBus`, or a `PermanentError` that says, in our words, what to do."""
	try:
		from smbus2 import SMBus
	except ImportError as e:
		raise PermanentError("A haptic output needs the device libraries (`uv sync --group device`, Raspberry Pi only).") from e
	return SMBus

class HapticRenderer:
	"""`bus_factory` opens the I²C bus by its number (smbus2's `SMBus`; a test gives a fake one)."""
	holds = False

	def __init__(self, bus_factory: Callable[[int], Any]|None = None):
		make = bus_factory or load_bus()
		try:
			self._bus = make(BUS)
		except OSError as e:
			raise PermanentError("There is no I²C bus: turn on I²C (raspi-config, Interface Options) and check that the app is given /dev/i2c-1.") from e
		try:
			status = self._bus.read_byte_data(ADDRESS, STATUS)
		except OSError as e:
			self._close_bus()
			raise PermanentError(f"No haptic driver answers on the I²C bus (address 0x{ADDRESS:02X}): check the Qw/ST cable and the module.") from e
		if (status >> 5) not in CHIP_IDS:
			self._close_bus()
			raise PermanentError(f"The chip at address 0x{ADDRESS:02X} is not a DRV2605 haptic driver.")
		try:
			self._configure()
		except OSError as e:
			self._close_bus()
			raise PermanentError("The haptic driver did not take its settings: check the Qw/ST cable.") from e
		# the chip stopped answering (unplugged): its settings are written again before the next cue
		self._lost = False
		logger.info(f"The haptic driver at 0x{ADDRESS:02X} is open.")

	def _configure(self) -> None:
		self._bus.write_byte_data(ADDRESS, MODE, INTERNAL_TRIGGER)
		self._bus.write_byte_data(ADDRESS, RTP, 0)
		self._bus.write_byte_data(ADDRESS, LIBRARY, ERM_LIBRARY)
		# an ERM motor (N_ERM_LRA clear), driven open loop (ERM_OPEN_LOOP set)
		self._bus.write_byte_data(ADDRESS, FEEDBACK, self._bus.read_byte_data(ADDRESS, FEEDBACK) & 0x7F)
		self._bus.write_byte_data(ADDRESS, CONTROL3, self._bus.read_byte_data(ADDRESS, CONTROL3) | 0x20)

	def play(self, cue: str, stop: threading.Event, seconds: float, options: Mapping[str, Any]|None = None) -> bool:
		"""The cue's effects, once; True when `stop` was set before they ended (the chip is stopped)."""
		effects = EFFECTS.get(cue, ())
		if not effects:
			return False
		try:
			return self._play(effects, stop)
		except OSError as e:
			self._lost = True
			raise PermanentError(f"The haptic driver stopped answering on the I²C bus (address 0x{ADDRESS:02X}): check the Qw/ST cable and the module.") from e

	def _play(self, effects: tuple[int, ...], stop: threading.Event) -> bool:
		if self._lost:
			self._configure()
			self._lost = False
		for slot in range(SLOTS):
			self._bus.write_byte_data(ADDRESS, SEQUENCE + slot, effects[slot] if slot < len(effects) else 0)
		self._bus.write_byte_data(ADDRESS, GO, 1)
		waited = 0.0
		# the chip clears GO when the sequence is over
		while self._bus.read_byte_data(ADDRESS, GO) & 1 and waited < LONGEST_SECONDS:
			if stop.wait(POLL_SECONDS):
				self.off()
				return True
			waited += POLL_SECONDS
		return False

	def off(self) -> None:
		self._bus.write_byte_data(ADDRESS, GO, 0)

	def close(self) -> None:
		try:
			self._bus.write_byte_data(ADDRESS, MODE, STANDBY)
		finally:
			self._close_bus()

	def _close_bus(self) -> None:
		try:
			self._bus.close()
		except Exception:
			logger.debug("The I²C bus did not close cleanly", exc_info=True)
