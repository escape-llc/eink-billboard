"""
The image part of a Generated Image on Google (`AiImageApi`): the task's `imageModel` and `quality`, through the Google AI provider (`dsec.use`),
which holds the key. The aspect ratio is the one Google takes (its discovery document) nearest the panel's; the quality picks the image size.
"""
from io import BytesIO
from typing import Any, Mapping

from PIL import Image

from ...plugins.plugin_base import PermanentError
from ..ai.parts import AiImageApi
from ..ai.prompt import CANVAS
from ..data_source import DataSourceExecutionContext
from ..google_api.google_api import GoogleApi, checked_model
from ..google_api.models import DEFAULT_IMAGE_MODEL, Vocabulary, is_image_model, ratio_for, size_for

# the provider it asks: its descriptor's id, never a value from a request
PROVIDER_ID = "google-ai"

def _size(value: Any, fallback: int) -> int:
	return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else fallback

class GoogleImageAsync(AiImageApi):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Image.Image:
		model = checked_model(str(params.get("imageModel") or DEFAULT_IMAGE_MODEL))
		if not is_image_model(model):
			raise PermanentError(f"{model} is not a Gemini image model: choose another in the task.")
		width, height = _size(params.get("width"), dsec.dimensions[0]), _size(params.get("height"), dsec.dimensions[1])
		provider, provider_dsec = dsec.use(PROVIDER_ID, GoogleApi)
		vocabulary: Vocabulary = await provider.open_async(provider_dsec, { "request": "discovery" })
		data = await provider.open_async(provider_dsec, {
			"request": "image",
			"model": model,
			"prompt": str(params.get("prompt") or "") + CANVAS,
			"aspectRatio": ratio_for(width, height, vocabulary),
			"imageSize": size_for(model, params.get("quality"), vocabulary),
		})
		image = Image.open(BytesIO(data))
		image.load()
		return image.convert("RGB")
