"""
Record the real answers the offline tests replay.

    uv run python -m scripts.record_http_fixtures

Needs the internet. For every site the tests fake (python/tests/fake_internet.py) it fetches the real text answer (the comic feeds, the
two Wikipedia API answers) and replaces the fixture in python/tests/fixtures/http/. An answer the code cannot use (a feed with no
entry the parsers understand, an API answer without an image) is reported and the old fixture is kept. Images are never recorded:
real comics, front pages and pictures are copyrighted or carry licence terms, so the fake generates them.
Review the diff before committing it. Nothing here needs, reads or writes a secret.
"""
import json
import os
import sys
from datetime import date

import feedparser
import httpx

from python.datasources.comic.comic_parser import COMICS, parse_the_feed
from python.tests.fake_internet import COMIC_FEEDS, FIXTURES, WIKIPEDIA_IMAGEINFO, WIKIPEDIA_POTD

HEADERS = { "User-Agent": "eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/) fixture recorder" }
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"

def save(name: str, text: str) -> None:
	with open(os.path.join(FIXTURES, name), "w", encoding="utf-8", newline="\n") as f:
		f.write(text if text.endswith("\n") else text + "\n")
	print(f"recorded {name} ({len(text)} bytes)")

def record_comic_feeds(client: httpx.Client) -> int:
	failed = 0
	by_url = { (httpx.URL(comic["feed"]).host, httpx.URL(comic["feed"]).path or "/"): (name, comic) for name, comic in COMICS.items() }
	for key, fixture in COMIC_FEEDS.items():
		known = by_url.get(key)
		if known is None:
			print(f"SKIPPED {fixture}: {key} is not a feed of comic_parser.COMICS any more")
			failed += 1
			continue
		name, comic = known
		try:
			response = client.get(comic["feed"], follow_redirects=True)
			response.raise_for_status()
			items = parse_the_feed(name, comic, feedparser.parse(response.text))
		except Exception as e:
			print(f"FAILED {fixture}: {type(e).__name__}: {e}")
			failed += 1
			continue
		if not items:
			print(f"FAILED {fixture}: the answer has no entry the parser understands; keeping the old fixture")
			failed += 1
			continue
		save(fixture, response.text)
	return failed

def record_wikipedia(client: httpx.Client) -> int:
	try:
		first = client.get(WIKIPEDIA, params={ "action": "query", "format": "json", "formatversion": "2", "prop": "images", "titles": f"Template:POTD/{date.today().isoformat()}" })
		first.raise_for_status()
		filename = first.json()["query"]["pages"][0]["images"][0]["title"]
		second = client.get(WIKIPEDIA, params={ "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1280, "titles": filename })
		second.raise_for_status()
		info = next(iter(second.json()["query"]["pages"].values()))["imageinfo"][0]
		if not (info.get("thumburl") or info.get("url")):
			raise KeyError("imageinfo has no url")
	except Exception as e:
		print(f"FAILED Wikipedia: {type(e).__name__}: {e}; keeping the old fixtures")
		return 1
	save(WIKIPEDIA_POTD, json.dumps(first.json(), indent=1))
	save(WIKIPEDIA_IMAGEINFO, json.dumps(second.json(), indent=1))
	return 0

def main() -> int:
	with httpx.Client(headers=HEADERS, timeout=20) as client:
		failed = record_comic_feeds(client) + record_wikipedia(client)
	print("done" if not failed else f"{failed} fixture(s) were not recorded")
	return 1 if failed else 0

if __name__ == "__main__":
	sys.exit(main())
