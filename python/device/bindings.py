"""
What an input means. A device only says that something happened (`InputEvent`: its name, which input, which gesture); the Application decides what that does, here. A button is bound by the
GPIO settings' `triggers`: each row is a pin and an action the Application already has: `play`, `stop`, `next` (the transport commands), `toggle` (play when playback is stopped, else
stop), `task` (run the task the row carries) or `playlist` (seek to the playlist the row names, by id). Only a press is bound; a long press does nothing yet.
"""
from typing import Any, Mapping

from .buttons import input_name

ACTIONS = ("play", "stop", "toggle", "next", "task", "playlist")

def row_for(source: str, name: str, gesture: str, settings: Mapping[str, Any]|None) -> Mapping[str, Any]|None:
	"""The row of the stored `devices` settings an input is bound by, or None when it is bound to nothing (a gesture nobody listens for is not an error)."""
	if source != "buttons" or gesture != "press":
		return None
	rows = (settings or {}).get("triggers")
	for row in rows if isinstance(rows, list) else []:
		pin = row.get("pin") if isinstance(row, dict) else None
		if isinstance(pin, int) and not isinstance(pin, bool) and input_name(pin) == name:
			return row if row.get("action") in ACTIONS else None
	return None

def action_for(source: str, name: str, gesture: str, settings: Mapping[str, Any]|None) -> str|None:
	"""The action an input is bound to by the stored `devices` settings, or None when it is bound to nothing."""
	row = row_for(source, name, gesture, settings)
	return row["action"] if row is not None else None

def row_with_pin(settings: Mapping[str, Any]|None, pin: int) -> Mapping[str, Any]|None:
	"""The row of the stored `devices` settings for a pin, whatever its action (the web app's Run now names a button by its pin)."""
	rows = (settings or {}).get("triggers")
	return next((row for row in rows if isinstance(row, dict) and row.get("pin") == pin), None) if isinstance(rows, list) else None
