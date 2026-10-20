"""
The internet the tests talk to: no test needs the real one.

`python/tests/__init__.py` makes `AsyncHttpWorkerPool` use this transport, so every download of the code under test is answered here:
- text answers (the XKCD Atom feed, the two Wikipedia API answers) come from `python/tests/fixtures/http/`, written by hand in the
  shapes the sites send and replaceable by real ones (`scripts/record_http_fixtures.py`, run once with internet access);
- images are generated: real comics, front pages and pictures are copyrighted or carry licence terms, and the code only needs a valid
  image of the right content type and a plausible size;
- any other URL is a loud `httpx.ConnectError`, so a test can never reach the network by accident.
Set `EINK_TEST_LIVE=1` to leave the real network in place (the opt-in live check).
"""
import base64
import io
import json
import os
from typing import Callable
from urllib.parse import parse_qs

import httpx
from PIL import Image, ImageDraw

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "http")
XKCD_FEED = "xkcd-atom.xml"
# every feed of python/datasources/comic/comic_parser.py (the test storage's playlist plays them all): URL (host, path) -> fixture file
COMIC_FEEDS = {
	("xkcd.com", "/atom.xml"): XKCD_FEED,
	("explosm-1311.appspot.com", "/"): "comic-cyanide.xml",
	("www.smbc-comics.com", "/comic/rss"): "comic-smbc.xml",
	("pbfcomics.com", "/feed/"): "comic-pbf.xml",
	("www.questionablecontent.net", "/QCRSS.xml"): "comic-qc.xml",
	("poorlydrawnlines.com", "/feed/"): "comic-pdl.xml",
	("www.qwantz.com", "/rssfeed.php"): "comic-qwantz.xml",
	("webcomicname.com", "/rss"): "comic-webcomicname.xml",
}
# where the comics' images come from; any image there is a generated one
COMIC_IMAGE_HOSTS = ("imgs.xkcd.com", "files.explosm.net", "static.explosm.net", "www.smbc-comics.com", "pbfcomics.com", "www.questionablecontent.net",
	"poorlydrawnlines.com", "www.qwantz.com", "64.media.tumblr.com")
WIKIPEDIA_POTD = "wikipedia-potd-images.json"
WIKIPEDIA_IMAGEINFO = "wikipedia-imageinfo.json"

def fixture_text(name: str) -> str:
	with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
		return f.read()

def synthetic_image(width: int, height: int, label: str, fmt: str) -> bytes:
	"""A valid image that is not a copy of anything: a gradient with the label drawn on it."""
	image = Image.new("RGB", (width, height))
	pixels = image.load()
	assert pixels is not None
	for y in range(height):
		for x in range(0, width):
			pixels[x, y] = (x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), 128)
	ImageDraw.Draw(image).text((8, 8), label, fill=(255, 255, 255))
	buffer = io.BytesIO()
	image.save(buffer, fmt)
	return buffer.getvalue()

def _image(width: int, height: int, label: str, fmt: str = "PNG") -> httpx.Response:
	return httpx.Response(200, content=synthetic_image(width, height, label, fmt), headers={ "Content-Type": f"image/{fmt.lower()}" })

class FakeInternet(httpx.MockTransport):
	"""Answers the requests the tests make from fixtures; remembers what was asked (`requests`) so a test can check it."""
	def __init__(self):
		self.requests: list[httpx.Request] = []
		super().__init__(self._handle)

	def _handle(self, request: httpx.Request) -> httpx.Response:
		self.requests.append(request)
		for route in ROUTES:
			response = route(request)
			if response is not None:
				return response
		raise httpx.ConnectError(f"offline test: no canned response for {request.method} {request.url}", request=request)

def _comic_feed(request: httpx.Request) -> httpx.Response | None:
	name = COMIC_FEEDS.get((request.url.host, request.url.path or "/"))
	if name is None:
		return None
	return httpx.Response(200, text=fixture_text(name), headers={ "Content-Type": "application/xml" })

def _comic_image(request: httpx.Request) -> httpx.Response | None:
	path = request.url.path.lower()
	if request.url.host in COMIC_IMAGE_HOSTS and path.endswith((".png", ".jpg", ".jpeg", ".gif")):
		return _image(640, 480, path.rsplit("/", 1)[-1])
	return None

