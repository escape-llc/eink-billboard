"""
What a generator (a master that draws a picture from a prompt) does once it has its prompt: the text part rewrites it (when the task says so), the image part draws it,
and the picture is fitted to the panel. The Generated Image and the Weather Visualizer differ only in where the prompt comes from.
"""
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...utils.image_utils import blurred_margin
from ..data_source import DataSourceExecutionContext, MediaRenderResult, target_dimensions, enhanced
from ..contracts.ai import AiImageApi, AiTextApi
from ..gallery.offer import offer_to_gallery
from .prompt import master_prompts, rewrite_request

def chosen(params: Mapping[str, Any], name: str, what: str) -> str:
	"""The id of the part a field chooses: only a key into the loaded data sources (`dsec.use` finds it, and opens it by its own id)."""
	part = params.get(name)
	if not isinstance(part, str) or not part:
		raise PermanentError(f"Choose the {what} in the task.")
	return part

def check_parts(dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> None:
	"""Both parts are found before anything is asked of a provider, so a missing one costs nothing."""
	dsec.use(chosen(params, "imageSource", "image source"), AiImageApi)
	if params.get("randomizePrompt") is True:
		dsec.use(chosen(params, "textSource", "text source"), AiTextApi)

async def generate(dsec: DataSourceExecutionContext, params: Mapping[str, Any], prompt: str, label: str, origin: str) -> MediaRenderResult:
	"""
	The picture for `prompt`: rewritten first when the task says `randomizePrompt`, then drawn, then fitted to the panel with a blurred margin.
	The picture as drawn is offered to the Gallery (#238) first (unless the task says `keepInGallery: false`), under the data source that asked for it (`origin`): it cost money, and the Gallery can show it again.
	"""
	if params.get("randomizePrompt") is True:
		text, text_dsec = dsec.use(chosen(params, "textSource", "text source"), AiTextApi)
		instructions, given = rewrite_request(master_prompts(dsec.provider.required(ConfigurationManager)), prompt)
		prompt = (await text.open_async(text_dsec, { **params, "instructions": instructions, "input": given })) or prompt
	image, image_dsec = dsec.use(chosen(params, "imageSource", "image source"), AiImageApi)
	width, height = target_dimensions(dsec)
	picture = await image.open_async(image_dsec, { **params, "prompt": prompt, "width": width, "height": height })
	# a picture in the panel's shape (a model that takes any size) fills it; another gets the picture's own blur around it
	title = f"{label}: {prompt or 'Untitled'}"
	if params.get("keepInGallery") is not False:
		offer_to_gallery(dsec, origin, picture, title, prompt or None)
	return MediaRenderResult(image=enhanced(dsec, blurred_margin(picture, (width, height))), title=title, original=picture)
