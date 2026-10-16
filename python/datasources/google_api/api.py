"""
The Google AI data source's routes (mounted under /api): what the saved AI Studio key may use, from the provider's kept model list (`GoogleApi`,
request `models`), and what each image model takes, from Google's discovery document (request `discovery`). The key is read here on the server; the
browser never sees it. A lookup that cannot be answered is an error in our words; the Test answers 200 `{ ok, message }`.
"""
import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Body

from ...model.configuration_manager import DatasourceConfigurationManager
from ...model.service_container import ServiceContainer
from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.documents import SECRET_MASK
from ...web.errors import ApiError
from ..data_source import DataSourceExecutionContext
from .google_api import GoogleApi, checked_key, list_model_ids, stored_api_key
from .models import QUALITY_NAMES, describe_models, image_models, text_models

logger = logging.getLogger(__name__)

DATASOURCE_ID = "google-ai"

# mounted under /api by the web application
google_router = APIRouter(prefix=f"/datasource/{DATASOURCE_ID}")

def _ask(cm, params: dict) -> Any:
	"""The provider's answer, as a task would get it (its folder, its kept answers), or the reason it could not be had in our words."""
	dscm = cm.datasource_manager(DATASOURCE_ID)
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, dscm)
	dsec = DataSourceExecutionContext(root, (0, 0), datetime.now(timezone.utc))
	try:
		return asyncio.run(GoogleApi(DATASOURCE_ID, "Google AI").open_async(dsec, params))
	except (PermanentError, RuntimeError) as problem:
		# the provider's failures are in our words already
		raise ApiError(502, str(problem), "google-models") from None
	except Exception as problem:
		logger.warning(f"Asking Google failed ({type(problem).__name__}).")
		raise ApiError(502, "Google's answer could not be read.", "google-models") from None

def _stored_ids(cm) -> list[str]:
	try:
		stored_api_key(cm.datasource_manager(DATASOURCE_ID))
	except PermanentError as problem:
		raise ApiError(409, f"{problem} Save the settings first.", "google-models") from None
	return list(_ask(cm, { "request": "models" })["ids"])

def _choices(ids: list[str]) -> list[dict]:
	return [{ "name": model, "value": model } for model in ids]

@google_router.get('/lookups/image-models')
def image_model_choices(cm: CM):
	"""The Gemini image models the saved key may use."""
	return _choices(image_models(_stored_ids(cm)))

@google_router.get('/lookups/text-models')
def text_model_choices(cm: CM):
	"""The Gemini text models the saved key may use, for the Google Text part."""
	return _choices(text_models(_stored_ids(cm)))

@google_router.get('/lookups/qualities')
def quality_choices():
	"""The qualities a Google image part offers: each asks for an image size (a model that does not take it uses the nearest one below)."""
	return [{ "name": name, "value": value } for value, name in QUALITY_NAMES.items()]

@google_router.get('/models')
def models(cm: CM):
	"""The models the saved key may use: each image model with the ratios and sizes it takes (Google's discovery document), and the text models."""
	ids = _stored_ids(cm)
	vocabulary = _ask(cm, { "request": "discovery" })
	return { "image": describe_models(ids, vocabulary), "text": text_models(ids) }

@google_router.post('/test')
def test_key(cm: CM, body: dict[str, Any] = Body(...)):
	"""Ask Google with the key typed (or the saved one, when the field shows the mask): `{ ok, message }`, always 200, in our words. Never kept."""
	value = body.get("value")
	if value in (None, "", SECRET_MASK):
		try:
			value = stored_api_key(cm.datasource_manager(DATASOURCE_ID))
		except PermanentError:
			return { "ok": False, "message": "Enter an API key first." }
	if not isinstance(value, str) or not value.strip():
		return { "ok": False, "message": "Enter an API key first." }
	try:
		key = checked_key(value)
	except PermanentError:
		return { "ok": False, "message": "That is not a Google AI Studio key: create one in AI Studio (it starts with AQ.)." }
	# the words below are fixed by the kind of failure: nothing is taken from the error
	try:
		ids = asyncio.run(list_model_ids(key))
	except PermanentError as refused:
		if "key type" in str(refused):
			return { "ok": False, "message": "Google did not accept this key type here: create a new key in Google AI Studio." }
		return { "ok": False, "message": "Google refused the API key, or does not let it list models: check it in the Google AI settings." }
	except Exception as e:
		logger.warning(f"Testing a Google key failed ({type(e).__name__}).")
		return { "ok": False, "message": "Google is busy or could not be reached: try again later." }
	found = image_models(ids)
	if not found:
		return { "ok": False, "message": "The key works, but it may use no Gemini image model." }
	shown = ", ".join(found[:3]) + (", ..." if len(found) > 3 else "")
	return { "ok": True, "message": f"The key works: {len(found)} image {'model' if len(found) == 1 else 'models'} ({shown})." }
