"""
The word clock: the time spelled in five-minute steps ("IT IS TWENTY FIVE PAST SEVEN") by lighting words on a grid of letters.

The grid is our own: every phrase reads left to right and top to bottom, so the minutes' FIVE and TEN come before PAST and TO and the hours' after.
The time is rounded down, so the clock never says a time that has not come yet.
"""
from datetime import datetime

from PIL import Image, ImageDraw

from ...model.configuration_manager import StaticConfigurationManager
from ...model.theme import Palette

GRID = (
	"ITKISYHALFTEN",
	"QUARTERTWENTY",
	"FIVEXPASTYTOE",
	"ONETWOTHREEKL",
	"FOURFIVESIXSD",
	"SEVENEIGHTXZQ",
	"NINETENELEVEN",
	"TWELVEOCLOCKS",
)
COLUMNS = len(GRID[0])

# each word as (row, first column, length); a word that is both a minute and an hour is two words, `m-` and `h-`
WORDS: dict[str, tuple[int, int, int]] = {
	"IT": (0, 0, 2), "IS": (0, 3, 2), "HALF": (0, 6, 4), "m-TEN": (0, 10, 3),
	"QUARTER": (1, 0, 7), "TWENTY": (1, 7, 6),
	"m-FIVE": (2, 0, 4), "PAST": (2, 5, 4), "TO": (2, 10, 2),
	"h-ONE": (3, 0, 3), "h-TWO": (3, 3, 3), "h-THREE": (3, 6, 5),
	"h-FOUR": (4, 0, 4), "h-FIVE": (4, 4, 4), "h-SIX": (4, 8, 3),
	"h-SEVEN": (5, 0, 5), "h-EIGHT": (5, 5, 5),
	"h-NINE": (6, 0, 4), "h-TEN": (6, 4, 3), "h-ELEVEN": (6, 7, 6),
	"h-TWELVE": (7, 0, 6), "OCLOCK": (7, 6, 6),
}
HOURS = ("TWELVE", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN")
# the words for the minutes past (5 to 30) or to (25 to 5) the hour
MINUTES = { 5: ["m-FIVE"], 10: ["m-TEN"], 15: ["QUARTER"], 20: ["TWENTY"], 25: ["TWENTY", "m-FIVE"], 30: ["HALF"] }
UNLIT = ("secondary", "none")
GRID_FILL = 0.92  # the share of the page the grid may span
MIN_LETTER_PX = 15  # the least a letter is drawn at (plugin.css: --min-text)


def phrase_words(t: datetime) -> list[str]:
	"""The words lit at `t`, in reading order, as keys of WORDS."""
	step = t.minute - t.minute % 5
	hour = t.hour if step <= 30 else t.hour + 1
	hour_word = f"h-{HOURS[hour % 12]}"
	if step == 0:
		return ["IT", "IS", hour_word, "OCLOCK"]
	if step <= 30:
		return ["IT", "IS", *MINUTES[step], "PAST", hour_word]
	return ["IT", "IS", *MINUTES[60 - step], "TO", hour_word]


def phrase(t: datetime) -> str:
	"""What the clock says at `t`: "IT IS QUARTER TO NINE"."""
	return " ".join(w.split("-")[-1] for w in phrase_words(t))


def lit_cells(t: datetime) -> set[tuple[int, int]]:
	"""The (row, column) of every letter lit at `t`."""
	cells: set[tuple[int, int]] = set()
	for word in phrase_words(t):
		row, start, length = WORDS[word]
		cells.update((row, c) for c in range(start, start + length))
	return cells


def draw_words(t: datetime, unlit: str, dimensions: tuple[int, int], palette: Palette, stm: StaticConfigurationManager, family: str) -> Image.Image:
	"""The page: the grid centred, lit letters bold in the main text ink, the others in the lighter ink (`secondary`) or not drawn (`none`)."""
	width, height = dimensions
	cell = min(width * GRID_FILL / COLUMNS, height * GRID_FILL / len(GRID))
	size = max(MIN_LETTER_PX, round(cell * 0.62))
	lit_font = stm.get_font(family, size, "bold")
	unlit_font = stm.get_font(family, size, "normal")
	left = (width - cell * COLUMNS) / 2
	top = (height - cell * len(GRID)) / 2
	image = Image.new("RGB", dimensions, palette.rgb("bg_page"))
	draw = ImageDraw.Draw(image)
	# no antialiasing: a grey edge on a letter is dithered on the panel
	draw.fontmode = "1"
	lit = lit_cells(t)
	for r, row in enumerate(GRID):
		for c, letter in enumerate(row):
			centre = (left + (c + 0.5) * cell, top + (r + 0.5) * cell)
			if (r, c) in lit:
				draw.text(centre, letter, font=lit_font, fill=palette.rgb("text_primary"), anchor="mm")
			elif unlit == "secondary":
				draw.text(centre, letter, font=unlit_font, fill=palette.rgb("text_secondary_2"), anchor="mm")
	return image
