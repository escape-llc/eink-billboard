"""
The image part of a Generated Image on OpenAI (`AiImageApi`): the task's `imageModel`, `quality` and `moderation`, through the OpenAI provider
(`dsec.use`), which holds the key. What the model takes is its family's (`openai_api/models.py`): `gpt-image-2` and later draw in the panel's own shape.
"""
from io import BytesIO
from typing import Any, Mapping

from PIL import Image

from ...model.configuration_manager import ConfigurationManager
from ...plugins.plugin_base import PermanentError
from ..ai.parts import AiImageApi
from ..ai.prompt import master_prompts, with_canvas
from ..data_source import DataSourceExecutionContext
from ..openai_api.models import DEFAULT_IMAGE_MODEL, MODERATIONS, family_of, is_retired, quality_for, size_for
from ..openai_api.openai_api import OpenAIApi

# the provider it asks: its descriptor's id, never a value from a request
PROVIDER_ID = "openai"

def _size(value: Any, fallback: int) -> int:
	return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else fallback

class OpenAIImageAsync(AiImageApi):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Image.Image:
		model = str(params.get("imageModel") or DEFAULT_IMAGE_MODEL)
		if is_retired(model):
			raise PermanentError(f"OpenAI retired the image model {model}: choose another in the task.")
		family = family_of(model)
		if family is None:
			raise PermanentError(f"{model} is not an OpenAI image model this can use: choose another in the task.")
		width, height = _size(params.get("width"), dsec.dimensions[0]), _size(params.get("height"), dsec.dimensions[1])
		moderation = params.get("moderation")
		provider, provider_dsec = dsec.use(PROVIDER_ID, OpenAIApi)
		png = await provider.open_async(provider_dsec, {
			"request": "image",
			"model": model,
			"prompt": with_canvas(master_prompts(dsec.provider.required(ConfigurationManager)), str(params.get("prompt") or "")),
			"size": size_for(family, width, height),
			"quality": quality_for(family, params.get("quality")),
			"moderation": moderation if moderation in MODERATIONS else "auto",
		})
		image = Image.open(BytesIO(png))
		image.load()
		return image.convert("RGB")
