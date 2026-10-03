from fastapi import APIRouter
from .constants import NEWSPAPERS

# mounted under /api by the web application
newspaper_router = APIRouter(prefix="/datasource/newspaper")

@newspaper_router.get('/lookups/newspaperSlug')
def plugin_newspaper_slugs():
	return [{ "name": x['name'], "value": x['slug'] } for x in NEWSPAPERS]
