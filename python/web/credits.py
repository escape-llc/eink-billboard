"""
Every credit the device owes, for the Credits section of the web app's Help drawer (`GET /api/credits`).

- **Data**: whoever downloads says whose data it is, in its descriptor (`credit`: `text`, optional `license` and `url`). A provider or data source with the
  `internet` feature declares one, unless it only reads addresses the user gives it (`USERS_OWN`); `test_credits` holds every descriptor to that.
- **Fonts**: every family we ship (`FONT_FAMILIES`) is under the SIL Open Font License, by its authors here (and in `NOTICE`).
- **Software**: the other parts by others that the device or its web app carries.

Two credits are also on the panel, because the services' terms ask for them next to their data: the weather provider's footer on the Weather pages
(`Report.credit`) and Thunderforest's strip on a map. Each is its descriptor's `text`; `test_credits` checks they agree.
"""
from typing import Any, NotRequired, TypedDict

from ..model.configuration_manager import FONT_FAMILIES, CollectInfoDict

class Credit(TypedDict):
	name: str
	by: str
	license: str
	url: NotRequired[str]
	what: NotRequired[str]

# the sources that download only what the user points them at: their own calendars, pictures and feeds, which the user knows the origin of
USERS_OWN: dict[str, str] = {
	"calendar-sources": "the user's own calendars and accounts (the holiday data is a library, under Software)",
	"image-url": "a picture at an address the user gives",
	"rss": "the feeds the user lists",
}

OFL = "SIL Open Font License 1.1"
FONT_AUTHORS: dict[str, str] = {
	"Jost": "The Jost Project Authors",
	"Atkinson Hyperlegible": "Braille Institute of America",
	"Lexend": "The Lexend Project Authors",
	"League Spartan": "The League Spartan Project Authors",
	"Literata": "The Literata Project Authors",
	"Bitter": "The Bitter Project Authors",
	"Dogica": "Roberto Mocci",
	"DSEG7": "keshikan",
}

SOFTWARE: list[Credit] = [
	{ "name": "Material Symbols", "by": "Google", "license": "Apache License 2.0", "url": "https://github.com/google/material-design-icons", "what": "Icons in the web app" },
	{ "name": "Waveshare e-Paper drivers", "by": "Waveshare", "license": "MIT", "url": "https://github.com/waveshareteam/e-Paper", "what": "The Waveshare panels' drivers, carried in the device" },
	{ "name": "OpenStreetMap", "by": "OpenStreetMap contributors", "license": "ODbL", "url": "https://www.openstreetmap.org/copyright", "what": "The map and the place search of the location picker" },
	{ "name": "Leaflet", "by": "Volodymyr Agafonkin and contributors", "license": "BSD 2-Clause", "url": "https://leafletjs.com/", "what": "The location picker's map" },
	{ "name": "holidays", "by": "The holidays authors", "license": "MIT", "url": "https://github.com/vacanza/holidays", "what": "The calendars' holidays" },
	{ "name": "Vue and PrimeVue", "by": "Evan You; PrimeTek", "license": "MIT", "url": "https://vuejs.org/", "what": "The web app" },
	{ "name": "Pinia and Pinia Colada", "by": "Eduardo San Martin Morote", "license": "MIT", "url": "https://pinia-colada.esm.dev/", "what": "Keeps the web app's data current" },
	{ "name": "Astral", "by": "Simon Kennedy", "license": "Apache License 2.0", "url": "https://github.com/sffjunkie/astral", "what": "The sun's and the moon's times and positions, calculated on the device" },
	{ "name": "FastAPI", "by": "Sebastián Ramírez", "license": "MIT", "url": "https://fastapi.tiangolo.com/", "what": "The web API" },
	{ "name": "Pillow", "by": "Jeffrey A. Clark and contributors", "license": "MIT-CMU", "url": "https://python-pillow.github.io/", "what": "Pictures on the device" },
	{ "name": "Chromium", "by": "The Chromium Authors", "license": "BSD 3-Clause", "url": "https://www.chromium.org/", "what": "Draws the pages for the panel" },
]

def data_credits(items: list[CollectInfoDict]) -> list[dict[str, Any]]:
	"""The descriptors' credits, by name: what a provider or data source downloads and whose it is."""
	found = []
	for item in items:
		info = item["info"]
		credit = info.get("credit")
		if not isinstance(credit, dict) or not credit.get("text"):
			continue
		entry = { "id": info["id"], "name": info.get("name") or info["id"], "text": credit["text"], "provider": "api" in (info.get("features") or []) }
		for key in ("license", "url"):
			if credit.get(key):
				entry[key] = credit[key]
		found.append(entry)
	return sorted(found, key=lambda e: e["name"].casefold())

def font_credits() -> list[Credit]:
	return [{ "name": family, "by": FONT_AUTHORS[family], "license": OFL } for family in FONT_FAMILIES]
