"""
A Generated Image: a prompt, optionally rewritten by a text part, drawn by an image part. The task chooses each part (`textSource`, `imageSource`:
data sources with the `ai-text` and `ai-image` features), so the text of one provider can go with the picture of another (GPT text, a Google picture).
The parts are API data sources (data only); this is the one that renders. Their fields are in the same task content; their providers hold the keys.
"""
from typing import Any, Mapping

from ..ai.generate import check_parts, generate
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult

class GeneratedImageAsync(DataSource, MediaListAsync, MediaRenderAsync):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		check_parts(dsec, params)
		return [{ "prompt": str(params.get("prompt") or "") }]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, dict):
			return None
		return await generate(dsec, params, str(state.get("prompt") or ""), "Generated Image")
