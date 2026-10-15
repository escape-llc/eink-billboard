"""
The OpenAI Image data source's routes (mounted under /api): what the account's key may use, read from OpenAI's model list.

The list (`GET /v1/models`) gives only ids: `models.py` says what each takes. The key is the **saved** one, read here on the server; the browser
never sees it. A lookup that cannot be answered is an error in our words (the form shows it under the field); the Test answers 200 `{ ok, message }`.
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body

from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.errors import ApiError
from .models import QUALITIES, describe_models, image_models, text_models
from .openai_image import openai_client, openai_problem, stored_api_key

logger = logging.getLogger(__name__)

DATASOURCE_ID = "openai-image"

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

async def _list_ids(api_key: str) -> list[str]:
	async with openai_client(api_key) as client:
		return [model.id async for model in client.models.list()]

def _ids(api_key: str) -> list[str]:
	"""The ids of the models the key may use, or the reason it could not be asked (ours, never OpenAI's text)."""
	try:
		return asyncio.run(_list_ids(api_key))
	except Exception as e:
		problem = openai_problem(e)
		logger.warning(f"Listing the OpenAI models failed ({type(e).__name__}): {problem}")
		raise ApiError(502, str(problem), "openai-models") from None

def _stored_ids(cm) -> list[str]:
	try:
		api_key = stored_api_key(cm.datasource_manager(DATASOURCE_ID))
	except PermanentError:
		raise ApiError(409, "Enter the OpenAI API key in the OpenAI Image settings and save them first.", "openai-models") from None
	return _ids(api_key)

def _choices(ids: list[str]) -> list[dict]:
	return [{ "name": model, "value": model } for model in ids]

@openai_router.get('/lookups/image-models')
def image_model_choices(cm: CM):
	"""The image models the saved key may use and this data source can drive (no retired DALL·E)."""
	return _choices(image_models(_stored_ids(cm)))

@openai_router.get('/lookups/text-models')
def text_model_choices(cm: CM):
	"""The text models the saved key may use, for rewriting the prompt."""
	return _choices(text_models(_stored_ids(cm)))

@openai_router.get('/lookups/qualities')
def quality_choices():
	"""Every quality an image model takes; a model asked for one it does not take uses the nearest one below it."""
	return [{ "name": QUALITY_NAMES[q], "value": q } for q in QUALITIES]

@openai_router.get('/models')
def models(cm: CM):
	"""The models the saved key may use: each image model with what it takes (qualities, sizes), and the text models."""
	ids = _stored_ids(cm)
	return { "image": describe_models(ids), "text": text_models(ids) }

@openai_router.post('/test')
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask OpenAI with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`, always 200, in our words."""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		try:
			value = stored_api_key(cm.datasource_manager(DATASOURCE_ID))
		except PermanentError:
			return { "ok": False, "message": "Enter an API key first." }
	if not isinstance(value, str):
		return { "ok": False, "message": "Enter an API key first." }
	try:
		ids = _ids(value.strip())
	except ApiError as refused:
		return { "ok": False, "message": refused.message }
	found = image_models(ids)
	if not found:
		return { "ok": False, "message": "The key works, but it may use no GPT image model." }
	shown = ", ".join(found[:3]) + (", ..." if len(found) > 3 else "")
	return { "ok": True, "message": f"The key works: {len(found)} image {'model' if len(found) == 1 else 'models'} ({shown})." }
