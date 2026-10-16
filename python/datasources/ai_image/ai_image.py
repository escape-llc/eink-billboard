"""
A Generated Image: a prompt, optionally rewritten by a text part, drawn by an image part. The task chooses each part (`textSource`, `imageSource`:
data sources with the `ai-text` and `ai-image` features), so the text of one provider can go with the picture of another (GPT text, a Google picture).
The parts are API data sources (data only); this is the one that renders. Their fields are in the same task content; their providers hold the keys.
"""
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...utils.image_utils import blurred_margin
from ..ai.parts import AiImageApi, AiTextApi
from ..ai.prompt import master_prompts, rewrite_request
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

def _chosen(params: Mapping[str, Any], name: str, what: str) -> str:
	"""The id of the part a field chooses: only a key into the loaded data sources (`dsec.use` finds it, and opens it by its own id)."""
	chosen = params.get(name)
	if not isinstance(chosen, str) or not chosen:
		raise PermanentError(f"Choose the {what} in the task.")
	return chosen

class GeneratedImageAsync(DataSource, MediaListAsync, MediaRenderAsync):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		# both parts are found before anything is asked of a provider, so a missing one costs nothing
		dsec.use(_chosen(params, "imageSource", "image source"), AiImageApi)
		if params.get("randomizePrompt") is True:
			dsec.use(_chosen(params, "textSource", "text source"), AiTextApi)
		return [{ "prompt": str(params.get("prompt") or "") }]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, dict):
			return None
		prompt = str(state.get("prompt") or "")
		if params.get("randomizePrompt") is True:
			text, text_dsec = dsec.use(_chosen(params, "textSource", "text source"), AiTextApi)
			instructions, given = rewrite_request(master_prompts(dsec.provider.required(ConfigurationManager)), prompt)
			prompt = (await text.open_async(text_dsec, { **params, "instructions": instructions, "input": given })) or prompt
		image, image_dsec = dsec.use(_chosen(params, "imageSource", "image source"), AiImageApi)
		width, height = target_dimensions(dsec)
		picture = await image.open_async(image_dsec, { **params, "prompt": prompt, "width": width, "height": height })
		# a picture in the panel's shape (a model that takes any size) fills it; another gets the picture's own blur around it
		return MediaRenderResult(image=blurred_margin(picture, (width, height)), title=f"Generated Image: {prompt or 'Untitled'}")
