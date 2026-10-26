import unittest

from ..display.inky_display import ink_set_of as inky_ink_set
from ..display.waveshare_display import MODELS, WAVESHARE_INK_SETS, ink_set_of
from ..model.inks import APPEARANCE, DRIVE, INK_SETS, INKS, ink_set_rgb

class TestInks(unittest.TestCase):
	def test_tables(self):
		self.assertEqual(set(DRIVE), set(INKS))
		self.assertEqual(set(APPEARANCE), set(INKS))
		self.assertEqual(APPEARANCE["white"], (255, 255, 255))
		for name, inks in INK_SETS.items():
			self.assertEqual(inks[:2], ("black", "white"), name)
			self.assertEqual(ink_set_rgb(name)[0], (0, 0, 0))
		self.assertEqual(ink_set_rgb("bwr"), [(0, 0, 0), (255, 255, 255), (255, 0, 0)])

class TestWaveshareInkSets(unittest.TestCase):
	def test_every_model_has_one(self):
		self.assertEqual(set(WAVESHARE_INK_SETS), set(MODELS))
		self.assertTrue(set(WAVESHARE_INK_SETS.values()) <= set(INK_SETS))

	def test_known_models(self):
		self.assertEqual(ink_set_of("epd7in3e"), "spectra6")
		self.assertEqual(ink_set_of("epd5in65f"), "acep7")
		self.assertEqual(ink_set_of("epd2in13g"), "bwry")
		self.assertEqual(ink_set_of("epd7in5_V2"), "bw")
		self.assertEqual(ink_set_of("epd7in5b_V2"), "bwr")
		self.assertIsNone(ink_set_of("nope"))

	def test_second_ink(self):
		self.assertEqual(ink_set_of("epd1in54c"), "bwy")
		self.assertEqual(ink_set_of("epd1in54c", "red"), "bwr")
		self.assertEqual(ink_set_of("epd2in13bc"), "bwr")
		self.assertEqual(ink_set_of("epd2in13bc", "yellow"), "bwy")

class TestInkyInkSets(unittest.TestCase):
	def board(self, module: str, colour=None):
		return type("Inky", (), { "__module__": f"inky.{module}", "colour": colour })()

	def test_by_chip(self):
		for module, expected in (("inky_e673", "spectra6"), ("inky_e640", "spectra6"), ("inky_el133uf1", "spectra6"), ("inky_uc8159", "acep7"),
				("inky_ac073tc1a", "acep7"), ("inky_jd79661", "bwry"), ("inky_jd79668", "bwry"), ("inky_ssd2683", "bwry")):
			self.assertEqual(inky_ink_set(self.board(module, "multi")), expected, module)

	def test_by_colour(self):
		for colour, expected in (("black", "bw"), ("red", "bwr"), ("yellow", "bwy")):
			self.assertEqual(inky_ink_set(self.board("phat", colour)), expected)
		self.assertIsNone(inky_ink_set(self.board("phat", "purple")))
