"""
The parts a Generated Image is made of: a text part (it rewrites the prompt) and an image part (it draws the picture). Each is a provider of one vendor,
chosen by the Generated Image's `textSource` and `imageSource` (people mix vendors here, so a task always chooses: no device setting) and asked with
`dsec.use(chosen, AiTextApi / AiImageApi)`; its own fields (the model and the like) are in the same task content. The vendor's provider holds the key.
"""
from typing import Any, Mapping

from PIL import Image

from ..data_source import DataSourceExecutionContext
from .provider import ProviderContract

class AiTextApi(ProviderContract):
	"""
	`open_async(dsec, params)`: `params` is the task's content with `instructions` (what the text is for) and `input` (the text to work on) added;
	the answer is the text the model wrote (a `str`). Its own fields (`textModel`) are in the content. A feature `data-ai-text` in its descriptor.
	"""
	capability = "data-ai-text"
	noun = "AI text"
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> str:
		raise NotImplementedError

class AiImageApi(ProviderContract):
	"""
	`open_async(dsec, params)`: `params` is the task's content with `prompt`, `width` and `height` (the picture the panel shows, as the viewer
	sees it) added; the answer is the picture (an RGB `Image`), whatever its shape (the Generated Image fits it). Its own fields (`imageModel`,
	`quality`, ...) are in the content. A feature `data-ai-image` in its descriptor.
	"""
	capability = "data-ai-image"
	noun = "AI image"
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Image.Image:
		raise NotImplementedError
