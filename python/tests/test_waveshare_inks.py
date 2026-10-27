"""
The colour Waveshare panels, through their own vendored drivers (#723): a frame made of a solid block of every ink of the panel's set reaches the driver's buffer as that ink, all of it.

The drivers are the real ones (`python/display/waveshare_epd/`); only `epdconfig`, which looks for a Raspberry Pi's GPIO when it is imported, is replaced. Each driver's `getbuffer` is given the
frame the display gives it (`to_inks`, then RGB), and the buffer is read back as the panel would read it: four bits (or two) a pixel, rows padded to a whole byte.
"""
import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from ..display.quantize import to_inks
from ..display.waveshare_display import WAVESHARE_INK_SETS, _FOUR_COLOR, _SEVEN_COLOR, split_for_bi_color
from ..model.inks import INK_SETS, ink_set_rgb

PACKAGE = "python.display.waveshare_epd"
# the number each driver gives each ink: the seven-colour panels' (black, white, green, blue, red, yellow, orange), the Spectra 6's (`epd7in3e`: no 4) and the four-colour panels' (black, white, yellow, red)
SEVEN = { "black": 0, "white": 1, "green": 2, "blue": 3, "red": 4, "yellow": 5, "orange": 6 }
SPECTRA = { "black": 0, "white": 1, "yellow": 2, "red": 3, "blue": 5, "green": 6 }
FOUR = { "black": 0, "white": 1, "yellow": 2, "red": 3 }
def driver(model: str):
	"""The vendored driver's `EPD`, with the Pi's GPIO library out of the way."""
	with patch.dict(sys.modules, { f"{PACKAGE}.epdconfig": MagicMock() }):
		sys.modules.pop(f"{PACKAGE}.{model}", None)
		return importlib.import_module(f"{PACKAGE}.{model}").EPD()

def frame(width: int, height: int, ink_set: str) -> Image.Image:
	"""A frame of one solid vertical block per ink of the set, on the inks as the display makes it, as RGB as the Waveshare display hands it over."""
	colors = ink_set_rgb(ink_set)
	picture = Image.new("RGB", (width, height))
	for i, color in enumerate(colors):
		picture.paste(color, (i * width // len(colors), 0, (i + 1) * width // len(colors), height))
	return to_inks(picture, ink_set).convert("RGB")

def decode(buf: list[int], width: int, height: int, bits: int) -> np.ndarray:
	"""The ink number of every pixel: `bits` bits a pixel, high bits first, each row padded to a whole byte."""
	data = np.array(buf, dtype=np.uint8)
	per_byte = 8 // bits
	row_bytes = -(-width // per_byte)
	shifts = np.arange(8 - bits, -1, -bits, dtype=np.uint8)
	pixels = (data[:, None] >> shifts) & ((1 << bits) - 1)
	return pixels.reshape(height, row_bytes * per_byte)[:, :width]

def shares(model: str, numbers: dict[str, int], bits: int) -> dict[str, float]:
	epd = driver(model)
	ink_set = WAVESHARE_INK_SETS[model]
	names = INK_SETS[ink_set]
	pixels = decode(epd.getbuffer(frame(epd.width, epd.height, ink_set)), epd.width, epd.height, bits)
	found = {}
	for i, name in enumerate(names):
		block = pixels[:, i * epd.width // len(names):(i + 1) * epd.width // len(names)]
		found[name] = float((block == numbers[name]).mean())
	return found

class TestColorDrivers(unittest.TestCase):
	def check(self, model: str, numbers: dict[str, int], bits: int) -> None:
		found = shares(model, numbers, bits)
		for name, share in found.items():
			with self.subTest(model=model, ink=name):
				self.assertEqual(share, 1.0)

	def test_the_seven_color_panels_get_every_ink_whole(self):
		for model in _SEVEN_COLOR:
			self.check(model, SEVEN, 4)

	def test_the_spectra_6_panel_gets_every_ink_whole(self):
		self.check("epd7in3e", SPECTRA, 4)

	def test_the_four_color_panels_get_every_ink_whole(self):
		for model in _FOUR_COLOR:
			self.check(model, FOUR, 2)

class TestThreeColorPanels(unittest.TestCase):
	def test_each_ink_goes_to_its_layer_and_white_to_neither(self):
		"""A three-colour panel takes a black layer and a second ink's layer, 0 where the ink goes (`split_for_bi_color`, ours: no driver quantizes for it)."""
		for ink_set in ("bwr", "bwy"):
			names = INK_SETS[ink_set]
			black, second = (np.asarray(layer) for layer in split_for_bi_color(frame(30 * len(names), 4, ink_set), ink_set))
			for i, name in enumerate(names):
				block = slice(i * 30, (i + 1) * 30)
				with self.subTest(ink_set=ink_set, ink=name):
					self.assertEqual((black[:, block] == 0).mean(), 1.0 if name == "black" else 0.0)
					self.assertEqual((second[:, block] == 0).mean(), 1.0 if name in ("red", "yellow") else 0.0)
