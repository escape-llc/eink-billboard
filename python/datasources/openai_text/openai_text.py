"""The text part of a Generated Image on OpenAI (`AiTextApi`): the task's `textModel` writes, through the OpenAI provider (`dsec.use`), which holds the key."""
from typing import Any, Mapping

from ..ai.parts import AiTextApi
from ..data_source import DataSourceExecutionContext
from ..openai_api.models import DEFAULT_TEXT_MODEL
from ..openai_api.openai_api import OpenAIApi

# the provider it asks: its descriptor's id, never a value from a request
PROVIDER_ID = "openai"

class OpenAITextAsync(AiTextApi):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> str:
		provider, provider_dsec = dsec.use(PROVIDER_ID, OpenAIApi)
		model = str(params.get("textModel") or DEFAULT_TEXT_MODEL)
		return await provider.open_async(provider_dsec, { "request": "text", "model": model, "instructions": params.get("instructions") or "", "input": params.get("input") or "" })
