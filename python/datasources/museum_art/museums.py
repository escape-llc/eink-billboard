"""
The museums of Museum Art (#618): how each is searched and what a work is. Each answers without a key; every address here is a constant of ours (and the
pictures' addresses, which come in the answers, go through the URL guard when they are downloaded).

**Only public domain.** A search asks each museum for public-domain works with a picture, and every record is checked again on the museum's own field
(`is_public_domain`, `isPublicDomain`, `share_license_status: CC0`) before it is a work: anything else is skipped.

What each museum allows (checked 2026-10-24):
- the Art Institute of Chicago filters only in a JSON body (in the query string `q` only ranks), pages no deeper than 1,000 results, and allows 60 requests
  a minute to anyone; it asks for an `AIC-User-Agent` naming the project. Its pictures are IIIF, 843 pixels wide as it recommends.
- The Met's `v1/search` was retired on 2026-10-01 (it answers 410); `v1.1/search` pages (at most 500 a page, no deeper than 10,000) and answers only object
  ids, so each work is a second call (kept for `recordCacheHours`). 80 requests a second.
- The Cleveland Museum of Art answers whole records in one call, with the picture's address.
"""
from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Mapping

import httpx

from ...plugins.plugin_base import PermanentError

# what is asked for a page of a search, and how deep a random page may be
PAGE = 25
# the Art Institute's picture server refuses a User-Agent with an address in it (403); its API asks for the project's name in `AIC-User-Agent`
USER_AGENT = "Mozilla/5.0 (compatible; eink-billboard)"
HEADERS = { "User-Agent": USER_AGENT, "Accept": "application/json" }
PICTURE_HEADERS = { "User-Agent": USER_AGENT }
AIC_USER_AGENT = "eink-billboard (github.com/escape-llc/eink-billboard)"

@dataclass(frozen=True, slots=True)
class Work:
	"""One work to show: what the caption says and the picture's address."""
	museum: str
	id: str
	title: str
	artist: str
	date: str
	image: str

	def as_dict(self) -> dict[str, str]:
		return asdict(self)

# a search's answer: the total that matched and this page's records (or, for The Met, its object ids)
Answer = Mapping[str, Any]
Ask = Callable[[str, Callable[[], Awaitable[Answer]]], Awaitable[Answer]]

class Refused(RuntimeError):
	"""The museum did not answer as it should: our words and the status code at most, never its text or the address."""

def _text(value: Any, limit: int = 200) -> str:
	return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""

def _dict(value: Any) -> dict:
	return value if isinstance(value, dict) else {}

def _list(value: Any) -> list:
	return value if isinstance(value, list) else []

def _https(value: Any) -> str|None:
	return value if isinstance(value, str) and value.startswith("https://") and " " not in value else None

def _check(response: httpx.Response, museum: str) -> Any:
	if response.status_code != 200:
		raise Refused(f"{museum} answered {response.status_code}")
	try:
		return response.json()
	except ValueError:
		raise Refused(f"{museum} did not answer with data") from None

