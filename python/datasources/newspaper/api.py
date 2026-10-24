from fastapi import APIRouter
from ...web.openapi import Choice, answers
from .constants import NEWSPAPERS

# mounted under /api by the web application
newspaper_router = APIRouter(prefix="/datasource/newspaper")

# the most a search answers: enough to choose from, never the whole list in a search box
MOST_FOUND = 50

@newspaper_router.get('/lookups/newspaperSlug', **answers(list[Choice]))
def plugin_newspaper_slugs(q: str | None = None):
	"""
	The newspapers. With `q` (the lookup's `search`: what was typed in the field's search box), those whose name, city or slug holds it, ignoring case,
	at most MOST_FOUND; without it, every one.
	"""
	papers = NEWSPAPERS
	if q is not None and q.strip():
		wanted = q.strip().casefold()
		papers = [x for x in NEWSPAPERS if any(wanted in str(x.get(key, '')).casefold() for key in ('name', 'city', 'slug'))][:MOST_FOUND]
	return [{ "name": x['name'], "value": x['slug'] } for x in papers]
