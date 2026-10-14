import unittest

from scripts.fake_waveshare import MODES, mode_of

class TestFakeWaveshare(unittest.TestCase):
	"""The pretend Raspberry Pi of the `app-waveshare` service (the drivers' libraries are not installed where the tests run: only what does not need them is checked)."""
	def test_a_mode_is_one_of_the_known_ones_or_nothing(self):
		self.assertEqual([mode_of(m) for m in MODES], list(MODES))
		self.assertEqual([mode_of(None), mode_of(""), mode_of("fast")], [None, None, None])

if __name__ == "__main__":
	unittest.main()
