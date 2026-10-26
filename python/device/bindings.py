"""
What an input means. A device only says that something happened (`InputEvent`: its name, which input, which gesture); the Application decides what that does, here. A button is bound by the
Devices settings' `triggers`: each row is a pin and an action the Application already has: `play`, `stop`, `next` (the transport commands) or `toggle` (play when playback is stopped, else
stop). Only a press is bound; a long press does nothing yet.
"""
from typing import Any, Mapping

from .buttons import input_name

ACTIONS = ("play", "stop", "toggle", "next")

def action_for(source: str, name: str, gesture: str, settings: Mapping[str, Any]|None) -> str|None:
	"""The action an input is bound to by the stored `devices` settings, or None when it is bound to nothing (a gesture nobody listens for is not an error)."""
	if source != "buttons" or gesture != "press":
		return None
	rows = (settings or {}).get("triggers")
	for row in rows if isinstance(rows, list) else []:
		pin = row.get("pin") if isinstance(row, dict) else None
		if isinstance(pin, int) and not isinstance(pin, bool) and input_name(pin) == name:
			action = row.get("action")
			return action if action in ACTIONS else None
	return None