def _freedom_forum(request: httpx.Request) -> httpx.Response | None:
	# https://cdn.freedomforum.org/dfp/jpg{day}/lg/{SLUG}.jpg
	if request.url.host == "cdn.freedomforum.org" and request.url.path.startswith("/dfp/jpg") and request.url.path.endswith(".jpg"):
		return _image(700, 1166, request.url.path.rsplit("/", 1)[-1], "JPEG")
	return None

def _wikipedia_api(request: httpx.Request) -> httpx.Response | None:
	if request.url.host == "en.wikipedia.org" and request.url.path == "/w/api.php":
		query = parse_qs(request.url.query.decode())
		title = (query.get("titles") or [""])[0]
		if title.startswith("Template:POTD/"):
			return httpx.Response(200, text=fixture_text(WIKIPEDIA_POTD), headers={ "Content-Type": "application/json" })
		if (query.get("prop") or [""])[0] == "imageinfo":
			return httpx.Response(200, text=fixture_text(WIKIPEDIA_IMAGEINFO), headers={ "Content-Type": "application/json" })
	return None

def _wikimedia_image(request: httpx.Request) -> httpx.Response | None:
	# the picture itself (upload.) and its resized thumbnails (thumb.), which is what the datasource asks for
	if request.url.host in ("upload.wikimedia.org", "thumb.wikimedia.org") and request.url.path.startswith("/wikipedia/"):
		return _image(1280, 853, request.url.path.rsplit("/", 1)[-1], "JPEG")
	return None

# NASA's Astronomy Picture of the Day: the latest pictures (a fixture, newest first), and one day by its yymmdd id. An id ending in 99 has no picture (404), one ending in 88 is a video
APOD_LIST = "apod-list.json"
APOD_PATH = "/wp-json/wp/v2/apod-basic"

def _apod(request: httpx.Request) -> httpx.Response | None:
	if request.url.host == "science.nasa.gov" and request.url.path == APOD_PATH:
		return httpx.Response(200, text=fixture_text(APOD_LIST), headers={ "Content-Type": "application/json" })
	if request.url.host == "science.nasa.gov" and request.url.path.startswith(APOD_PATH + "/"):
		ident = request.url.path.rsplit("/", 1)[-1]
		if not (len(ident) == 6 and ident.isdigit()) or ident.endswith("99"):
			return httpx.Response(404, json={ "code": "rest_post_invalid_id", "message": "Invalid post ID." })
		day = f"20{ident[:2]}-{ident[2:4]}-{ident[4:]}"
		kind = "video" if ident.endswith("88") else "image"
		doc = { "date": day, "title": f"Picture of {day}", "media_type": kind, "explanation": "<strong>Explanation:</strong> text", "credit": "Someone",
			"url": f"https://science.nasa.gov/image-article/apod-{ident}" }
		if kind == "image":
			doc["hdurl"] = f"https://assets.science.nasa.gov/content/dam/science/cds/apod/apod/20{ident[:2]}/picture_{ident}.jpg"
		return httpx.Response(200, json=doc)
	return None

def _apod_image(request: httpx.Request) -> httpx.Response | None:
	if request.url.host == "assets.science.nasa.gov" and request.url.path.lower().endswith(".jpg"):
		return _image(1600, 1000, request.url.path.rsplit("/", 1)[-1], "JPEG")
	return None

# invented feeds for the RSS Feed data source: URL (host, path) -> fixture file; "/page" answers 200 with HTML (a cookie wall), which is no feed
RSS_FEEDS = {
	("news.example.test", "/feed.xml"): "rss-news.xml",
	("notes.example.test", "/atom.xml"): "rss-atom.xml",
}

def _rss_feed(request: httpx.Request) -> httpx.Response | None:
	if request.url.host == "news.example.test" and request.url.path == "/page":
		return httpx.Response(200, text="<html><body>Please accept cookies</body></html>", headers={ "Content-Type": "text/html" })
	name = RSS_FEEDS.get((request.url.host, request.url.path))
	if name is None:
		return None
	return httpx.Response(200, text=fixture_text(name), headers={ "Content-Type": "application/xml" })

