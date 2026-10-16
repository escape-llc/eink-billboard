"""
The fields of a prompt: `{name}` in the text is replaced by a value the data behind it supplies (the weather's `{temp}`, a rewrite's `{prompt}`).

Whatever supplies the values also lists the names it knows, with a description of each (a descriptor's `tokens`, for the form and for validating a saved
text), so a name is never a guess: an unknown one is refused when the text is saved. `{{` and `}}` are a literal brace; any other brace is plain text.
One expression here and in `FormValidation.ts`, so both sides read a text the same way.
"""
import re
from typing import Iterable, Mapping

# `{{`, `}}` (a literal brace), or `{name}` (a field)
TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")

def token_names(text: str) -> list[str]:
	"""The field names a text uses, in order, once each."""
	return list(dict.fromkeys(m.group(1) for m in TOKEN.finditer(text) if m.group(1)))

def unknown_token(text: str, known: Iterable[str]) -> str|None:
	"""The first field in the text that is not one of `known`, or None."""
	allowed = set(known)
	return next((name for name in token_names(text) if name not in allowed), None)

def fill_tokens(text: str, values: Mapping[str, object]) -> str:
	"""The text with each field replaced by its value; a field with no value (missing, None, empty) drops out, as a Describe line's does."""
	def replace(match: re.Match) -> str:
		whole = match.group(0)
		if whole == "{{":
			return "{"
		if whole == "}}":
			return "}"
		value = values.get(match.group(1))
		return "" if value is None else str(value)
	return TOKEN.sub(replace, text)
