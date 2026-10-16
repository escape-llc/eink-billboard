"""
OpenAI as an API data source (`DataSourceApi`): the key, the models it may use, and the calls; nothing drawn. Its text and image parts (`openai-text`,
`openai-image`) ask it with `dsec.use`, and its routes (`api.py`) list the models for the forms. What each model takes is in `models.py`.
"""
import base64
import logging
from typing import Any, Mapping, cast

import httpx
import openai

from ...model.configuration_manager import DatasourceConfigurationManager
from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context
from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext
from ..response_cache import cached

TIMEOUT = 120.0
# the model list changes when OpenAI adds or retires a model: kept a day unless the settings say otherwise
DEFAULT_MODELS_HOURS = 24.0

logger = logging.getLogger(__name__)

def openai_client(api_key: str) -> openai.AsyncOpenAI:
	"""A client on an HTTP client of ours: our TLS context (see `tls_context`), and in the tests the fake internet. Closing it closes both."""
	http = httpx.AsyncClient(transport=AsyncHttpWorkerPool.default_transport, verify=tls_context(), timeout=TIMEOUT)
	# the SDK runs on `httpx2` and is typed for its client, but takes an `httpx` one too (`openai._httpx2`, the legacy client): ours is httpx, as the pool's is
	return openai.AsyncOpenAI(api_key=api_key, timeout=TIMEOUT, max_retries=2, http_client=cast(Any, http))

def _code(error: openai.APIStatusError) -> str:
	"""OpenAI's error code (`invalid_api_key`, `model_not_found`, ...): only the code reaches a message, never OpenAI's text (it can quote the key)."""
	body = error.body
	if isinstance(body, dict):
		inner = body.get("error") if isinstance(body.get("error"), dict) else body
		code = inner.get("code") if isinstance(inner, dict) else None
		if isinstance(code, str) and code.replace("_", "").isalnum() and len(code) <= 60:
			return code
	return ""

def openai_problem(error: Exception, model: str = "") -> Exception:
	"""
	What went wrong, in our words: a PermanentError when trying again cannot help (the key, the model, the account's credit), else a RuntimeError.
	Never the exception's text, which can hold the key.
	"""
	if isinstance(error, PermanentError):
		return error
	return explain_failure(error, model)

def explain_failure(error: Exception, model: str = "") -> Exception:
	"""`openai_problem` for an error that is not already ours: only OpenAI's classes and codes decide the words, never the error's text."""
	named = f" {model}" if model else ""
	if isinstance(error, openai.AuthenticationError):
		return PermanentError("OpenAI refused the API key: check it in the OpenAI settings.")
	if isinstance(error, openai.PermissionDeniedError):
		return PermanentError(f"OpenAI does not let this key use the model{named} (the organization may need to be verified).")
	if isinstance(error, openai.NotFoundError):
		return PermanentError(f"OpenAI does not offer the model{named} to this key: choose another in the task.")
	if isinstance(error, openai.RateLimitError):
		if _code(error) == "insufficient_quota":
			return PermanentError("The OpenAI account has no credit left.")
		return RuntimeError("OpenAI is busy (429): it is tried again later.")
	if isinstance(error, openai.BadRequestError):
		code = _code(error)
		return RuntimeError(f"OpenAI refused the request ({code})." if code else "OpenAI refused the request.")
	if isinstance(error, openai.APIStatusError):
		return RuntimeError(f"OpenAI answered {error.status_code}.")
	if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException)):
		return RuntimeError("OpenAI did not answer in time.")
	if isinstance(error, (openai.APIConnectionError, httpx.HTTPError)):
		return RuntimeError("Could not reach OpenAI.")
	return RuntimeError(f"The OpenAI request failed ({type(error).__name__}).")

def stored_api_key(dscm: DatasourceConfigurationManager) -> str:
	_, settings = dscm.open().get()
	api_key = (settings or {}).get("apiKey")
	if not isinstance(api_key, str) or not api_key.strip():
		raise PermanentError("Enter the OpenAI API key in the OpenAI settings.")
	return api_key.strip()

async def list_model_ids(api_key: str) -> list[str]:
	"""Every model the key may use, as OpenAI lists them (ids only)."""
	async with openai_client(api_key) as client:
		return [model.id async for model in client.models.list()]

class OpenAIApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)` by `params["request"]`:
	- `models`: `{ "ids": [...] }`, every model the key may use (kept for the settings' `modelsCacheHours`, shared by the forms and the tasks);
	- `text` (`model`, `instructions`, `input`): the text the model wrote (`str`), through the Responses API;
	- `image` (`model`, `prompt`, `size`, `quality`, `moderation`): the picture, PNG `bytes`, from `images.generate` (opaque, base64: a GPT image model
	  never answers an address). Never kept: each is a new picture.
	Failures are in our words (`openai_problem`): a PermanentError when trying again cannot help.
	"""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		api_key = stored_api_key(dscm)
		request = params.get("request")
		model = str(params.get("model") or "")
		try:
			if request == "models":
				rev, settings = dscm.open().get()
				async def fetch() -> Mapping[str, Any]:
					return { "ids": await list_model_ids(api_key) }
				# the settings' revision names the key without holding it: another key is another list
				answer = await cached(dscm, settings or {}, f"models|{rev}", dsec.timestamp, fetch, DEFAULT_MODELS_HOURS, "modelsCacheHours")
				return { "ids": [str(i) for i in answer.get("ids") or []] }
			if request == "text":
				async with openai_client(api_key) as client:
					response = await client.responses.create(model=model, instructions=str(params.get("instructions") or ""), input=str(params.get("input") or ""))
				return (response.output_text or "").strip()
			if request == "image":
				async with openai_client(api_key) as client:
					picture = await client.images.generate(model=model, prompt=str(params.get("prompt") or ""), size=str(params.get("size") or "1024x1024"),
						quality=params.get("quality") or "auto", moderation=params.get("moderation") or "auto", background="opaque", output_format="png", n=1)
		except Exception as e:
			problem = openai_problem(e, model)
			if problem is not e:
				# the type and our words only: the exception's text can quote the key
				logger.error(f"OpenAI request failed ({type(e).__name__}): {problem}")
			raise problem from None
		if request != "image":
			raise PermanentError(f"Unknown OpenAI request: {request!r}")
		data = picture.data[0].b64_json if picture.data else None
		if not data:
			raise RuntimeError("OpenAI answered without a picture.")
		return base64.b64decode(data)
