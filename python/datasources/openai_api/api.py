"""
The OpenAI data source's routes (mounted under /api): what the saved key may use, from the provider's kept model list (`OpenAIApi`, request `models`),
so the forms and the tasks share one answer.

The list gives only ids: `models.py` says what each takes. The key is the **saved** one, read here on the server; the browser never sees it. A lookup
that cannot be answered is an error in our words (the form shows it under the field); the Test answers 200 `{ ok, message }`.
"""
import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

import httpx
import openai
from fastapi import APIRouter, Body

from ...model.configuration_manager import DatasourceConfigurationManager
from ...model.service_container import ServiceContainer
from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.errors import ApiError
from ...web.openapi import Choice, answers, test_route
from ..data_source import DataSourceExecutionContext
from .models import QUALITIES, describe_models, image_models, text_models
from .openai_api import OpenAIApi, list_model_ids, stored_api_key

logger = logging.getLogger(__name__)

DATASOURCE_ID = "openai-api"

# mounted under /api by the web application
openai_router = APIRouter(prefix=f"/datasource/{DATASOURCE_ID}")

QUALITY_NAMES = {
	"auto": "Auto (the model chooses)",
	"low": "Low",
	"medium": "Medium",
	"high": "High",
	"xhigh": "Extra high (gpt-image-2.5)",
	"max": "Maximum (gpt-image-2.5)",
}

def _stored_ids(cm) -> list[str]:
	"""The ids of the models the saved key may use (kept by the provider), or the reason they could not be had (ours, never OpenAI's text)."""
	dscm = cm.datasource_manager(DATASOURCE_ID)
	try:
		stored_api_key(dscm)
	except PermanentError:
		raise ApiError(409, "Enter the OpenAI API key in the OpenAI settings and save them first.", "openai-models") from None
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, dscm)
	dsec = DataSourceExecutionContext(root, (0, 0), datetime.now(timezone.utc))
	try:
		answer = asyncio.run(OpenAIApi(DATASOURCE_ID, "OpenAI").open_async(dsec, { "request": "models" }))
	except (PermanentError, RuntimeError) as problem:
		# the provider's failures are in our words already (openai_problem)
		raise ApiError(502, str(problem), "openai-models") from None
	except Exception as problem:
		logger.warning(f"Listing the OpenAI models failed ({type(problem).__name__}).")
		raise ApiError(502, "The OpenAI model list could not be read.", "openai-models") from None
	return list(answer["ids"])

def _choices(ids: list[str]) -> list[dict]:
	return [{ "name": model, "value": model } for model in ids]

@openai_router.get('/lookups/image-models', **answers(list[Choice]))
def image_model_choices(cm: CM):
	"""The image models the saved key may use and the OpenAI Image part can drive (no retired DALL·E)."""
	return _choices(image_models(_stored_ids(cm)))

@openai_router.get('/lookups/text-models', **answers(list[Choice]))
def text_model_choices(cm: CM):
	"""The text models the saved key may use, for the OpenAI Text part."""
	return _choices(text_models(_stored_ids(cm)))

@openai_router.get('/lookups/qualities', **answers(list[Choice]))
def quality_choices():
	"""Every quality an image model takes; a model asked for one it does not take uses the nearest one below it."""
	return [{ "name": QUALITY_NAMES[q], "value": q } for q in QUALITIES]

@openai_router.get('/models')
def models(cm: CM):
	"""The models the saved key may use: each image model with what it takes (qualities, sizes), and the text models."""
	ids = _stored_ids(cm)
	return { "image": describe_models(ids), "text": text_models(ids) }

def _test_words(error: Exception) -> str:
	"""What a failed key test means: words fixed by the kind of failure, nothing taken from the error."""
	if isinstance(error, (PermanentError, openai.AuthenticationError)):
		return "OpenAI refused the API key, or does not let it list models: check it in the OpenAI settings."
	if isinstance(error, openai.PermissionDeniedError):
		return "OpenAI does not let this key list its models."
	if isinstance(error, openai.RateLimitError):
		return "OpenAI is busy (429), or the account has no credit left."
	if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException)):
		return "OpenAI did not answer in time."
	if isinstance(error, (openai.APIConnectionError, httpx.HTTPError)):
		return "Could not reach OpenAI."
	if isinstance(error, openai.APIStatusError):
		return "OpenAI did not accept the request."
	return "The key could not be tested."

@openai_router.post('/test', **test_route())
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask OpenAI with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`, always 200, in our words. Never kept."""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		try:
			value = stored_api_key(cm.datasource_manager(DATASOURCE_ID))
		except PermanentError:
			return { "ok": False, "message": "Enter an API key first." }
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an API key first." }
	try:
		ids = asyncio.run(list_model_ids(value.strip()))
	except Exception as e:
		logger.warning(f"Testing an OpenAI key failed ({type(e).__name__}).")
		return { "ok": False, "message": _test_words(e) }
	found = image_models(ids)
	if not found:
		return { "ok": False, "message": "The key works, but it may use no GPT image model." }
	shown = ", ".join(found[:3]) + (", ..." if len(found) > 3 else "")
	return { "ok": True, "message": f"The key works: {len(found)} image {'model' if len(found) == 1 else 'models'} ({shown})." }
