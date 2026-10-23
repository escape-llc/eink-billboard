from fastapi import APIRouter
from ...web.openapi import Choice, answers
from .constants import NEWSPAPERS

# mounted under /api by the web application
newspaper_router = APIRouter(prefix="/datasource/newspaper")

@newspaper_router.get('/lookups/newspaperSlug', **answers(list[Choice]))
def plugin_newspaper_slugs():
	return [{ "name": x['name'], "value": x['slug'] } for x in NEWSPAPERS]
