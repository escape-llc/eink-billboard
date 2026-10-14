import struct
import unittest

from scripts.fake_inky import MODES, UNKNOWN_VARIANT, VARIANT_7_COLOUR, eeprom_bytes, mode_of

class TestFakeInky(unittest.TestCase):
	"""The pretend board of the `app-inky` container (the driver itself is not installed where the tests run: only what does not need it is checked)."""
	def test_the_eeprom_is_what_the_driver_reads(self):
		data = eeprom_bytes(VARIANT_7_COLOUR, 600, 448)
		self.assertEqual(len(data), 29)
		width, height, colour, pcb, variant, written = struct.unpack("<HHBBB22p", bytes(data))
		self.assertEqual((width, height, colour, variant), (600, 448, 5, VARIANT_7_COLOUR))
		self.assertTrue(written.startswith(b"2026"))
		self.assertNotEqual(UNKNOWN_VARIANT, VARIANT_7_COLOUR)

	def test_a_mode_is_one_of_the_known_ones_or_nothing(self):
		self.assertEqual([mode_of(m) for m in MODES], list(MODES))
		self.assertEqual([mode_of(None), mode_of(""), mode_of("fast")], [None, None, None])

if __name__ == "__main__":
	unittest.main()
