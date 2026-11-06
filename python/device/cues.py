"""
What the outputs say, and when (#867, #891). One vocabulary of cues for every kind of output: each kind plays a cue in its own medium (an LED blinks, the haptic motor clicks or buzzes, the
sound card plays a tone). The feedback rows are in a section per kind (`FEEDBACK`), each offering its kind's outputs, events and cues (#897): every kind plays the
shared cues, and a kind's own (a haptic effect, a sound, an I²C LED's colour wheel) are added to its section alone, so a row never shows a choice its output cannot play.

An event is what the device says: a gesture (a button's `press`, `long-press`) happens once; a state (`holding`, `problem`, `drawing`) begins and ends.
"""
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class Cue:
	"""A cue's title (the form's, the live view's) and whether it goes on while a state lasts on an output that can hold it (an LED); else it plays once."""
	title: str
	repeat: bool

# the cues a person chooses from, by the value stored in the settings; the order is the list's in the form (the schema's `cues` lookup says the same titles)
CUES: Mapping[str, Cue] = {
	"off": Cue("Off", False),
	"one": Cue("One", False),
	"two": Cue("Two", False),
	"three": Cue("Three", False),
	"steady": Cue("Steady", True),
	"slow": Cue("Slow", True),
	"fast": Cue("Fast", True),
	"heartbeat": Cue("Heartbeat", True),
}

# the events a feedback row answers (the schema's `events` lookup), with their words in the live view
GESTURES: Mapping[str, str] = { "press": "a press", "long-press": "a long press" }
# the states, the more urgent first: holding (the cue to let go) before a problem before drawing
STATES: Mapping[str, str] = { "holding": "a button held", "problem": "a problem", "drawing": "the panel drawing" }
EVENTS = (*GESTURES, *STATES)

# the kinds of output (the schema's `kind` of an output row), each with the settings list of its feedback rows and its title in our sentences
FEEDBACK: Mapping[str, str] = { "gpio": "gpioFeedback", "haptic": "hapticFeedback", "audio": "audioFeedback" }
KIND_TITLES: Mapping[str, str] = { "gpio": "GPIO", "haptic": "haptic", "audio": "audio" }
KINDS = tuple(FEEDBACK)
# what each kind's section offers (the schema's `<kind>Cues` and events lookups): a haptic motor is felt only while touching the device, so it answers the buttons alone
KIND_CUES: Mapping[str, tuple[str, ...]] = { kind: tuple(CUES) for kind in KINDS }
KIND_EVENTS: Mapping[str, tuple[str, ...]] = { "gpio": EVENTS, "haptic": ("press", "long-press", "holding"), "audio": EVENTS }
