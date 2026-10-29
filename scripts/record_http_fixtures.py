"""
Record the real answers the offline tests replay.

    uv run python -m scripts.record_http_fixtures

Needs the internet. For every site the tests fake (python/tests/fake_internet.py) it fetches the real text answer (the comic feeds, the
two Wikipedia API answers) and replaces the fixture in python/tests/fixtures/http/. An answer the code cannot use (a feed with no
entry the parsers understand, an API answer without an image) is reported and the old fixture is kept. Images are never recorded:
real comics, front pages and pictures are copyrighted or carry licence terms, so the fake generates them.
Review the diff before committing it. Nothing here needs, reads or writes a secret, except:

    $env:TRANSITLAND_API_KEY = "<your key>"      # PowerShell; `export TRANSITLAND_API_KEY=...` in bash
    uv run python -m scripts.record_http_fixtures --transitland

which records Transitland's real answers (#429), and only those, into python/tests/fixtures/http/recorded/ (at most 13 calls of the plan). **That folder is
git-ignored and stays on your machine**: the answers were fetched with your key under your plan's terms, so they are yours to test with, not to publish. The key is
read from the environment only, sent in the `apikey` header only, and never written or printed: an answer that holds it is not saved. The answers are
asked at downtown Seattle (the tests' SEATTLE), never the device's location, so a recording says nothing of where you are. They do not replace the hand-written fixtures,
whose made-up stops and alerts the behaviour tests name: `test_transitland_recorded` reads them with the real parsers, to check what they make of a
real answer. What a real answer shows that the parsers cannot (the refusal of a wrong key, the rate-limit headers) is in transitland-notes.json.
"""
import json
import os
import sys
from datetime import date

import feedparser
import httpx

from python.datasources.comic.strips import COMICS, read_feed
from python.tests.fake_internet import COMIC_FEEDS, FIXTURES, WIKIPEDIA_IMAGEINFO, WIKIPEDIA_POTD

HEADERS = { "User-Agent": "eInkBillboard/0.0 (https://github.com/escape-llc/eink-billboard/) fixture recorder" }
TRANSITLAND = "https://transit.land/api/v2/rest"
RECORDED = os.path.join(FIXTURES, "recorded")
# downtown Seattle (python/tests/test_weather.SEATTLE): a public place with live transit, never the device's location
SEATTLE = (47.61, -122.33)
# a recorded answer is cut to this many stops and departures: enough to read, small enough to review
KEEP_STOPS = 8
KEEP_DEPARTURES = 12
# how many of the nearest stops are asked for departures, looking for live times: a call each
LIVE_TRIES = 8
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"

def save(name: str, text: str) -> None:
	with open(os.path.join(FIXTURES, name), "w", encoding="utf-8", newline="\n") as f:
		f.write(text if text.endswith("\n") else text + "\n")
	print(f"recorded {name} ({len(text)} bytes)")

def record_comic_feeds(client: httpx.Client) -> int:
	failed = 0
	by_url = { (httpx.URL(comic.feed).host, httpx.URL(comic.feed).path or "/"): (name, comic) for name, comic in COMICS.items() }
	for key, fixture in COMIC_FEEDS.items():
		known = by_url.get(key)
		if known is None:
			print(f"SKIPPED {fixture}: {key} is not a feed of strips.COMICS any more")
			failed += 1
			continue
		name, comic = known
		try:
			response = client.get(comic.feed, follow_redirects=True)
			response.raise_for_status()
			items = read_feed(name, comic, feedparser.parse(response.text))
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

def _trimmed(data: dict) -> dict:
	"""The answer cut to KEEP_STOPS stops of KEEP_DEPARTURES departures each (and no `meta`, whose `next` link would be a page we did not record)."""
	stops = [dict(s) for s in (data.get("stops") or [])[:KEEP_STOPS] if isinstance(s, dict)]
	for stop in stops:
		if isinstance(stop.get("departures"), list):
			stop["departures"] = stop["departures"][:KEEP_DEPARTURES]
	return { **{ k: v for k, v in data.items() if k not in ("stops", "meta") }, **({ "stops": stops } if "stops" in data else {}) }