class Museum:
	"""A museum's search: `page(client, ask, query, department, offset)` answers `{ "total", "items" }` for one page, and `works` turns a page into works."""
	key = ""
	name = ""
	# how deep a page may start: the museum refuses past it
	deepest = 10_000

	async def page(self, client: httpx.AsyncClient, ask: Ask, query: str, department: str|None, offset: int) -> Answer:
		raise NotImplementedError

	async def works(self, client: httpx.AsyncClient, ask: Ask, answer: Answer) -> list[Work]:
		raise NotImplementedError

	async def search(self, client: httpx.AsyncClient, ask: Ask, query: str, department: str|None) -> list[Work]:
		"""A random page of what matches, as works: the first page says how many there are, then a page at random within what the museum will page to."""
		first = await self.page(client, ask, query, department, 0)
		total = int(first.get("total") or 0)
		pages = max(1, min(total, self.deepest) // PAGE)
		offset = random.randrange(pages) * PAGE
		answer = first if offset == 0 else await self.page(client, ask, query, department, offset)
		return await self.works(client, ask, answer)

AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"
AIC_IIIF = "https://www.artic.edu/iiif/2/{}/full/843,/0/default.jpg"
AIC_FIELDS = ["id", "title", "artist_display", "artist_title", "date_display", "image_id", "is_public_domain"]
IMAGE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

class ArtInstitute(Museum):
	key = "aic"
	name = "Art Institute of Chicago"
	deepest = 1_000

	@staticmethod
	def body(query: str, offset: int) -> dict[str, Any]:
		"""The search's body: public domain with a picture, and every word of the query in the title, the artist or the subjects."""
		must: list[Any] = [{ "multi_match": { "query": query, "fields": ["title", "artist_title", "term_titles"], "operator": "and" } }] if query else []
		return { "query": { "bool": { "filter": [{ "term": { "is_public_domain": True } }, { "exists": { "field": "image_id" } }], "must": must } },
			"fields": AIC_FIELDS, "limit": PAGE, "from": offset }

	async def page(self, client, ask, query, department, offset):
		async def fetch() -> Answer:
			data = _check(await client.post(AIC_SEARCH, json=self.body(query, offset), headers={ **HEADERS, "AIC-User-Agent": AIC_USER_AGENT }), self.name)
			if not isinstance(data, dict):
				raise Refused(f"{self.name} did not answer with data")
			pagination = _dict(data.get("pagination"))
			items = _list(data.get("data"))
			return { "total": int(pagination.get("total") or 0), "items": items }
		return await ask(f"aic|{query}|{offset}", fetch)

	async def works(self, client, ask, answer):
		found = []
		for item in answer.get("items") or []:
			if not isinstance(item, dict) or item.get("is_public_domain") is not True:
				continue
			image_id = item.get("image_id")
			if not isinstance(image_id, str) or not IMAGE_ID.match(image_id):
				continue
			found.append(Work(self.key, _text(item.get("id")), _text(item.get("title")), _text(item.get("artist_title") or item.get("artist_display")),
				_text(item.get("date_display")), AIC_IIIF.format(image_id)))
		return found

MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{}"
# The Met answers ids only: at most this many records are asked for to make a list
MET_RECORDS = 12

class TheMet(Museum):
	key = "met"
	name = "The Met"
	deepest = 10_000

	async def page(self, client, ask, query, department, offset):
		params: dict[str, str|int] = { "hasImages": "true", "isPublicDomain": "true", "offset": offset, "limit": PAGE }
		if query:
			params["q"] = query
		if department:
			params["departmentId"] = department
		async def fetch() -> Answer:
			data = _check(await client.get(MET_SEARCH, params=params, headers=HEADERS), self.name)
			if not isinstance(data, dict):
				raise Refused(f"{self.name} did not answer with data")
			ids = _list(data.get("objectIDs"))
			return { "total": int(data.get("total") or 0), "items": [i for i in ids if isinstance(i, int) and not isinstance(i, bool)] }
		return await ask(f"met|{query}|{department or ''}|{offset}", fetch)

	async def works(self, client, ask, answer):
		ids = list(answer.get("items") or [])
		random.shuffle(ids)
		found = []
		for object_id in ids[:MET_RECORDS]:
			async def fetch(object_id: int = object_id) -> Answer:
				response = await client.get(MET_OBJECT.format(object_id), headers=HEADERS)
				# an object that is gone is not a failure of the search: it is skipped
				if response.status_code == 404:
					return {}
				data = _check(response, self.name)
				return data if isinstance(data, dict) else {}
			record = await ask(f"met-object|{object_id}", fetch)
			image = _https(record.get("primaryImageSmall"))
			if record.get("isPublicDomain") is not True or image is None:
				continue
			found.append(Work(self.key, _text(record.get("objectID")), _text(record.get("title")), _text(record.get("artistDisplayName")), _text(record.get("objectDate")), image))
		return found

CMA_SEARCH = "https://openaccess-api.clevelandart.org/api/artworks/"
CMA_FIELDS = "id,title,creators,creation_date,images,share_license_status"

class Cleveland(Museum):
	key = "cleveland"
	name = "Cleveland Museum of Art"
	deepest = 10_000

	async def page(self, client, ask, query, department, offset):
		params: dict[str, str|int] = { "cc0": 1, "has_image": 1, "limit": PAGE, "skip": offset, "fields": CMA_FIELDS }
		if query:
			params["q"] = query
		async def fetch() -> Answer:
			data = _check(await client.get(CMA_SEARCH, params=params, headers=HEADERS), self.name)
			if not isinstance(data, dict):
				raise Refused(f"{self.name} did not answer with data")
			info = _dict(data.get("info"))
			items = _list(data.get("data"))
			return { "total": int(info.get("total") or 0), "items": items }
		return await ask(f"cleveland|{query}|{offset}", fetch)

	async def works(self, client, ask, answer):
		found = []
		for item in answer.get("items") or []:
			if not isinstance(item, dict) or item.get("share_license_status") != "CC0":
				continue
			images = _dict(item.get("images"))
			web = _dict(images.get("web"))
			image = _https(web.get("url"))
			if image is None:
				continue
			creators = _list(item.get("creators"))
			artist = next((_text(c.get("description")) for c in creators if isinstance(c, dict) and c.get("description")), "")
			found.append(Work(self.key, _text(item.get("id")), _text(item.get("title")), artist, _text(item.get("creation_date")), image))
		return found

MUSEUMS: dict[str, Museum] = { m.key: m for m in (ArtInstitute(), TheMet(), Cleveland()) }

def museum_of(params: Mapping[str, Any]) -> Museum:
	"""The task's museum; unset reads as the Art Institute, an unknown one is a settings problem."""
	key = params.get("museum") or "aic"
	if key not in MUSEUMS:
		raise PermanentError(f"Unknown museum '{key}' (one of {', '.join(MUSEUMS)})")
	return MUSEUMS[str(key)]
