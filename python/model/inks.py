"""
The ink vocabulary (#684): which inks a panel has and what each looks like. It knows nothing about drivers; a display says which ink set it has (`DisplayBase.ink_set`), everything that
draws or quantizes asks here what the inks are.

Each ink has two colours. The **drive** colour is the exact RGB the app draws with and hands to a driver (every driver's palette in the repo uses these, so a frame made only of drive
colours passes through any driver's quantizer with no error). The **appearance** is roughly what the panel shows, for dithering a photograph and for a preview.
"""
from typing import Literal

INKS = ("black", "white", "red", "yellow", "blue", "green", "orange")

DRIVE: dict[str, tuple[int, int, int]] = {
	"black": (0, 0, 0),
	"white": (255, 255, 255),
	"red": (255, 0, 0),
	"yellow": (255, 255, 0),
	"blue": (0, 0, 255),
	"green": (0, 255, 0),
	"orange": (255, 128, 0),
}

# what the pigments look like, measured by Pimoroni (`SATURATED_PALETTE` of the `inky` driver, the Spectra 6 E673 panel; orange from the 7-colour Impression's, which has it), against that
# panel's own white (161, 164, 165). Each colour is divided by that white channel by channel, so the white is #ffffff and the others keep their distance from it. It is an approximation: other
# panels of the family differ a little, and a photograph in a preview only needs to be near.
_PANEL_WHITE = (161, 164, 165)
_MEASURED: dict[str, tuple[int, int, int]] = {
	"black": (0, 0, 0),
	"white": _PANEL_WHITE,
	"red": (156, 72, 75),
	"yellow": (208, 190, 71),
	"blue": (61, 59, 94),
	"green": (58, 91, 70),
	"orange": (177, 106, 73),
}
APPEARANCE: dict[str, tuple[int, int, int]] = {
	name: (min(255, round(r * 255 / _PANEL_WHITE[0])), min(255, round(g * 255 / _PANEL_WHITE[1])), min(255, round(b * 255 / _PANEL_WHITE[2])))
	for name, (r, g, b) in _MEASURED.items()
}

# the inks of each set, in the order of the palette index of a quantized picture
INK_SETS: dict[str, tuple[str, ...]] = {
	"bw": ("black", "white"),
	"bwr": ("black", "white", "red"),
	"bwy": ("black", "white", "yellow"),
	"bwry": ("black", "white", "red", "yellow"),
	"spectra6": ("black", "white", "red", "yellow", "blue", "green"),
	"acep7": ("black", "white", "red", "yellow", "blue", "green", "orange"),
}
DEFAULT_INK_SET = "spectra6"

def nearest_ink(rgb: tuple[int, int, int], ink_set: str) -> str:
	"""The ink of `ink_set` that a colour someone else chose (a bus route's) is drawn in, by what the inks look like (`APPEARANCE`), so a page stays inks only (#429)."""
	return min(INK_SETS.get(ink_set, INK_SETS[DEFAULT_INK_SET]), key=lambda ink: sum((a - b) ** 2 for a, b in zip(APPEARANCE[ink], rgb, strict=True)))

def ink_for(color: str|None, ink_set: str, page_ink: str) -> str|None:
	"""
	A colour someone else chose (a calendar's, an event's: `#rgb` or `#rrggbb`) as the `#rrggbb` of its nearest ink, so a page that draws it stays inks only (#801).
	None, for the page's own text colour, when there is no colour or its nearest ink is the page's own: drawn in it, it would not show.
	"""
	if not isinstance(color, str) or len(color) not in (4, 7) or not color.startswith("#"):
		return None
	digits = color[1:] if len(color) == 7 else "".join(c * 2 for c in color[1:])
	try:
		rgb = (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
	except ValueError:
		return None
	ink = nearest_ink(rgb, ink_set)
	return None if ink == page_ink else "#%02x%02x%02x" % DRIVE[ink]

def ink_set_rgb(name: str, which: Literal["drive", "appearance"] = "drive") -> list[tuple[int, int, int]]:
	"""The colours of an ink set's inks, in palette order (`drive`: what is drawn and handed to the driver; `appearance`: what the panel shows)."""
	table = DRIVE if which == "drive" else APPEARANCE
	return [table[ink] for ink in INK_SETS[name]]

# the ink set of the panel that is attached, published by the Display task once the display has started and cleared when it quits: a page asks for it when it is rendered (`panel_ink_set`)
# so that the theme resolves to inks the panel has. One device has one display, so this is one value, not a service; before a display has started it is the default.
_panel: str|None = None

def publish_panel_ink_set(name: str|None) -> None:
	global _panel
	_panel = name if name in INK_SETS else None

def panel_ink_set() -> str:
	"""The ink set of the attached panel, or the default (six colors) while no display has started."""
	return _panel or DEFAULT_INK_SET
