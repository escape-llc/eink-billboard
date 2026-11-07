"""
Which lines of the 40-pin header are whose. The panel's belong to the display's driver stage; every other line belongs to the `DeviceIO` task (python/task/device_io.py), and a device
connected to it must not be given one that the panel uses. The panel's lines are fixed by its driver (Waveshare: `waveshare_epd/epdconfig.py`; Inky: the `inky` package), so they are
a table here, by display type; a device's pins are checked against it before anything is opened.

Pins are Broadcom (BCM) numbers, the GPIO numbers of the header (2 to 27), as gpiozero takes them.
"""
from dataclasses import dataclass
from typing import Mapping

from .cues import FEEDBACK, KIND_TITLES

# the GPIO numbers of the 40-pin header
FIRST_PIN, LAST_PIN = 2, 27

@dataclass(frozen=True)
class Panel:
	"""What the Display task made of the panel, given to the other tasks as a service: which kind it is and how big (the 13.3 inch Inky drives two chips and so uses more lines)."""
	display_type: str
	width: int
	height: int

# Waveshare: every driver uses epdconfig's lines
WAVESHARE_LINES: Mapping[int, str] = { 17: "reset", 25: "data/command", 8: "chip select", 24: "busy", 18: "power", 10: "SPI data", 11: "SPI clock" }
# Inky: the lines of the `inky` package's boards (reset 27, busy 17, data/command 22, chip select 8)
INKY_LINES: Mapping[int, str] = { 27: "reset", 17: "busy", 22: "data/command", 8: "chip select", 10: "SPI data", 11: "SPI clock" }
# the 13.3 inch Inky (1600x1200) has two chip selects of its own
INKY_13_LINES: Mapping[int, str] = { 26: "first chip select", 16: "second chip select" }
INKY_13_SIZES = ((1600, 1200), (1200, 1600))

def panel_lines(panel: Panel|None) -> Mapping[int, str]:
	"""The lines the panel uses, by pin number, with what each is for; none for a display that is not a panel (mock, tk) or when it is not known."""
	if panel is None:
		return {}
	if panel.display_type == "waveshare":
		return WAVESHARE_LINES
	if panel.display_type == "inky":
		return { **INKY_LINES, **(INKY_13_LINES if (panel.width, panel.height) in INKY_13_SIZES else {}) }
	return {}

# the I²C bus's lines (a haptic output's driver chip is on it)
I2C_LINES: Mapping[int, str] = { 2: "I²C data", 3: "I²C clock" }
# lines of the buses the install turns on for the panel: a button may use one when that bus is off, so they are said, not refused
BUS_LINES: Mapping[int, str] = { 2: "I²C data", 3: "I²C clock", 7: "SPI chip select 1", 9: "SPI data in" }

# what the panel's board wires to a free line (the Inky Impression's LED, #887, and its four buttons, #866, from Pimoroni's examples/spectra6): said in the list of pins, so the
# person sees which one to choose
INKY_PARTS: Mapping[int, str] = { 5: "Button A", 6: "Button B", 13: "LED", 16: "Button C", 24: "Button D" }
# the 13.3 inch board's button C is on 25 (16 is its second chip select)
INKY_13_PARTS: Mapping[int, str] = { 5: "Button A", 6: "Button B", 13: "LED", 24: "Button D", 25: "Button C" }

def board_parts(panel: Panel|None) -> Mapping[int, str]:
	"""The parts on the panel's board that use a line the panel leaves free, by pin number; none when the board has none or is not known."""
	if panel is None or panel.display_type != "inky":
		return {}
	return INKY_13_PARTS if (panel.width, panel.height) in INKY_13_SIZES else INKY_PARTS

@dataclass(frozen=True)
class PinChoice:
	"""One pin of the header as the GPIO settings offer it: its name (what it is, and why it cannot be used when it cannot) and whether it can be chosen."""
	pin: int
	name: str
	available: bool

def panel_for(display_type: str|None, running: Panel|None) -> Panel|None:
	"""
	The panel the display settings choose (`display_type`), which is not always the one that is running: a change of display takes effect at the next start, and the choice of pins follows the
	selection at once. The running panel's size is used only when it is the same kind (the big Inky is told by its size, which only a started display knows); none chosen: none.
	"""
	if not display_type:
		return None
	return running if running is not None and running.display_type == display_type else Panel(display_type, 0, 0)

def pin_choices(panel: Panel|None) -> list[PinChoice]:
	"""Every pin the header offers (`FIRST_PIN` to `LAST_PIN`), the panel's lines marked as not available, the board's parts and the buses' lines said, in the order of the header's numbers."""
	taken, parts = panel_lines(panel), board_parts(panel)
	choices: list[PinChoice] = []
	for pin in range(FIRST_PIN, LAST_PIN + 1):
		if pin in taken:
			choices.append(PinChoice(pin, f"GPIO {pin} · not available: the panel's {taken[pin]}", False))
		elif pin in parts:
			choices.append(PinChoice(pin, f"GPIO {pin} · {parts[pin]}", True))
		elif pin in BUS_LINES:
			choices.append(PinChoice(pin, f"GPIO {pin} · {BUS_LINES[pin]}: in use while that bus is on", True))
		else:
			choices.append(PinChoice(pin, f"GPIO {pin}", True))
	return choices

