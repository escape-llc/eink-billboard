import unittest

import numpy as np
from PIL import Image

from ..display.quantize import ink_indexes, to_appearance, to_inks
from ..display.waveshare_display import split_for_bi_color
from ..model.inks import DRIVE, INK_SETS, ink_set_rgb

def photo(width=120, height=80) -> Image.Image:
	"""A smooth gradient with noise: no pixel of it is a drive colour (but for chance, which the test avoids by an offset)."""
	rng = np.random.default_rng(1)
	x = np.linspace(20, 235, width)[None, :, None]
	y = np.linspace(30, 220, height)[:, None, None]
	pixels = np.concatenate([np.broadcast_to(x, (height, width, 1)), np.broadcast_to(y, (height, width, 1)), np.broadcast_to((x + y) / 2, (height, width, 1))], axis=2)
	return Image.fromarray(np.clip(pixels + rng.integers(-8, 9, pixels.shape), 3, 252).astype(np.uint8), "RGB")

class TestToInks(unittest.TestCase):
	def test_the_palette_is_the_ink_sets_drive_colors_in_order(self):
		for name in INK_SETS:
			out = to_inks(Image.new("RGB", (4, 4), "white"), name)
			self.assertEqual(out.mode, "P")
			self.assertEqual(list(out.getpalette() or [])[:3 * len(INK_SETS[name])], [c for rgb in ink_set_rgb(name) for c in rgb], name)

	def test_a_drive_colored_pixel_is_kept_and_only_the_sets_indexes_appear(self):
		for name, inks in INK_SETS.items():
			img = photo()
			for i, ink in enumerate(inks):
				img.putpixel((i, 0), DRIVE[ink])
			indexes = ink_indexes(to_inks(img, name))
			self.assertLess(int(indexes.max()), len(inks), name)
			self.assertEqual([int(indexes[0, i]) for i in range(len(inks))], list(range(len(inks))), name)

	def test_a_gradient_is_dithered(self):
		self.assertGreater(len(set(ink_indexes(to_inks(photo(), "spectra6")).flatten().tolist())), 2)

	def test_a_line_through_a_photo_survives_whole(self):
		img = photo()
		for x in range(img.width):
			img.putpixel((x, 40), DRIVE["red"])
		for y in range(img.height):
			img.putpixel((60, y), DRIVE["black"])
		indexes = ink_indexes(to_inks(img, "spectra6"))
		self.assertTrue(all(indexes[40, x] == 2 for x in range(img.width) if x != 60))
		self.assertTrue(all(indexes[y, 60] == 0 for y in range(img.height)))

	def test_a_frame_of_drive_colors_is_not_changed_at_all(self):
		img = Image.new("RGB", (30, 30), "white")
		img.paste(DRIVE["yellow"], (0, 0, 10, 30))
		img.paste(DRIVE["blue"], (20, 0, 30, 10))
		self.assertEqual(to_inks(img, "spectra6").convert("RGB").tobytes(), img.tobytes())

	def test_the_appearance_has_the_inks_own_colors(self):
		shown = to_appearance(to_inks(Image.new("RGB", (2, 2), DRIVE["white"]), "bw"), "bw")
		self.assertEqual(shown.getpixel((0, 0)), (255, 255, 255))

class TestOverlayOverAPhoto(unittest.TestCase):
	def test_every_opaque_overlay_pixel_keeps_its_ink(self):
		base = photo(200, 120).convert("RGBA")
		overlay = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
		rng = np.random.default_rng(2)
		inks = ("black", "white", "red", "yellow")
		for _ in range(600):
			overlay.putpixel((int(rng.integers(0, 200)), int(rng.integers(0, 120))), (*DRIVE[inks[int(rng.integers(0, 4))]], 255))
		base.alpha_composite(overlay)
		indexes = ink_indexes(to_inks(base.convert("RGB"), "spectra6"))
		wanted = np.asarray(overlay)
		opaque = wanted[:, :, 3] == 255
		names = [ink for ink in INK_SETS["spectra6"]]
		expected = np.zeros(opaque.shape, dtype=int)
		for i, ink in enumerate(names):
			expected[np.all(wanted[:, :, :3] == DRIVE[ink], axis=2)] = i
		self.assertEqual(int((indexes[opaque] != expected[opaque]).sum()), 0)

class TestSplitForThreeColors(unittest.TestCase):
	def test_the_second_ink_is_red_or_yellow(self):
		img = Image.new("RGB", (4, 1), "white")
		img.putpixel((1, 0), DRIVE["black"])
		img.putpixel((2, 0), DRIVE["red"])
		img.putpixel((3, 0), DRIVE["yellow"])
		for name, second in (("bwr", 2), ("bwy", 3)):
			black, colour = split_for_bi_color(img, name)
			self.assertEqual([black.getpixel((x, 0)) for x in range(4)][:2], [1, 0])
			self.assertEqual(colour.getpixel((second, 0)), 0, name)
