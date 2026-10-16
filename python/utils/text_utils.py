"""Text that comes from outside (feeds, answers, HTML attributes) and is shown on the panel."""
import html

# an entity is read once per pass; markup that was escaped twice (`&amp;quot;`) or three times needs more. More than this is not escaping, it is the text.
MAX_UNESCAPES = 4

def unescape_text(value: str) -> str:
	"""
	Character entities read until none are left to read (`&quot;`, `&#039;`, `&amp;quot;`, `&hellip;`: named, decimal and hex), up to `MAX_UNESCAPES`
	passes. A feed that escaped its text twice (Dinosaur Comics) gives the same page as one that escaped it once. Text that really holds a
	literal `&amp;` is read as `&` too: on a billboard, a visible entity is always the lesser evil.
	"""
	for _ in range(MAX_UNESCAPES):
		decoded = html.unescape(value)
		if decoded == value:
			break
		value = decoded
	return value
