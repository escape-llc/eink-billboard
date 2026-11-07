"""
The haptic output (#867): a DRV2605 on the I²C bus, set up for an ERM motor and played from its own library; on a Pi without the module it is said, in our words, and nothing is left open.
The bus here is a fake (no test needs the hardware).
"""
import threading
import unittest
from typing import Any

from ..device import haptic
from ..device.haptic import ADDRESS, CONTROL3, EFFECTS, FEEDBACK, GO, LIBRARY, MODE, SEQUENCE, SLOTS, STANDBY, STATUS, HapticRenderer
from ..device.cues import PLAYABLE
from ..plugins.plugin_base import PermanentError

class FakeBus:
	"""An I²C bus with a DRV2605L at 0x5A (or nothing, `present=False`); a sequence plays for `busy_reads` reads of GO."""
	def __init__(self, present: bool = True, chip_id: int = 7, busy_reads: int = 2):
		self.present = present
		self.registers: dict[int, int] = { STATUS: chip_id << 5, FEEDBACK: 0xB6, CONTROL3: 0xA0 }
		self.writes: list[tuple[int, int]] = []
		self.busy_reads = busy_reads
		self.busy = 0
		self.closed = False
	def read_byte_data(self, address: int, register: int) -> int:
		if not self.present or address != ADDRESS:
			raise OSError(121, "Remote I/O error")
		if register == GO:
			self.busy = max(0, self.busy - 1)
			return 1 if self.busy else 0
		return self.registers.get(register, 0)
	def write_byte_data(self, address: int, register: int, value: int) -> None:
		if not self.present or address != ADDRESS:
			raise OSError(121, "Remote I/O error")
		self.writes.append((register, value))
		self.registers[register] = value
		if register == GO and value == 1:
			self.busy = self.busy_reads
	def close(self) -> None:
		self.closed = True

def opened(bus: FakeBus) -> HapticRenderer:
	return HapticRenderer(lambda number: bus)

class TestHaptic(unittest.TestCase):
	def test_every_cue_is_a_sequence_that_fits_the_chip(self):
		self.assertEqual(set(EFFECTS), set(PLAYABLE))
		for cue, effects in EFFECTS.items():
			self.assertLessEqual(len(effects), SLOTS, cue)
			self.assertTrue(all(0 < e <= 0xFF for e in effects), cue)

	def test_it_is_set_up_for_an_erm_motor_from_its_library(self):
		bus = FakeBus()
		opened(bus)
		self.assertEqual(bus.registers[MODE], 0x00, "out of standby, played by a write to GO")
		self.assertEqual(bus.registers[LIBRARY], 1, "the ERM library")
		self.assertEqual(bus.registers[FEEDBACK] & 0x80, 0, "an ERM motor, not an LRA")
		self.assertEqual(bus.registers[CONTROL3] & 0x20, 0x20, "open loop")

	def test_a_cue_is_written_to_the_sequence_and_played_once(self):
		bus = FakeBus()
		renderer = opened(bus)
		bus.writes.clear()
		self.assertFalse(renderer.play("three", threading.Event(), 0.0))
		sequence = [value for register, value in bus.writes if SEQUENCE <= register < SEQUENCE + SLOTS]
		self.assertEqual(sequence, [12, 0, 0, 0, 0, 0, 0, 0], "a triple click, the rest of the slots cleared")
		self.assertEqual(bus.writes[-1], (GO, 1))
		bus.writes.clear()
		self.assertFalse(renderer.play("off", threading.Event(), 0.0))
		self.assertEqual(bus.writes, [], "Off plays nothing")

	def test_a_cue_cut_short_stops_the_chip(self):
		bus = FakeBus(busy_reads=1000)
		renderer = opened(bus)
		stop = threading.Event()
		stop.set()
		self.assertTrue(renderer.play("slow", stop, 0.0))
		self.assertEqual(bus.writes[-1], (GO, 0))

	def test_closing_puts_the_chip_in_standby_and_lets_the_bus_go(self):
		bus = FakeBus()
		opened(bus).close()
		self.assertEqual(bus.registers[MODE], STANDBY)
		self.assertTrue(bus.closed)

	def test_with_nothing_on_the_bus_it_says_what_to_check_and_leaves_the_bus_closed(self):
		bus = FakeBus(present=False)
		with self.assertRaises(PermanentError) as raised:
			opened(bus)
		self.assertEqual(str(raised.exception), "No haptic driver answers on the I²C bus (address 0x5A): check the Qw/ST cable and the module.")
		self.assertTrue(bus.closed)

	def test_another_chip_at_the_address_is_not_taken_for_one(self):
		bus = FakeBus(chip_id=1)
		with self.assertRaises(PermanentError) as raised:
			opened(bus)
		self.assertIn("not a DRV2605", str(raised.exception))
		self.assertTrue(bus.closed)

	def test_with_no_bus_it_says_to_turn_on_i2c(self):
		def no_bus(number: int) -> Any:
			raise FileNotFoundError(2, "No such file or directory: '/dev/i2c-1'")
		with self.assertRaises(PermanentError) as raised:
			HapticRenderer(no_bus)
		self.assertIn("turn on I²C", str(raised.exception))
		self.assertNotIn("/dev/i2c-1'", str(raised.exception))

	def test_without_the_device_libraries_it_says_what_to_do(self):
		import builtins
		real = builtins.__import__
		def no_smbus(name: str, *args: Any, **kwargs: Any) -> Any:
			if name == "smbus2":
				raise ImportError("No module named 'smbus2'")
			return real(name, *args, **kwargs)
		builtins.__import__ = no_smbus
		try:
			with self.assertRaises(PermanentError) as raised:
				haptic.load_bus()
		finally:
			builtins.__import__ = real
		self.assertIn("device libraries", str(raised.exception))

class TestUnplugged(unittest.TestCase):
	def test_a_module_unplugged_is_said_in_our_words_and_plugged_in_again_gets_its_settings_back(self):
		bus = FakeBus()
		renderer = opened(bus)
		bus.present = False
		with self.assertRaises(PermanentError) as raised:
			renderer.play("one", threading.Event(), 0.0)
		self.assertEqual(str(raised.exception), "The haptic driver stopped answering on the I²C bus (address 0x5A): check the Qw/ST cable and the module.")
		# plugged in again: the chip starts in standby with its own library, so the settings are written before the cue
		bus.present = True
		bus.registers[MODE] = STANDBY
		bus.writes.clear()
		self.assertFalse(renderer.play("one", threading.Event(), 0.0))
		self.assertEqual(bus.writes[0], (MODE, 0x00))
		self.assertIn((GO, 1), bus.writes)
		bus.writes.clear()
		renderer.play("one", threading.Event(), 0.0)
		self.assertNotIn((MODE, 0x00), bus.writes, "only once")

if __name__ == "__main__":
	unittest.main()
