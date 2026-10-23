"""
Google's Gemini API as an API data source (`DataSourceApi`): the AI Studio key, what the API takes (its discovery document), the models the key may
use, and the calls; nothing drawn. Its text and image parts (`google-text`, `google-image`) ask it with `dsec.use`; its routes (`api.py`) list the
models for the forms.

REST through an HTTP client of ours (`tls_context`, and the tests' fake internet). The key is an AI Studio authorization key (`AQ.`), sent only in the
`x-goog-api-key` header: never in an address (where such keys are refused, and where logs would show it) and never as a Bearer token.
"""
import base64
import logging
from typing import Any, Mapping

import httpx

from ...model.configuration_manager import DatasourceConfigurationManager
from ...plugins.plugin_base import PermanentError
from ..metering import metered_client
from ..data_source import DataSource, DataSourceApi, DataSourceExecutionContext
from ..response_cache import cached
from .models import FALLBACK, KEY, MODEL_ID, Vocabulary, model_ids, read_discovery

API = "https://generativelanguage.googleapis.com/v1beta"
DISCOVERY = "https://generativelanguage.googleapis.com/$discovery/rest"
TIMEOUT = 120.0
MAX_BYTES = 40 * 1024 * 1024
DEFAULT_MODELS_HOURS = 24.0
DEFAULT_DISCOVERY_HOURS = 168.0
MAX_PAGES = 20

logger = logging.getLogger(__name__)

def google_client() -> httpx.AsyncClient:
	return metered_client("google-api", timeout=TIMEOUT)

def stored_api_key(dscm: DatasourceConfigurationManager) -> str:
	_, settings = dscm.open().get()
	api_key = (settings or {}).get("apiKey")
	if not isinstance(api_key, str) or not api_key.strip():
		raise PermanentError("Enter the Google AI Studio API key in the Google AI settings.")
	return checked_key(api_key)

def checked_key(api_key: str) -> str:
	"""An AI Studio key (`AQ.`), or a PermanentError before anything is asked: an older `AIza` key is not one."""
	api_key = api_key.strip()
	if not KEY.match(api_key):
		raise PermanentError("That is not a Google AI Studio key: create one in AI Studio (it starts with AQ.).")
	return api_key

def _token(value: Any) -> str:
	"""A word from Google's answer (a status, a reason), only when it is one: never Google's message, which is not ours to show."""
	return value if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 60 else ""

def google_problem(response: httpx.Response, model: str = "") -> Exception:
	"""What an error answer means, in our words and Google's status word: a PermanentError when trying again cannot help."""
	try:
		error = response.json().get("error") or {}
	except (ValueError, AttributeError):
		error = {}
	status = _token(error.get("status")) if isinstance(error, dict) else ""
	reasons = { _token(d.get("reason")) for d in (error.get("details") or []) if isinstance(d, dict) } if isinstance(error, dict) else set()
	named = f" {model}" if model else ""
	code = response.status_code
	if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in reasons:
		return PermanentError("Google did not accept this key type here: create a new key in Google AI Studio.")
	# a key Google does not know is a 400 with this reason, not a 401
	if code in (401, 403) or "API_KEY_INVALID" in reasons:
		return PermanentError("Google refused the API key: check it in the Google AI settings.")
	if code == 404:
		return PermanentError(f"Google does not offer the model{named} to this key: choose another in the task.")
	if code == 429:
		return RuntimeError("Google is busy, or the key's quota is used up (429): it is tried again later.")
	if code == 400:
		return RuntimeError(f"Google refused the request ({status})." if status else "Google refused the request.")
	return RuntimeError(f"Google answered {code}.")

async def _send(client: httpx.AsyncClient, method: str, url: str, api_key: str|None, model: str = "", **kw) -> dict:
	"""One call; the key in the header only. Failures say what happened, never what was asked or Google's text."""
	headers = { "x-goog-api-key": api_key } if api_key else {}
	try:
		response = await client.request(method, url, headers=headers, **kw)
	except httpx.TimeoutException:
		raise RuntimeError("Google did not answer in time.") from None
	except httpx.HTTPError as ex:
		raise RuntimeError(f"Could not reach Google ({type(ex).__name__}).") from None
	if response.status_code != 200:
		raise google_problem(response, model)
	if len(response.content) > MAX_BYTES:
		raise RuntimeError("Google's answer is too large.")
	try:
		data = response.json()
	except ValueError:
		raise RuntimeError("Google's answer is not JSON.") from None
	if not isinstance(data, dict):
		raise RuntimeError("Google's answer is not what was expected.")
	return data

async def list_model_ids(api_key: str) -> list[str]:
	"""Every model the key may use for `generateContent`, page after page."""
	ids: list[str] = []
	token = ""
	async with google_client() as client:
		for _ in range(MAX_PAGES):
			params = { "pageSize": "1000", **({ "pageToken": token } if token else {}) }
			page = await _send(client, "GET", f"{API}/models", api_key, params=params)
			ids.extend(model_ids(page))
			token = str(page.get("nextPageToken") or "")
			if not token:
				break
	return list(dict.fromkeys(ids))

