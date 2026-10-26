"""
From the composited frame to the inks of the panel (#684). The frame is drawn in drive colours (the exact RGB of each ink, `python/model/inks.py`): a page, an overlay and a line of text are
already on the panel's inks and must reach it as they are. Only a photograph needs to be turned into inks, by dithering, and that is done against what the inks *look like* on the panel.
"""
import numpy as np
from PIL import Image

from ..model.inks import ink_set_rgb
from ..utils.image_utils import to_rgb

def _palette(colors: list[tuple[int, int, int]]) -> list[int]:
	"""A palette of 256 entries: the colours, then copies of the first (PIL pads with black, which is the first ink of every set, but a padded entry must never be a colour of its own)."""
	flat = [channel for color in colors for channel in color]
	return flat + list(colors[0]) * (256 - len(colors))

def to_inks(img: Image.Image, ink_set: str) -> Image.Image:
	"""
	A `P` image whose palette starts with exactly the ink set's drive colours, in its order, and whose pixels are indexes into it. A pixel that already is a drive colour keeps its ink (no dithering,
	no error taken or given); every other pixel is Floyd-Steinberg dithered against the inks' appearance.
	"""
	drive = ink_set_rgb(ink_set, "drive")
	appearance = ink_set_rgb(ink_set, "appearance")
	rgb = to_rgb(img).convert("RGB")
	pixels = np.asarray(rgb)
	exact = np.zeros(pixels.shape[:2], dtype=bool)
	exact_index = np.zeros(pixels.shape[:2], dtype=np.uint8)
	# an exact pixel becomes the ink's appearance before the dither, so it sends no error to the photograph beside it
	prepared = pixels.copy()
	for index, color in enumerate(drive):
		match = np.all(pixels == color, axis=2)
		exact |= match
		exact_index[match] = index
		prepared[match] = appearance[index]
	if exact.all():
		indexes = exact_index
	else:
		palette = Image.new("P", (1, 1))
		palette.putpalette(_palette(appearance))
		dithered = np.asarray(Image.fromarray(prepared, "RGB").quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG))
		# only the inks' entries are colours; a padded entry is the first ink
		indexes = np.where(dithered < len(drive), dithered, 0).astype(np.uint8)
		indexes = np.where(exact, exact_index, indexes).astype(np.uint8)
	out = Image.fromarray(indexes, "P")
	out.putpalette(_palette(drive))
	return out

def to_appearance(inked: Image.Image, ink_set: str) -> Image.Image:
	"""A frame from `to_inks` as the panel shows it: RGB, each ink in its appearance colour (for a preview)."""
	shown = inked.copy()
	shown.putpalette(_palette(ink_set_rgb(ink_set, "appearance")))
	return shown.convert("RGB")

def ink_indexes(inked: Image.Image) -> np.ndarray:
	"""The ink index of every pixel of a frame from `to_inks`."""
	return np.asarray(inked)