def _rss_image(request: httpx.Request) -> httpx.Response | None:
	path = request.url.path.lower()
	if request.url.host == "img.example.test" and path.endswith((".png", ".jpg", ".gif")):
		return _image(640, 360, path.rsplit("/", 1)[-1], "JPEG" if path.endswith(".jpg") else "PNG")
	return None

# invented pictures at an address, for the Image from a Web Address data source (a camera, a chart): "/snapshot.jpg" and "/portrait.png" are pictures, "/octet" a picture a camera sent as
# application/octet-stream, "/anonymous" one with no content type at all, "/page" an HTML page, "/animated.gif" two frames, "/huge.png" a small file that holds a huge picture
def _picture_at_an_address(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "camera.example.test":
		return None
	path = request.url.path
	if path == "/snapshot.jpg":
		return _image(1280, 720, "snapshot", "JPEG")
	if path == "/portrait.png":
		return _image(300, 600, "portrait", "PNG")
	if path == "/octet":
		return httpx.Response(200, content=synthetic_image(400, 300, "octet", "PNG"), headers={ "Content-Type": "application/octet-stream" })
	if path == "/anonymous":
		return httpx.Response(200, content=synthetic_image(400, 300, "anonymous", "PNG"), headers={ "Content-Type": "" })
	if path == "/page":
		return httpx.Response(200, text="<html><body>Please log in</body></html>", headers={ "Content-Type": "text/html" })
	if path == "/animated.gif":
		frames = [Image.new("RGB", (100, 80), "red"), Image.new("RGB", (100, 80), "blue")]
		buffer = io.BytesIO()
		frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:], duration=100)
		return httpx.Response(200, content=buffer.getvalue(), headers={ "Content-Type": "image/gif" })
	if path == "/huge.png":
		buffer = io.BytesIO()
		Image.new("1", (9000, 9000)).save(buffer, "PNG")
		return httpx.Response(200, content=buffer.getvalue(), headers={ "Content-Type": "image/png" })
	if path == "/forbidden":
		return httpx.Response(403, text="no")
	return httpx.Response(404, text="Not found")

# invented calendars for the Calendar data source: URL (host, path) -> fixture file. "/private.ics" needs the Basic sign-in user:pass,
# "/page" is an HTML page (no calendar); dav.example.test answers a CalDAV REPORT and checks that it is one
CALENDARS = {
	("calendar.example.test", "/family.ics"): "calendar-family.ics",
	("calendar.example.test", "/season.ics"): "calendar-season.ics",
	("calendar.example.test", "/ended.ics"): "calendar-ended.ics",
}
CALENDAR_SIGN_IN = "Basic dXNlcjpwYXNz"

