"""
A Weather Visualizer: a picture of the weather, drawn from a prompt that talks about it. The task's prompt has fields (`{temp}`, `{condition}`, `{daypart}`; the list
is the weather contract's, `contracts/weather.py`, and the device's weather provider supplies the values), filled from the report for the device's location; the picture is then made as the Generated
Image makes one (an optional rewrite by a text part, an image part, a blurred margin: `ai/generate.py`).

Soft by default: when the weather provider cannot be reached the prompt is made with what is known (a field with no value drops out) and the picture is still drawn. A key or
a location that is not set (a `PermanentError`) is the user's to fix, and reaches the error page like the weather's own.
"""
import logging
import re
from typing import Any, Mapping

from ...plugins.plugin_base import PermanentError
from ...utils.prompt_tokens import fill_tokens
from ..ai.generate import check_parts, generate
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult
from ..contracts.weather import WeatherApi

logger = logging.getLogger(__name__)

def tidy(text: str) -> str:
	"""A prompt after its fields dropped out: no doubled spaces, no space before a mark, no empty line."""
	lines = (re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]+", " ", line)).strip() for line in text.splitlines())
	return "\n".join(line for line in lines if line)

async def weather_fields(dsec: DataSourceExecutionContext) -> dict[str, str]:
	"""
	The values of the weather fields now. A failure that is not the user's to fix leaves its fields out: all of them, or the forecast's (high, low, rain) when
	only the forecast could not be had.
	"""
	api, api_dsec = dsec.provide(WeatherApi)
	try:
		return dict(api.prompt_fields(await api.open_async(api_dsec, { "needs": ["current", "forecast"] })))
	except PermanentError:
		raise
	except Exception as e:
		logger.warning(f"The weather could not be had for the prompt ({type(e).__name__}); using what is known.")
	fields: dict[str, str] = {}
	for need in ("current", "forecast"):
		try:
			fields.update(api.prompt_fields(await api.open_async(api_dsec, { "needs": [need] })))
		except PermanentError:
			raise
		except Exception:
			pass
	return fields

class WeatherImageAsync(DataSource, MediaListAsync, MediaRenderAsync):
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		template = str(params.get("weatherPrompt") or "").strip()
		if not template:
			raise PermanentError("Write the prompt in the task.")
		check_parts(dsec, params)
		return [{ "prompt": tidy(fill_tokens(template, await weather_fields(dsec))) }]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, dict):
			return None
		return await generate(dsec, params, str(state.get("prompt") or ""), "Weather Visualizer")
