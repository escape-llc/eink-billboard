"""
What a text part is asked to do with a prompt, and what an image part adds to every prompt: the same for every provider, and the user's to change.

The texts are the Master Prompts settings (`master-prompts`, a device-wide document; its schema in the NVE holds the factory text, which "restore the default"
restores). A value that is missing or empty is read as the factory text, so a damaged document never leaves a generator without instructions. A prompt may use
fields (`{prompt}`, see `python/utils/prompt_tokens.py`); the schema lists the ones each prompt knows.
"""
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager
from ...utils.prompt_tokens import fill_tokens

SETTINGS = "master-prompts"
# the prompts the document holds
PROMPTS = ("inventInstructions", "inventRequest", "rewriteInstructions", "rewriteRequest", "canvas")

def master_prompts(cm: ConfigurationManager) -> dict[str, str]:
	"""Every master prompt, as the user saved it, or as shipped where it is missing or empty."""
	shipped = cm.shipped_settings(SETTINGS)
	_, stored = cm.settings_manager().open(SETTINGS).get()
	stored = stored if isinstance(stored, dict) else {}
	prompts: dict[str, str] = {}
	for name in PROMPTS:
		value = stored.get(name)
		prompts[name] = value if isinstance(value, str) and value.strip() else str(shipped.get(name) or "")
	return prompts

def rewrite_request(prompts: Mapping[str, str], prompt: str) -> tuple[str, str]:
	"""The `instructions` and the `input` that make a text model write an image prompt: a new one from nothing, or this one made vivid."""
	if not prompt.strip():
		return fill_tokens(prompts["inventInstructions"], {}), fill_tokens(prompts["inventRequest"], {})
	return fill_tokens(prompts["rewriteInstructions"], {}), fill_tokens(prompts["rewriteRequest"], { "prompt": prompt })

def with_canvas(prompts: Mapping[str, Any], prompt: str) -> str:
	"""The prompt an image model gets: the user's words, then what every picture for a panel needs (a panel shows the whole canvas, with few colors)."""
	text = prompt.rstrip()
	if text and text[-1] not in ".!?":
		text += "."
	return f"{text} {fill_tokens(str(prompts['canvas']), {})}".strip()
