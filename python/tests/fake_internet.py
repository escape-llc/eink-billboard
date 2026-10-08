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
COMIC_IMAGE_HOSTS = ("imgs.xkcd.com", "files.explosm.net", "www.smbc-comics.com", "pbfcomics.com", "www.questionablecontent.net",
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
	if request.url.host == "upload.wikimedia.org" and request.url.path.startswith("/wikipedia/"):
		return _image(1280, 853, request.url.path.rsplit("/", 1)[-1], "JPEG")
	return None

ROUTES: list[Callable[[httpx.Request], httpx.Response | None]] = [_comic_feed, _comic_image, _freedom_forum, _wikipedia_api, _wikimedia_image]

def install() -> FakeInternet | None:
	"""Make every `AsyncHttpWorkerPool` talk to the fake (unless EINK_TEST_LIVE is set)."""
	if os.environ.get("EINK_TEST_LIVE"):
		return None
	from ..task.async_http_worker_pool import AsyncHttpWorkerPool
	fake = FakeInternet()
	AsyncHttpWorkerPool.default_transport = fake
	return fake