def checked_model(model: str) -> str:
	if not MODEL_ID.match(model):
		raise PermanentError("That is not a Google model name: choose one in the task.")
	return model

def _parts(answer: Mapping[str, Any]) -> list[dict]:
	candidates = answer.get("candidates") or []
	first = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
	return [p for p in ((first.get("content") or {}).get("parts") or []) if isinstance(p, dict)]

def _blocked(answer: Mapping[str, Any]) -> str:
	"""Why Google gave nothing back (a word of its own: SAFETY, ...), when it says."""
	feedback = answer.get("promptFeedback") or {}
	candidates = answer.get("candidates") or [{}]
	return _token(feedback.get("blockReason")) or _token((candidates[0] or {}).get("finishReason") if isinstance(candidates[0], dict) else "")

class GoogleApi(DataSource, DataSourceApi):
	"""
	`open_async(dsec, params)` by `params["request"]`:
	- `discovery`: the `Vocabulary` (ratios, sizes) of the discovery document, kept for `discoveryCacheHours`; today's values when it cannot be read;
	- `models`: `{ "ids": [...] }`, the models the key may use (kept for `modelsCacheHours`, shared by the forms and the tasks);
	- `text` (`model`, `instructions`, `input`): the text the model wrote (`str`), from `generateContent`;
	- `image` (`model`, `prompt`, `aspectRatio`, `imageSize`): the picture's bytes, from `generateContent` with image output (never kept).
	Failures are in our words: a PermanentError when trying again cannot help.
	"""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		request = params.get("request")
		rev, settings = dscm.open().get()
		settings = settings or {}
		if request == "discovery":
			return await self._vocabulary(dscm, settings, dsec)
		api_key = stored_api_key(dscm)
		if request == "models":
			async def fetch_ids() -> Mapping[str, Any]:
				return { "ids": await list_model_ids(api_key) }
			# the settings' revision names the key without holding it: another key is another list
			answer = await cached(dscm, settings, f"models|{rev}", dsec.timestamp, fetch_ids, DEFAULT_MODELS_HOURS, "modelsCacheHours")
			return { "ids": [str(i) for i in answer.get("ids") or []] }
		model = checked_model(str(params.get("model") or ""))
		url = f"{API}/models/{model}:generateContent"
		if request == "text":
			body = { "systemInstruction": { "parts": [{ "text": str(params.get("instructions") or "") }] },
				"contents": [{ "role": "user", "parts": [{ "text": str(params.get("input") or "") }] }] }
			async with google_client() as client:
				answer = await _send(client, "POST", url, api_key, model, json=body)
			return "".join(str(p.get("text") or "") for p in _parts(answer) if not p.get("thought")).strip()
		if request == "image":
			body = { "contents": [{ "role": "user", "parts": [{ "text": str(params.get("prompt") or "") }] }],
				"generationConfig": { "responseModalities": ["IMAGE"], "imageConfig": { "aspectRatio": str(params.get("aspectRatio") or "1:1"), "imageSize": str(params.get("imageSize") or "1K") } } }
			async with google_client() as client:
				answer = await _send(client, "POST", url, api_key, model, json=body)
			# a thinking model can show pictures on its way: the last one is the answer
			images = [p["inlineData"] for p in _parts(answer) if isinstance(p.get("inlineData"), dict) and str(p["inlineData"].get("mimeType") or "").startswith("image/")]
			if not images or not images[-1].get("data"):
				why = _blocked(answer)
				raise RuntimeError(f"Google drew no picture ({why})." if why else "Google drew no picture.")
			return base64.b64decode(images[-1]["data"])
		raise PermanentError(f"Unknown Google request: {request!r}")

	async def _vocabulary(self, dscm: DatasourceConfigurationManager, settings: Mapping[str, Any], dsec: DataSourceExecutionContext) -> Vocabulary:
		async def fetch() -> Mapping[str, Any]:
			# public: no key is sent for Google's description of its own API
			async with google_client() as client:
				doc = await _send(client, "GET", DISCOVERY, None, params={ "version": "v1beta" })
			found = read_discovery(doc)
			if found is None:
				raise RuntimeError("Google's discovery document does not say what a picture takes.")
			return { "ratios": list(found.ratios), "sizes": list(found.sizes), "imageOutput": found.image_output }
		try:
			kept = await cached(dscm, settings, "discovery|v1beta", dsec.timestamp, fetch, DEFAULT_DISCOVERY_HOURS, "discoveryCacheHours")
			ratios, sizes = tuple(str(r) for r in kept.get("ratios") or ()), tuple(str(s) for s in kept.get("sizes") or ())
			if ratios and sizes:
				return Vocabulary(ratios, sizes, bool(kept.get("imageOutput")), True)
		except Exception as e:
			logger.warning(f"Google's discovery document could not be used ({type(e).__name__}: {e}); using today's values.")
		return FALLBACK