def _calendar(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "calendar.example.test":
		return None
	if request.url.path == "/private.ics":
		if request.headers.get("Authorization") != CALENDAR_SIGN_IN:
			return httpx.Response(401, text="Sign in")
		return httpx.Response(200, text=fixture_text("calendar-family.ics"), headers={ "Content-Type": "text/calendar" })
	if request.url.path == "/page":
		return httpx.Response(200, text="<html><body>Sign in to see this calendar</body></html>", headers={ "Content-Type": "text/html" })
	name = CALENDARS.get((request.url.host, request.url.path))
	return None if name is None else httpx.Response(200, text=fixture_text(name), headers={ "Content-Type": "text/calendar" })

def _caldav(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "dav.example.test":
		return None
	body = request.read().decode("utf-8")
	if request.method != "REPORT" or request.headers.get("Depth") != "1" or "calendar-query" not in body or "time-range" not in body:
		return httpx.Response(400, text="Expected a calendar-query REPORT with Depth 1 and a time range")
	return httpx.Response(207, text=fixture_text("calendar-dav.xml"), headers={ "Content-Type": "application/xml" })

# OpenWeatherMap: the key says what is answered ("good-key" the fixtures, "busy-key" a 429, any other key a 401, as the real service does for a key it does not know)
WEATHER_FIXTURES = { "/data/2.5/weather": "weather-current.json", "/data/2.5/forecast": "weather-forecast.json" }

def _weather(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "api.openweathermap.org":
		return None
	name = WEATHER_FIXTURES.get(request.url.path)
	if name is None:
		return httpx.Response(404, json={ "cod": "404", "message": "Internal error" })
	key = request.url.params.get("appid")
	if key == "busy-key":
		return httpx.Response(429, json={ "cod": 429, "message": "Too many requests" })
	if key != "good-key":
		return httpx.Response(401, json={ "cod": 401, "message": "Invalid API key" })
	return httpx.Response(200, text=fixture_text(name), headers={ "Content-Type": "application/json" })

# ipapi.co: the caller's rough position (the Location field's button): always the same place
def _ip_location(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "ipapi.co":
		return None
	if request.url.path != "/json/":
		return httpx.Response(404, json={ "error": True, "reason": "Not Found" })
	return httpx.Response(200, json={ "ip": "203.0.113.7", "city": "Detroit", "region": "Michigan", "country_code": "US", "latitude": 42.33143, "longitude": -83.04575 })

# OpenAI: the key says what is answered ("sk-good" the fixtures, "sk-busy" a 429, "sk-broke" a 429 insufficient_quota, any other a 401 whose message
# quotes the key, as the real one does). The model list is a fixture (its shape: it needs a key, so it is not recorded); a picture is a generated
# PNG of the size asked, divided by 8 (the shape is what the code checks); the size follows the rules of the model's family.
OPENAI_MODELS = "openai-models.json"

def _openai_error(status: int, code: str, message: str) -> httpx.Response:
	return httpx.Response(status, json={ "error": { "message": message, "type": "invalid_request_error", "param": None, "code": code } })

def _openai(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "api.openai.com":
		return None
	key = request.headers.get("Authorization", "").removeprefix("Bearer ")
	if key == "sk-busy":
		return _openai_error(429, "rate_limit_exceeded", "Rate limit reached.")
	if key == "sk-broke":
		return _openai_error(429, "insufficient_quota", "You exceeded your current quota.")
	if key != "sk-good":
		return _openai_error(401, "invalid_api_key", f"Incorrect API key provided: {key}. You can find your API key at https://platform.openai.com/account/api-keys.")
	known = { m["id"] for m in json.loads(fixture_text(OPENAI_MODELS))["data"] }
	if request.method == "GET" and request.url.path == "/v1/models":
		return httpx.Response(200, text=fixture_text(OPENAI_MODELS), headers={ "Content-Type": "application/json" })
	body = json.loads(request.read() or b"{}")
	model = body.get("model", "")
	if model not in known:
		return _openai_error(404, "model_not_found", f"The model `{model}` does not exist or you do not have access to it.")
	if request.method == "POST" and request.url.path == "/v1/images/generations":
		size = str(body.get("size", ""))
		w, _, h = size.partition("x")
		free = model.startswith("gpt-image-2")
		if not (w.isdigit() and h.isdigit()) or (free and (int(w) % 16 or int(h) % 16 or not 1 / 3 <= int(w) / int(h) <= 3)) \
				or (not free and size not in ("1024x1024", "1536x1024", "1024x1536")) or "response_format" in body or "style" in body:
			return _openai_error(400, "invalid_value", f"Invalid value: '{size}'.")
		png = synthetic_image(int(w) // 8, int(h) // 8, model, "PNG")
		return httpx.Response(200, json={ "created": 1789000000, "size": size, "data": [{ "b64_json": base64.b64encode(png).decode() }] })
	if request.method == "POST" and request.url.path == "/v1/responses":
		text = "A lighthouse drawn as a woodcut by Hokusai, in a storm of paper cranes"
		return httpx.Response(200, json={ "id": "resp_1", "object": "response", "created_at": 1789000000, "status": "completed", "model": model,
			"output": [{ "type": "message", "id": "msg_1", "status": "completed", "role": "assistant", "content": [{ "type": "output_text", "text": text, "annotations": [] }] }],
			"parallel_tool_calls": True, "tool_choice": "auto", "tools": [] })
	return _openai_error(404, "unknown_url", "Unknown request URL.")

# Google's Gemini API: AI Studio authorization keys ("AQ."), sent in the x-goog-api-key header only ("AQ.good" works, "AQ.busy" is a 429, "AQ.broke" a
# 403 saying the key type is unsupported; any other key, and a key in the address, is refused as the real service does). The discovery document is public
# and a fixture (trimmed to the schemas the code reads); the model list is a fixture served in two pages; a picture is a generated PNG in the shape asked,
# and the aspect ratio and size must be ones the discovery document lists (and the model takes: Flash Lite Image only 1K, Nano Banana no 512).
GOOGLE_DISCOVERY = "google-discovery.json"
GOOGLE_MODELS = "google-models.json"

def _google_error(status: int, code: str, reason: str|None = None) -> httpx.Response:
	error: dict = { "code": status, "message": "Google's own text, which can quote things (AQ.leaked).", "status": code }
	if reason:
		error["details"] = [{ "@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason }]
	return httpx.Response(status, json={ "error": error })

def _google_discovered() -> tuple[list[str], list[str]]:
	props = json.loads(fixture_text(GOOGLE_DISCOVERY))["schemas"]["ImageConfig"]["properties"]
	import re
	return (re.findall(r"`(\d+:\d+)`", props["aspectRatio"]["description"]), re.findall(r"`(\d+K|512)`", props["imageSize"]["description"]))

def _google(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "generativelanguage.googleapis.com":
		return None
	if request.url.path == "/$discovery/rest":
		return httpx.Response(200, text=fixture_text(GOOGLE_DISCOVERY), headers={ "Content-Type": "application/json" })
	key = request.headers.get("x-goog-api-key", "")
	if "key" in request.url.params or request.headers.get("Authorization"):
		return _google_error(401, "UNAUTHENTICATED", "ACCESS_TOKEN_TYPE_UNSUPPORTED")
	if key == "AQ.busy":
		return _google_error(429, "RESOURCE_EXHAUSTED")
	if key == "AQ.broke":
		return _google_error(403, "PERMISSION_DENIED", "ACCESS_TOKEN_TYPE_UNSUPPORTED")
	if key != "AQ.good":
		return _google_error(400, "INVALID_ARGUMENT", "API_KEY_INVALID")
	if request.method == "GET" and request.url.path == "/v1beta/models":
		everything = json.loads(fixture_text(GOOGLE_MODELS))["models"]
		half = len(everything) // 2
		if request.url.params.get("pageToken") == "p2":
			return httpx.Response(200, json={ "models": everything[half:] })
		return httpx.Response(200, json={ "models": everything[:half], "nextPageToken": "p2" })
	prefix, _, rest = request.url.path.partition("/v1beta/models/")
	model, _, action = rest.partition(":")
	if request.method != "POST" or prefix != "" or action != "generateContent":
		return _google_error(404, "NOT_FOUND")
	if model not in { m["baseModelId"] for m in json.loads(fixture_text(GOOGLE_MODELS))["models"] }:
		return _google_error(404, "NOT_FOUND")
	body = json.loads(request.read() or b"{}")
	config = body.get("generationConfig") or {}
	if "IMAGE" not in (config.get("responseModalities") or []):
		text = "A lighthouse drawn as a woodcut by Hokusai, in a storm of paper cranes"
		return httpx.Response(200, json={ "candidates": [{ "content": { "role": "model", "parts": [{ "text": text }] }, "finishReason": "STOP" }] })
	image = config.get("imageConfig") or {}
	ratios, sizes = _google_discovered()
	size = image.get("imageSize")
	if "flash-lite-image" in model:
		sizes = [s for s in sizes if s == "1K"]
	if "nano-banana" in model:
		sizes = [s for s in sizes if s != "512"]
	if image.get("aspectRatio") not in ratios or size not in sizes:
		return _google_error(400, "INVALID_ARGUMENT")
	w, _, h = str(image["aspectRatio"]).partition(":")
	scale = { "512": 40, "1K": 80, "2K": 160, "4K": 320 }[size]
	png = synthetic_image(int(w) * scale // max(int(w), int(h)), int(h) * scale // max(int(w), int(h)), model, "PNG")
	return httpx.Response(200, json={ "candidates": [{ "content": { "role": "model", "parts": [
		{ "text": "Here is the picture." }, { "inlineData": { "mimeType": "image/png", "data": base64.b64encode(png).decode() } }] }, "finishReason": "STOP" }] })

# Comic Vine: the key is a query parameter (`cv-good` works, `cv-busy` is over its hourly limit, any other is refused), the User-Agent must not be the HTTP library's own,
# and the series searched for is one with COMICVINE_ISSUES issues, 100 to a page, each with a (generated) cover; "nothing-here" matches nothing
COMICVINE_ISSUES = 250
COMICVINE_VOLUME = 4050

def _comicvine_body(status: int, code: int, error: str) -> httpx.Response:
	return httpx.Response(status, json={ "error": error, "status_code": code, "results": [], "number_of_total_results": 0 })

def _comicvine(request: httpx.Request) -> httpx.Response | None:
	if request.url.host != "comicvine.gamespot.com":
		return None
	path = request.url.path
	if path.startswith("/a/uploads/"):
		return _image(480, 740, path.rsplit("/", 1)[-1], "JPEG")
	if not path.startswith("/api/"):
		return None
	if "python-httpx" in request.headers.get("user-agent", ""):
		return httpx.Response(403, text="Forbidden")
	query = parse_qs(request.url.query.decode())
	key = (query.get("api_key") or [""])[0]
	if key == "cv-busy":
		return _comicvine_body(420, 107, "Rate limit exceeded")
	if key != "cv-good":
		return _comicvine_body(401, 100, "Invalid API Key")
	if path == "/api/search/":
		if (query.get("resources") or [""])[0] != "volume":
			return _comicvine_body(200, 102, "Filter Error")
		text = (query.get("query") or [""])[0]
		if text == "nothing-here":
			return httpx.Response(200, json={ "error": "OK", "status_code": 1, "number_of_total_results": 0, "results": [] })
		return httpx.Response(200, json={ "error": "OK", "status_code": 1, "number_of_total_results": 1, "results": [
			{ "id": COMICVINE_VOLUME, "name": "Test Tales", "start_year": "1951", "count_of_issues": COMICVINE_ISSUES, "publisher": { "name": "Fixture Press" } }] })
	if path == "/api/issues/":
		if (query.get("filter") or [""])[0] != f"volume:{COMICVINE_VOLUME}":
			return httpx.Response(200, json={ "error": "OK", "status_code": 1, "number_of_total_results": 0, "results": [] })
		offset, limit = int((query.get("offset") or ["0"])[0]), int((query.get("limit") or ["100"])[0])
		results = [{ "issue_number": str(n), "name": None if n % 2 else f"Tale {n}", "cover_date": f"{1951 + n // 12}-{n % 12 + 1:02d}-01",
			"image": { "super_url": f"https://comicvine.gamespot.com/a/uploads/scale_large/{COMICVINE_VOLUME}/{n}.jpg", "original_url": f"https://comicvine.gamespot.com/a/uploads/original/{COMICVINE_VOLUME}/{n}.jpg" } }
			for n in range(offset + 1, min(offset + limit, COMICVINE_ISSUES) + 1)]
		return httpx.Response(200, json={ "error": "OK", "status_code": 1, "number_of_total_results": COMICVINE_ISSUES, "results": results })
	return httpx.Response(404, text="Not found")

ROUTES: list[Callable[[httpx.Request], httpx.Response | None]] = [_comic_feed, _comic_image, _freedom_forum, _wikipedia_api, _wikimedia_image, _apod, _apod_image, _rss_feed, _rss_image, _picture_at_an_address, _calendar, _caldav, _weather, _ip_location, _openai, _google, _comicvine]

def install() -> FakeInternet | None:
	"""Make every `AsyncHttpWorkerPool` talk to the fake (unless EINK_TEST_LIVE is set)."""
	if os.environ.get("EINK_TEST_LIVE"):
		return None
	from ..task.async_http_worker_pool import AsyncHttpWorkerPool
	from ..utils import url_guard
	async def public(host: str, port: int) -> list[str]:
		# the fake hosts have no DNS: they all "resolve" to a public address, so the URL guard (every download goes through it) lets them pass;
		# a test that wants a refusal patches `url_guard._resolve` itself, or uses an address literal
		return ["93.184.216.34"]
	url_guard._resolve = public
	fake = FakeInternet()
	AsyncHttpWorkerPool.default_transport = fake
	return fake
