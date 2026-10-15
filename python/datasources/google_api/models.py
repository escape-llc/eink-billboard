"""
What Google's Gemini API takes, from its own description of itself: the discovery document (`$discovery/rest?version=v1beta`), which lists the
aspect ratios and image sizes `ImageConfig` accepts and the output modalities `GenerationConfig` knows. The model list (`GET v1beta/models`) has
no output modality, so which models draw is a rule by id (`-image`, `nano-banana`), and the limits Google documents outside the schema are kept
here as exceptions to the discovered sets (Flash Lite Image takes only `1K`; Nano Banana 2.1 has no `512`).
"""
from dataclasses import dataclass
import math
import re
from typing import Any, Mapping

# today's values, used when the discovery document cannot be read or understood
FALLBACK_RATIOS = ("1:1", "1:4", "4:1", "1:8", "8:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
FALLBACK_SIZES = ("512", "1K", "2K", "4K")
SIZE_ORDER = ("512", "1K", "2K", "4K")

DEFAULT_IMAGE_MODEL = "gemini-nano-banana-2.1"
DEFAULT_TEXT_MODEL = "gemini-3.5-flash"

# a model id goes into a path: only these characters, never anything a URL could read as more
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,80}$")
# an AI Studio key: an authorization key, "AQ." and then its token (the older "AIza" standard keys are not accepted)
KEY = re.compile(r"^AQ\.[A-Za-z0-9._\-]+$")

# the qualities a Google image part offers, and the image size each asks for (clamped to what the model takes)
QUALITY_SIZES = { "auto": "1K", "low": "1K", "medium": "1K", "high": "2K", "xhigh": "4K", "max": "4K" }
QUALITY_NAMES = { "auto": "Auto (1K)", "high": "High (2K)", "max": "Maximum (4K)" }

@dataclass(frozen=True)
class Vocabulary:
	"""What the discovery document says `generateContent` takes for a picture."""
	ratios: tuple[str, ...]
	sizes: tuple[str, ...]
	image_output: bool
	discovered: bool

FALLBACK = Vocabulary(FALLBACK_RATIOS, FALLBACK_SIZES, True, False)

def _values(prop: Any, pattern: str) -> tuple[str, ...]:
	"""A property's allowed values: its `enum` where the schema has one, else the backticked values its description lists."""
	if not isinstance(prop, dict):
		return ()
	enum = prop.get("enum")
	found: list[Any] = enum if isinstance(enum, list) else re.findall(r"`([^`]+)`", str(prop.get("description") or ""))
	return tuple(dict.fromkeys(v for v in found if isinstance(v, str) and re.fullmatch(pattern, v)))

def read_discovery(doc: Mapping[str, Any]) -> Vocabulary | None:
	"""The vocabulary of a discovery document, or None when it does not say what is needed (the fallback is used then)."""
	schemas = doc.get("schemas") if isinstance(doc, dict) else None
	if not isinstance(schemas, dict):
		return None
	image = ((schemas.get("ImageConfig") or {}).get("properties")) or {}
	ratios = _values(image.get("aspectRatio"), r"\d{1,2}:\d{1,2}")
	sizes = _values(image.get("imageSize"), r"\d+K|512")
	modalities = (((schemas.get("GenerationConfig") or {}).get("properties") or {}).get("responseModalities") or {})
	enum = (modalities.get("items") or {}).get("enum") if isinstance(modalities, dict) else None
	if not ratios or not sizes or not isinstance(enum, list):
		return None
	return Vocabulary(ratios, tuple(s for s in SIZE_ORDER if s in sizes), "IMAGE" in enum, True)

def is_image_model(model: str) -> bool:
	return "-image" in model or "nano-banana" in model

_NOT_TEXT = ("image", "nano-banana", "embedding", "tts", "live", "audio", "robotics", "computer-use", "aqa")

def is_text_model(model: str) -> bool:
	return model.startswith("gemini-") and not any(part in model for part in _NOT_TEXT)

def sizes_for(model: str, vocabulary: Vocabulary) -> tuple[str, ...]:
	"""The image sizes the model takes: the discovered ones, less what Google documents this model does not take."""
	if "flash-lite-image" in model:
		return tuple(s for s in vocabulary.sizes if s == "1K") or ("1K",)
	if "nano-banana" in model:
		return tuple(s for s in vocabulary.sizes if s != "512")
	return vocabulary.sizes

def size_for(model: str, quality: Any, vocabulary: Vocabulary) -> str:
	"""The image size a quality asks for, clamped to what the model takes: the largest it takes up to it, else its smallest."""
	wanted = QUALITY_SIZES.get(str(quality), "1K")
	taken = sizes_for(model, vocabulary)
	fitting = [s for s in taken if SIZE_ORDER.index(s) <= SIZE_ORDER.index(wanted)]
	return fitting[-1] if fitting else (taken[0] if taken else "1K")

def ratio_for(width: int, height: int, vocabulary: Vocabulary) -> str:
	"""The allowed aspect ratio nearest the panel's shape, measured on a log scale (so 2:1 is as far from 1:1 as 1:2 is)."""
	target = math.log(max(1, width) / max(1, height))
	def distance(ratio: str) -> float:
		w, h = (int(v) for v in ratio.split(":"))
		return abs(math.log(w / h) - target)
	return min(vocabulary.ratios, key=distance)

def model_ids(page: Mapping[str, Any]) -> list[str]:
	"""The models of one page of the list that answer `generateContent`, by their base id (`models/` dropped), and only well-formed ids."""
	found = []
	for model in page.get("models") or []:
		if not isinstance(model, dict) or "generateContent" not in (model.get("supportedGenerationMethods") or []):
			continue
		ident = str(model.get("baseModelId") or str(model.get("name") or "").removeprefix("models/"))
		if MODEL_ID.match(ident):
			found.append(ident)
	return found

def image_models(ids: list[str]) -> list[str]:
	return sorted(dict.fromkeys(m for m in ids if is_image_model(m)), key=lambda m: (len(m), m))

def text_models(ids: list[str]) -> list[str]:
	return sorted(dict.fromkeys(m for m in ids if is_text_model(m)), key=lambda m: (len(m), m))

def describe_models(ids: list[str], vocabulary: Vocabulary) -> list[dict]:
	"""Each image model with what it takes: the route that says so (`GET .../models`)."""
	return [{ "id": m, "ratios": list(vocabulary.ratios), "sizes": list(sizes_for(m, vocabulary)), "discovered": vocabulary.discovered } for m in image_models(ids)]
