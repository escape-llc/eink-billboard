"""
Write the web API's OpenAPI document to app/src/api/openapi.json (#590), without starting a server.

The app is built as python/eink-billboard.py builds it: the core routers and every enabled plugin's and data source's own router (`load_routers`), over a throwaway
storage seeded with the factory defaults (no device's settings are read). The web app's types (app/src/api/schema.d.ts) are generated from the file
(`npm run api` runs both steps), and `test_openapi_document` fails when the committed file is not what this writes.

	uv run python -m scripts.export_openapi            # write it
	uv run python -m scripts.export_openapi --check    # exit 1 when the committed file differs
"""
import json
import logging
import os
import sys
import tempfile
from typing import Any

from python.model.configuration_manager import ConfigurationManager
from python.web.app import WebSettings, create_app

DOCUMENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "src", "api", "openapi.json")

def openapi_document() -> dict[str, Any]:
	"""The OpenAPI document of the app as the server builds it."""
	with tempfile.TemporaryDirectory(prefix="eink-openapi-") as storage:
		cm = ConfigurationManager(storage_path=storage)
		cm.hard_reset()
		routers: dict[str, Any] = {}
		routers.update(cm.load_routers(cm.enum_plugins()))
		routers.update(cm.load_routers(cm.enum_datasources()))
		return create_app(WebSettings(), routers=routers).openapi()

def as_text(document: dict[str, Any]) -> str:
	"""The file's text: sorted keys and tabs, so a change reads as a small diff and the same document is always the same bytes."""
	return json.dumps(document, indent="\t", sort_keys=True, ensure_ascii=False) + "\n"

def main(argv: list[str]) -> int:
	logging.basicConfig(level=logging.WARNING)
	text = as_text(openapi_document())
	if "--check" in argv:
		try:
			with open(DOCUMENT, encoding="utf-8") as f:
				same = f.read() == text
		except FileNotFoundError:
			same = False
		if not same:
			print(f"{DOCUMENT} is not the app's OpenAPI document: run `cd app && npm run api` and commit the result.", file=sys.stderr)
		return 0 if same else 1
	os.makedirs(os.path.dirname(DOCUMENT), exist_ok=True)
	with open(DOCUMENT, "w", encoding="utf-8", newline="\n") as f:
		f.write(text)
	print(f"wrote {DOCUMENT}")
	return 0

if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
