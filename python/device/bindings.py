"""
What an input means. A device only says that something happened (`InputEvent`: its name, which input, which gesture); the Application decides what that does, here. Each binding is an action
the Application already has: `play`, `stop`, `next` (the transport commands) or `toggle` (play when playback is stopped, else stop).
"""
from typing import Mapping

# (source, input, gesture) -> action
DEFAULT_BINDINGS: Mapping[tuple[str, str, str], str] = {
	("buttons", "play-stop", "press"): "toggle",
	("buttons", "next", "press"): "next",
	("buttons", "stop", "press"): "stop",
}

def action_for(source: str, name: str, gesture: str, bindings: Mapping[tuple[str, str, str], str] = DEFAULT_BINDINGS) -> str|None:
	"""The action an input is bound to, or None when it is bound to nothing (a gesture nobody listens for is not an error)."""
	return bindings.get((source, name, gesture))