def record_transitland(client: httpx.Client, key: str) -> int:
	"""The calls the provider makes, at SEATTLE, each saved under recorded/; and what a wrong key and the headers look like, in the notes."""
	from python.datasources.transitland_api.transitland_api import DEPARTURES_LIMIT, NEARBY_LIMIT, ROUTES_LIMIT, SEARCH_RADIUS, WINDOW_SECONDS, stop_key_of, stop_path
	os.makedirs(RECORDED, exist_ok=True)
	notes: dict = { "asked_at": SEATTLE, "calls": {} }
	def ask(name: str, path: str, params: dict, keyed: str = key) -> httpx.Response:
		response = client.get(f"{TRANSITLAND}{path}", params=params, headers={ "apikey": keyed })
		# what the plan's headers say (a limit, what is left, when it resets), and the status; never a header that could hold the key
		notes["calls"][name] = { "status": response.status_code, "bytes": len(response.content),
			"headers": { h: v for h, v in response.headers.items() if any(w in h.lower() for w in ("ratelimit", "rate-limit", "retry", "quota", "limit")) } }
		return response
	def keep(name: str, response: httpx.Response, trim: bool = True) -> dict|None:
		if response.status_code != 200:
			print(f"FAILED {name}: Transitland answered {response.status_code}")
			return None
		data = response.json()
		text = json.dumps(_trimmed(data) if trim else data, indent=1, ensure_ascii=False)
		if key in text:
			print(f"NOT SAVED {name}: the answer holds the key")
			return None
		with open(os.path.join(RECORDED, name), "w", encoding="utf-8", newline="\n") as f:
			f.write(text + "\n")
		print(f"recorded recorded/{name} ({len(text)} bytes)")
		return data
	lat, lon = f"{SEATTLE[0]:.5f}", f"{SEATTLE[1]:.5f}"
	near = keep("transitland-stops-near.json", ask("stops-near", "/stops", { "lat": lat, "lon": lon, "radius": 800, "limit": NEARBY_LIMIT }))
	if near is None:
		return 1
	stops = [s for s in near.get("stops") or [] if isinstance(s, dict) and s.get("onestop_id")]
	if not stops:
		print("FAILED: no stop with a Onestop ID near the point")
		return 1
	failed = 0
	# the stop to record: the nearest with live times (what the parsers most need to meet), else the nearest with any departure (late at night, perhaps none);
	# a timetable-only stop (a monorail) says nothing about estimates and delays
	def departures_of(response: httpx.Response) -> list[dict]:
		return [d for s in response.json().get("stops") or [] if isinstance(s, dict) for d in s.get("departures") or [] if isinstance(d, dict)]
	live: tuple[dict, httpx.Response]|None = None
	fallback: tuple[dict, httpx.Response]|None = None
	for stop in stops[:LIVE_TRIES]:
		response = ask(f"departures {stop['onestop_id']}", stop_path(stop["onestop_id"]) + "/departures", { "next": WINDOW_SECONDS, "include_alerts": "true", "limit": DEPARTURES_LIMIT })
		if response.status_code != 200:
			continue
		found = departures_of(response)
		if any((d.get("departure") or {}).get("estimated_utc") or (d.get("arrival") or {}).get("estimated_utc") for d in found):
			live = (stop, response)
			break
		if found and fallback is None:
			fallback = (stop, response)
	notes["live"] = live is not None
	picked = live or fallback
	if picked is None:
		print("FAILED departures: none of the nearest stops has a departure in the next 90 minutes; try in the daytime")
		failed += 1
		chosen = stops[0]
	else:
		if live is None:
			print("no stop near the point has live times now: recording the nearest with departures")
		chosen = picked[0]
		keep("transitland-departures.json", picked[1])
	notes["stop"] = { "onestop_id": chosen["onestop_id"], "name": chosen.get("stop_name") }
	name = str(chosen.get("stop_name") or "")
	failed += keep("transitland-stops-search.json", ask("search", "/stops", { "search": name, "limit": NEARBY_LIMIT, "lat": lat, "lon": lon, "radius": SEARCH_RADIUS })) is None
	failed += keep("transitland-stop-key.json", ask("stop_key", "/stops", { "stop_key": stop_key_of(chosen) })) is None
	failed += keep("transitland-routes.json", ask("routes", "/routes", { "serves_stop_onestop_id": chosen["onestop_id"], "include_alerts": "true", "limit": ROUTES_LIMIT }), trim=False) is None
	# a wrong key: what the refusal looks like (its body's keys and the status only: the body may quote the key it was sent)
	wrong = ask("wrong-key", "/operators", { "limit": 1 }, keyed="not-a-key")
	try:
		body = wrong.json()
		notes["calls"]["wrong-key"]["body_keys"] = sorted(body) if isinstance(body, dict) else type(body).__name__
	except ValueError:
		notes["calls"]["wrong-key"]["body_keys"] = "not JSON"
	text = json.dumps(notes, indent=1, ensure_ascii=False)
	if key in text:
		print("NOT SAVED transitland-notes.json: it holds the key")
		return failed + 1
	with open(os.path.join(RECORDED, "transitland-notes.json"), "w", encoding="utf-8", newline="\n") as f:
		f.write(text + "\n")
	print(f"recorded recorded/transitland-notes.json; the stop used: {notes['stop']['name']}")
	return failed

def main() -> int:
	if "--transitland" in sys.argv[1:]:
		key = os.environ.get("TRANSITLAND_API_KEY", "").strip()
		if not key:
			print("Set TRANSITLAND_API_KEY in this shell first (it is read from the environment only).")
			return 2
		with httpx.Client(headers=HEADERS, timeout=20) as client:
			failed = record_transitland(client, key)
		print("done" if not failed else f"{failed} answer(s) were not recorded")
		return 1 if failed else 0
	with httpx.Client(headers=HEADERS, timeout=20) as client:
		failed = record_comic_feeds(client) + record_wikipedia(client)
	print("done" if not failed else f"{failed} fixture(s) were not recorded")
	return 1 if failed else 0

if __name__ == "__main__":
	sys.exit(main())
