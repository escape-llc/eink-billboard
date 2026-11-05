"""
What the outputs say, and when (#867, #891). One vocabulary of cues for every kind of output: each kind plays a cue in its own medium (an LED blinks, the haptic motor clicks or buzzes, the
sound card plays a tone), so a feedback row chooses a cue the same way whatever its output is.

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

# the kinds of output (the schema's `kind` of an output row)
KINDS = ("gpio", "haptic", "audio")
