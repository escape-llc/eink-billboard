"""
The colour Inky boards, as the driver draws them (#723): a frame made of a solid block of every ink of the board's set reaches the board's buffer as that ink, all of it.

The boards here are fakes that run the driver's own `set_image` and palettes: copied from `inky` 2.6.0 (`inky_uc8159`, `inky_ac073tc1a`, `inky_e673`, `inky_e640`, `inky_el133uf1`),
the version `pyproject.toml` pins (the real package needs a Pi's GPIO and is not installed where the tests run). A new driver version needs the copies read again.
"""
import unittest

import numpy as np
from PIL import Image

from ..display.inky_display import InkyDisplay
from ..display.quantize import to_inks
from ..model.inks import INK_SETS, ink_set_rgb
from .test_inky_display import settings_of

BLOCK = 40

# the 7-colour boards' palettes (`inky_uc8159`, `inky_ac073tc1a`): their own order, and their own orange
SEVEN_NAMES = ("black", "white", "green", "blue", "red", "yellow", "orange")
SEVEN_DESATURATED = [[0, 0, 0], [255, 255, 255], [0, 255, 0], [0, 0, 255], [255, 0, 0], [255, 255, 0], [255, 140, 0], [255, 255, 255]]
SEVEN_SATURATED = [[57, 48, 57], [255, 255, 255], [58, 91, 70], [61, 59, 94], [156, 72, 75], [208, 190, 71], [177, 106, 73], [255, 255, 255]]
# the Spectra boards' (`inky_e673`, `inky_e640`, `inky_el133uf1`): their numbers are the buffer's, with no 4
SPECTRA_NAMES = { "black": 0, "white": 1, "yellow": 2, "red": 3, "blue": 5, "green": 6 }
SPECTRA_DESATURATED = [[0, 0, 0], [255, 255, 255], [255, 255, 0], [255, 0, 0], [0, 0, 255], [0, 255, 0], [255, 255, 255]]
SPECTRA_SATURATED = [[0, 0, 0], [161, 164, 165], [208, 190, 71], [156, 72, 75], [61, 59, 94], [58, 91, 70], [255, 255, 255]]

def blend(desaturated: list, saturated: list, colors: int, saturation: float) -> list[int]:
	"""The driver's `_palette_blend`."""
	palette: list[int] = []
	for i in range(colors):
		rs, gs, bs = [c * saturation for c in saturated[i]]
		rd, gd, bd = [c * (1.0 - saturation) for c in desaturated[i]]
		palette += [int(rs + rd), int(gs + gd), int(bs + bd)]
	return palette

class SevenColourBoard:
	"""`inky_uc8159` and `inky_ac073tc1a`: a `P` image is the buffer as it is; anything else is quantized (and dithered) to the board's own palette."""
	def __init__(self, width: int, height: int):
		self.width, self.height = width, height
		self.buf = np.zeros((height, width), dtype=np.uint8)
		self.shown = 0
	def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:
		if not image.size == (self.width, self.height):
			raise ValueError(f"Image must be ({self.width}x{self.height}) pixels!")
		if image.mode != "P":
			palette = blend(SEVEN_DESATURATED, SEVEN_SATURATED, 7, saturation) + [255, 255, 255]
			palette_image = Image.new("P", (1, 1))
			palette_image.putpalette(palette + [0, 0, 0] * 248)
			image = image.convert("RGB").quantize(palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)
		self.buf = np.array(image, dtype=np.uint8).reshape((self.height, self.width))
	def show(self) -> None:
		self.shown += 1

class Uc8159(SevenColourBoard):
	__module__ = "inky.inky_uc8159"

class Ac073tc1a(SevenColourBoard):
	__module__ = "inky.inky_ac073tc1a"

class SpectraBoard:
	"""`inky_e673`, `inky_e640` and `inky_el133uf1`: quantized to six colours against the board's palette, then numbered as the buffer is (colour 4 is missing)."""
	def __init__(self, width: int, height: int):
		self.width, self.height = width, height
		self.buf = np.zeros((height, width), dtype=np.uint8)
	def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:
		if not image.size == (self.width, self.height):
			raise ValueError(f"Image must be ({self.width}x{self.height}) pixels!")
		palette_image = Image.new("P", (1, 1))
		palette_image.putpalette(blend(SPECTRA_DESATURATED, SPECTRA_SATURATED, 6, saturation))
		image = image.convert("RGB").quantize(6, palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)
		remap = np.array([0, 1, 2, 3, 5, 6])
		self.buf = remap[np.array(image, dtype=np.uint8).reshape((self.height, self.width))]
	def show(self) -> None:
		pass

class E673(SpectraBoard):
	__module__ = "inky.inky_e673"

class E640(SpectraBoard):
	__module__ = "inky.inky_e640"

class El133uf1(SpectraBoard):
	__module__ = "inky.inky_el133uf1"

def blocks(ink_set: str) -> Image.Image:
	"""A frame of one solid block per ink of the set, in drive colours, through `to_inks` as the display task makes it."""
	drive = ink_set_rgb(ink_set)
	frame = Image.new("RGB", (BLOCK * len(drive), BLOCK))
	for i, color in enumerate(drive):
		frame.paste(color, (i * BLOCK, 0, (i + 1) * BLOCK, BLOCK))
	return to_inks(frame, ink_set)

def share_of(buf: np.ndarray, index: int, which: int, count: int) -> float:
	"""The share of block `which` (of `count`) of a frame that is `index`."""
	block = buf[:, which * BLOCK:(which + 1) * BLOCK]
	return float((block == index).mean())

def shown_on(board, ink_set: str) -> np.ndarray:
	display = InkyDisplay("inky", loader=lambda: board)
	display.initialize(settings_of({}))
	display.render(blocks(ink_set), 1)
	return board.buf

class TestSevenColourBoards(unittest.TestCase):
	def test_every_ink_reaches_the_board_whole(self):
		for cls in (Uc8159, Ac073tc1a):
			board = cls(BLOCK * 7, BLOCK)
			buf = shown_on(board, "acep7")
			for i, name in enumerate(INK_SETS["acep7"]):
				with self.subTest(board=cls.__name__, ink=name):
					self.assertEqual(share_of(buf, SEVEN_NAMES.index(name), i, 7), 1.0)
			self.assertEqual(board.shown, 1)

	def test_the_fake_board_shows_the_trouble_it_is_there_for(self):
		"""What the board did with an RGB frame: its own orange is not ours, so drive orange was dithered (8% of it red)."""
		board = Uc8159(BLOCK * 7, BLOCK)
		board.set_image(blocks("acep7").convert("RGB"), saturation=0.0)
		orange = INK_SETS["acep7"].index("orange")
		self.assertLess(share_of(board.buf, SEVEN_NAMES.index("orange"), orange, 7), 1.0)
		self.assertGreater(share_of(board.buf, SEVEN_NAMES.index("red"), orange, 7), 0.0)

class TestSpectraBoards(unittest.TestCase):
	def test_every_ink_reaches_the_board_whole(self):
		for cls in (E673, E640, El133uf1):
			board = cls(BLOCK * 6, BLOCK)
			buf = shown_on(board, "spectra6")
			for i, name in enumerate(INK_SETS["spectra6"]):
				with self.subTest(board=cls.__name__, ink=name):
					self.assertEqual(share_of(buf, SPECTRA_NAMES[name], i, 6), 1.0)
