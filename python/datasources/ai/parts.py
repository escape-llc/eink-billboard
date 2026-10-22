"""
The parts a Generated Image is made of: a text part (it rewrites the prompt) and an image part (it draws the picture). Each is an API data source
(`DataSourceApi`: data only, it renders nothing) of one provider, chosen by the Generated Image's `textSource` and `imageSource` and asked with
`dsec.use(chosen, AiTextApi / AiImageApi)`; its own fields (the model and the like) are in the same task content. The provider holds the key.
"""
from typing import Any, Mapping

from PIL import Image

from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext

class AiTextApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)`: `params` is the task's content with `instructions` (what the text is for) and `input` (the text to work on) added;
	the answer is the text the model wrote (a `str`). Its own fields (`textModel`) are in the content. A feature `data-ai-text` in its descriptor.
	"""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> str:
		# not abstract: `dsec.use(id, AiTextApi)` takes the class itself
		raise NotImplementedError

class AiImageApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)`: `params` is the task's content with `prompt`, `width` and `height` (the picture the panel shows, as the viewer
	sees it) added; the answer is the picture (an RGB `Image`), whatever its shape (the Generated Image fits it). Its own fields (`imageModel`,
	`quality`, ...) are in the content. A feature `data-ai-image` in its descriptor.
	"""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Image.Image:
		raise NotImplementedError
