from typing import Any, Mapping, cast
from PIL import Image
import logging
from io import BytesIO
import base64

import httpx
import openai

from ...plugins.plugin_base import PermanentError
from ...task.async_http_worker_pool import AsyncHttpWorkerPool, tls_context
from ...utils.image_utils import blurred_margin
from ...model.configuration_manager import DatasourceConfigurationManager
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from .models import DEFAULT_IMAGE_MODEL, DEFAULT_TEXT_MODEL, MODERATIONS, family_of, is_retired, quality_for, size_for

TIMEOUT = 120.0

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
	named = f" {model}" if model else ""
	if isinstance(error, openai.AuthenticationError):
		return PermanentError("OpenAI refused the API key: check it in the OpenAI Image settings.")
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
	if not api_key:
		raise PermanentError("Enter the OpenAI API key in the OpenAI Image settings.")
	return str(api_key)

class OpenAIAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		api_key = stored_api_key(dsec.provider.required(DatasourceConfigurationManager))
		image_model = params.get("imageModel") or DEFAULT_IMAGE_MODEL
		if is_retired(image_model):
			raise PermanentError(f"OpenAI retired the image model {image_model}: choose another in the task.")
		family = family_of(image_model)
		if family is None:
			raise PermanentError(f"{image_model} is not an image model this data source can use: choose another in the task.")
		moderation = params.get("moderation")
		width, height = target_dimensions(dsec)
		return [{
			"api_key": api_key,
			"text_prompt": params.get("prompt") or "",
			"image_model": image_model,
			"image_quality": quality_for(family, params.get("quality")),
			"size": size_for(family, width, height),
			"moderation": moderation if moderation in MODERATIONS else "auto",
			"randomize_prompt": params.get("randomizePrompt") is True,
			"prompt_model": params.get("promptModel") or DEFAULT_TEXT_MODEL,
		}]
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		image = await self._dispatch_image(state)
		# a free size has the panel's shape already (a margin of a pixel or two at most); a fixed size gets the picture's own blur around it
		return None if image is None else MediaRenderResult(image=blurred_margin(image, target_dimensions(dsec)), title=f"OpenAI Image: {state.get('text_prompt') or 'Untitled'}")
	async def _dispatch_image(self, state: Mapping[str, Any]) -> Image.Image | None:
		image_model = state.get("image_model") or DEFAULT_IMAGE_MODEL
		# the model being asked, so that a failure names the right one
		asking = image_model
		try:
			# the client owns a connection pool: close it when done
			async with openai_client(state["api_key"]) as ai_client:
				prompt = state.get("text_prompt") or ""
				if state.get("randomize_prompt"):
					asking = state.get("prompt_model") or DEFAULT_TEXT_MODEL
					prompt = await OpenAIAsync.fetch_image_prompt(self.logger, ai_client, asking, prompt)
					asking = image_model
				return await OpenAIAsync.fetch_image(self.logger, ai_client, prompt, model=image_model, quality=state.get("image_quality") or "auto",
					size=state.get("size") or "1024x1024", moderation=state.get("moderation") or "auto")
		except PermanentError:
			raise
		except Exception as e:
			problem = openai_problem(e, asking)
			# the type and our words only: the exception's text can quote the key
			self.logger.error(f"OpenAI request failed ({type(e).__name__}): {problem}")
			raise problem from None
	@staticmethod
	async def fetch_image(logger, ai_client, prompt: str, model: str = DEFAULT_IMAGE_MODEL, quality: str = "auto", size: str = "1024x1024", moderation: str = "auto") -> Image.Image:
		"""
		One picture from `images.generate`. A GPT image model always answers base64 (`response_format` and `style` are for the retired DALL·E);
		the background is opaque, as the panel has no transparency.
		"""
		logger.info(f"fetch_image model: {model}, quality: {quality}, size: {size}, prompt: {prompt}")
		prompt += (
			". The image should fully occupy the entire canvas without any frames, "
			"borders, or cropped areas. No blank spaces or artificial framing. "
			"Focus on simplicity, bold shapes, and strong contrast to enhance clarity "
			"and visual appeal. Avoid excessive detail or complex gradients, ensuring "
			"the design works well with flat, vibrant colors."
		)
		response = await ai_client.images.generate(model=model, prompt=prompt, size=size, quality=quality, moderation=moderation,
			background="opaque", output_format="png", n=1)
		data = response.data[0].b64_json if response.data else None
		if not data:
			raise RuntimeError("OpenAI answered without a picture.")
		img = Image.open(BytesIO(base64.b64decode(data)))
		img.load()
		return img.convert("RGB")
	@staticmethod
	async def fetch_image_prompt(logger, ai_client, model: str = DEFAULT_TEXT_MODEL, from_prompt: str | None = None) -> str:
		"""A new prompt from a text model (the Responses API, which every current text model takes); the prompt given when the answer is empty."""
		logger.info(f"fetch_image_prompt model: {model}")
		instructions = (
			"You are a creative assistant generating extremely random and unique image prompts. "
			"Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
			"of art style, medium, subjects, time periods, and moods. No repetition. Prompts "
			"should be 20 words or less and specify random artist, movie, tv show or time period "
			"for the theme. Do not provide any headers or repeat the request, just provide the "
			"updated prompt in your response."
		)
		user_content = (
			"Give me a completely random image prompt, something unexpected and creative! "
			"Let's see what your AI mind can cook up!"
		)
		if from_prompt and from_prompt.strip():
			instructions = (
				"You are a creative assistant specializing in generating highly descriptive "
				"and unique prompts for creating images. When given a short or simple image "
				"description, your job is to rewrite it into a more detailed, imaginative, "
				"and descriptive version that captures the essence of the original while "
				"making it unique and vivid. Avoid adding irrelevant details but feel free "
				"to include creative and visual enhancements. Avoid common themes. Focus on "
				"unexpected, unconventional, and bizarre combinations of art style, medium, "
				"subjects, time periods, and moods. Do not provide any headers or repeat the "
				"request, just provide your updated prompt in the response. Prompts "
				"should be 20 words or less and specify random artist, movie, tv show or time "
				"period for the theme."
			)
			user_content = (
				f"Original prompt: \"{from_prompt}\"\n"
				"Rewrite it to make it more detailed, imaginative, and unique while staying "
				"true to the original idea. Include vivid imagery and descriptive details. "
				"Avoid changing the subject of the prompt."
			)
		response = await ai_client.responses.create(model=model, instructions=instructions, input=user_content)
		prompt = (response.output_text or "").strip()
		logger.info(f"fetch_image_prompt.Generated: {prompt}")
		return prompt or (from_prompt or "")