def panel_pin_errors(rows: object, panel: Panel|None, list_name: str = "triggers") -> list[dict]:
	"""
	What is wrong with the pins of a list's rows (`{ pin, ... }`) at a save, as the form shows it: a pin the panel uses is an error on that row's `pin` (`[list, "<row>", "pin"]`), in our words.
	The same rule `check_pins` applies when the devices are opened; here it is said where the person is choosing.
	"""
	taken = panel_lines(panel)
	errors: list[dict] = []
	for index, row in enumerate(rows if isinstance(rows, list) else []):
		pin = row.get("pin") if isinstance(row, dict) else None
		if isinstance(pin, int) and not isinstance(pin, bool) and pin in taken:
			errors.append({ "path": [list_name, str(index), "pin"], "message": f"The panel uses this pin ({taken[pin]}): choose another." })
	return errors

def output_pin_errors(document: Mapping[str, object], panel: Panel|None) -> list[dict]:
	"""
	The outputs' pins at a save (#891), each at its row's `pin` (`["outputs", "<row>", "pin"]`): a GPIO output not on a pin the panel, a button or another output uses; with a haptic output
	(on the I²C bus), no button or GPIO output on the bus's pins. The same rules `check_pins` applies when the devices are opened.
	"""
	taken = panel_lines(panel)
	outputs = document.get("outputs")
	rows = [row for row in outputs if isinstance(row, dict)] if isinstance(outputs, list) else []
	triggers = document.get("triggers")
	buttons = { row.get("pin") for row in triggers if isinstance(row, dict) } if isinstance(triggers, list) else set()
	errors: list[dict] = []
	seen: set[int] = set()
	for index, row in enumerate(rows):
		pin = row.get("pin")
		if row.get("kind") != "gpio" or not isinstance(pin, int) or isinstance(pin, bool):
			continue
		path = ["outputs", str(index), "pin"]
		if pin in taken:
			errors.append({ "path": path, "message": f"The panel uses this pin ({taken[pin]}): choose another." })
		elif pin in buttons:
			errors.append({ "path": path, "message": "A button uses this pin: each needs its own." })
		elif pin in seen:
			errors.append({ "path": path, "message": "Another output uses this pin: each needs its own." })
		seen.add(pin)
	if any(row.get("kind") == "haptic" for row in rows):
		bus = set(I2C_LINES)
		for index, row in enumerate(rows):
			if row.get("kind") == "gpio" and row.get("pin") in bus:
				errors.append({ "path": ["outputs", str(index), "pin"], "message": "The haptic output uses this pin (the I²C bus): choose another." })
		for index, row in enumerate(triggers if isinstance(triggers, list) else []):
			if isinstance(row, dict) and row.get("pin") in bus:
				errors.append({ "path": ["triggers", str(index), "pin"], "message": "The haptic output uses this pin (the I²C bus): choose another." })
	return errors

def feedback_row_errors(document: Mapping[str, object]) -> list[dict]:
	"""
	A feedback row names an output of its section's kind in the document being saved, at `["<section>", "<row>", "output"]`; the choice is a lookup of the
	saved outputs, which the form cannot check.
	"""
	outputs = document.get("outputs")
	rows_of = [row for row in outputs if isinstance(row, dict)] if isinstance(outputs, list) else []
	errors: list[dict] = []
	for kind, section in FEEDBACK.items():
		names = { row.get("name") for row in rows_of if row.get("kind") == kind }
		rows = document.get(section)
		errors += [{ "path": [section, str(index), "output"], "message": f"No {KIND_TITLES[kind]} output has this name: add it under Outputs." }
			for index, row in enumerate(rows if isinstance(rows, list) else []) if isinstance(row, dict) and row.get("output") not in names]
	return errors

def playlist_row_errors(rows: object, playlists: Mapping[str, str], list_name: str = "triggers") -> list[dict]:
	"""
	A row that plays a playlist names one that exists (`playlists`: each id with its name), at `[list, "<row>", "playlist"]`, and so does its long press (`longAction`,
	`longPlaylist`); the choice is a lookup the form cannot check.
	"""
	errors: list[dict] = []
	for index, row in enumerate(rows if isinstance(rows, list) else []):
		if not isinstance(row, dict):
			continue
		for action, playlist in (("action", "playlist"), ("longAction", "longPlaylist")):
			if row.get(action) == "playlist" and row.get(playlist) not in playlists:
				errors.append({ "path": [list_name, str(index), playlist], "message": "Not one of the allowed values" })
	return errors

def check_pins(pins: Mapping[str, int], panel: Panel|None, labels: Mapping[str, str]|None = None) -> list[str]:
	"""
	What is wrong with the pins a device was given (`pins`: the name of each input to its pin), in our words: a pin that is not on the header, one the panel uses, one used twice.
	`labels` says what each input is called to a person (the GPIO settings' own names). Empty: nothing wrong.
	"""
	labels = labels or {}
	def label(name: str) -> str:
		return labels.get(name, name)
	problems: list[str] = []
	taken = panel_lines(panel)
	seen: dict[int, str] = {}
	for name, pin in pins.items():
		if not FIRST_PIN <= pin <= LAST_PIN:
			problems.append(f"The {label(name)} is on pin {pin}, which is not a GPIO pin of the header ({FIRST_PIN} to {LAST_PIN}).")
		elif pin in taken:
			problems.append(f"The {label(name)} is on pin {pin}, which the panel uses ({taken[pin]}): choose another pin.")
		elif pin in seen:
			problems.append(f"The {label(name)} and the {label(seen[pin])} are both on pin {pin}: each needs its own.")
		seen.setdefault(pin, name)
	return problems
