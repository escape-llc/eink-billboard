"""
What OpenAI's models take, which its list API (`GET /v1/models`) does not say: it gives only the ids.

The ids come from the account (the lookup routes in `api.py` list them); what each takes comes from its **family**, found by the id's prefix,
so a dated snapshot (`gpt-image-2-2026-04-21`) is its model and a new model of a known family needs no change here. The table follows
OpenAI's `images.generate` reference: every GPT image model takes the sizes `1024x1024`, `1536x1024` and `1024x1536` and the qualities
`low`, `medium`, `high` and `auto`; `gpt-image-2` and later take any `WIDTHxHEIGHT` (both divisible by 16, a ratio from 1:3 to 3:1, at most
3840x2160), so the picture can have the panel's own shape; the `gpt-image-2.5` models add the qualities `xhigh` and `max`.
DALL·E 2 and 3 were removed from the API on 2026-05-12.
"""
from dataclasses import dataclass

# the qualities, lowest first; `auto` lets the model choose
QUALITY_ORDER = ("low", "medium", "high", "xhigh", "max")
QUALITIES = ("auto", *QUALITY_ORDER)
MODERATIONS = ("auto", "low")

DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_TEXT_MODEL = "gpt-5.6-luna"

# a free size: the long edge (pixels). The cost grows with the pixels, and the panel is smaller than this anyway.
LONG_EDGE = 1536
MAX_SIZE = (3840, 2160)
SIZE_STEP = 16
MAX_RATIO = 3.0

@dataclass(frozen=True)
class Family:
	name: str
	prefixes: tuple[str, ...]
	qualities: tuple[str, ...]
	# any WIDTHxHEIGHT (within the rules above), or only the three fixed sizes
	free_size: bool

FIXED_SIZES = ("1024x1024", "1536x1024", "1024x1536")

# the longest prefix first: `gpt-image-2.5-` is a `gpt-image-2` too
FAMILIES = (
	Family("gpt-image-2.5", ("gpt-image-2.5-",), QUALITIES, True),
	Family("gpt-image-2", ("gpt-image-2",), ("auto", "low", "medium", "high"), True),
	# gpt-image-1, -1-mini, -1.5, chatgpt-image-latest, and a GPT image model this table does not know yet: what every GPT image model takes
	Family("gpt-image", ("gpt-image-", "chatgpt-image-"), ("auto", "low", "medium", "high"), False),
)
RETIRED_PREFIXES = ("dall-e-",)

def family_of(model: str) -> Family | None:
	"""The family of an image model id; None when it is not a GPT image model (a retired DALL·E, a text model, a typo)."""
	for family in FAMILIES:
		if model.startswith(family.prefixes):
			return family
	return None

def is_retired(model: str) -> bool:
	return model.startswith(RETIRED_PREFIXES)

def quality_for(family: Family, wanted: str | None) -> str:
	"""The quality to ask for: the one wanted when the model takes it, else the nearest one below it it does take (`max` on gpt-image-2 is `high`)."""
	if not wanted or wanted == "auto" or wanted not in QUALITY_ORDER:
		return "auto"
	at = QUALITY_ORDER.index(wanted)
	for quality in reversed(QUALITY_ORDER[:at + 1]):
		if quality in family.qualities:
			return quality
	return "auto"

def _step(value: float) -> int:
	return max(SIZE_STEP, int(round(value / SIZE_STEP)) * SIZE_STEP)

def size_for(family: Family, width: int, height: int) -> str:
	"""
	The size to ask for a panel of `width` x `height` (as the viewer sees it). A free size has the panel's ratio (clamped to 1:3 .. 3:1) with
	a long edge of LONG_EDGE, each side a multiple of 16; a fixed size is the one closest in shape (the picture then gets a blurred margin).
	"""
	width, height = max(1, width), max(1, height)
	ratio = min(max(width / height, 1 / MAX_RATIO), MAX_RATIO)
	if not family.free_size:
		if ratio > 1.15:
			return "1536x1024"
		if ratio < 1 / 1.15:
			return "1024x1536"
		return "1024x1024"
	long = float(LONG_EDGE)
	w, h = (long, long / ratio) if ratio >= 1 else (long * ratio, long)
	return f"{min(_step(w), MAX_SIZE[0])}x{min(_step(h), MAX_SIZE[1])}"

def image_models(ids: list[str]) -> list[str]:
	"""The image models of a model list that this data source can drive: the newest family first, plain names before their dated snapshots."""
	found = { m: family for m in ids if (family := family_of(m)) is not None }
	return sorted(found, key=lambda m: (FAMILIES.index(found[m]), len(m), m))

# what a model id says it is not: these are not for writing a line of text
_NOT_TEXT = ("image", "audio", "realtime", "tts", "transcribe", "search", "embedding", "codex", "moderation", "cyber", "deep-research", "instruct")

def text_models(ids: list[str]) -> list[str]:
	"""The models of a model list that can rewrite a prompt (the GPT text models), plain names before dated snapshots."""
	return sorted({ m for m in ids if m.startswith("gpt-") and not any(part in m for part in _NOT_TEXT) }, key=lambda m: (len(m), m))

def describe_models(ids: list[str]) -> list[dict]:
	"""Each image model of the list with what it takes: the route that says so (`GET .../models`)."""
	result = []
	for model in image_models(ids):
		family = family_of(model)
		assert family is not None
		result.append({
			"id": model,
			"family": family.name,
			"qualities": list(family.qualities),
			"size": "free" if family.free_size else "fixed",
			"sizes": [] if family.free_size else list(FIXED_SIZES),
			"moderation": list(MODERATIONS),
		})
	return result
