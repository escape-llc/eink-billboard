"""The text part of a Generated Image on Google (`AiTextApi`): the task's `textModel` writes, through the Google AI provider (`dsec.use`), which holds the key."""
from typing import Any, Mapping

from ..contracts.ai import AiTextApi
from ..data_source import DataSourceExecutionContext
from ..google_api.google_api import GoogleApi
from ..google_api.models import DEFAULT_TEXT_MODEL

# the provider it asks: its descriptor's id, never a value from a request
PROVIDER_ID = "google-api"

class GoogleTextAsync(AiTextApi):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> str:
		provider, provider_dsec = dsec.use(PROVIDER_ID, GoogleApi)
		model = str(params.get("textModel") or DEFAULT_TEXT_MODEL)
		return await provider.open_async(provider_dsec, { "request": "text", "model": model, "instructions": params.get("instructions") or "", "input": params.get("input") or "" })
