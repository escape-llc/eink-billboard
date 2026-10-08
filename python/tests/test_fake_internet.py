import asyncio
import io
import unittest

import httpx
from PIL import Image

from ..datasources.comic.comic_parser import COMICS, parse_the_feed
from ..datasources.newspaper.newspaper import FREEDOM_FORUM_URL, KNOWN_SLUGS
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .fake_internet import COMIC_FEEDS, FakeInternet, fixture_text

def get(url: str, **kwargs) -> httpx.Response:
	async def run():
		async with httpx.AsyncClient(transport=FakeInternet()) as client:
			return await client.get(url, **kwargs)
	return asyncio.run(run())

class TestFakeInternet(unittest.TestCase):
	def test_the_tests_run_against_it_by_default(self):
		import os
		if os.environ.get("EINK_TEST_LIVE"):
			self.skipTest("EINK_TEST_LIVE is set")
		self.assertIsInstance(AsyncHttpWorkerPool.default_transport, FakeInternet)

	def test_every_comic_feed_is_served_and_the_parsers_read_it(self):
		import feedparser
		for name, comic in COMICS.items():
			url = httpx.URL(comic["feed"])
			self.assertIn((url.host, url.path or "/"), COMIC_FEEDS, f"{name}: the fake does not serve its feed")
			response = get(comic["feed"])
			self.assertEqual(response.status_code, 200)
			items = parse_the_feed(name, comic, feedparser.parse(response.text))
			self.assertGreaterEqual(len(items), 4, f"{name}: the fixture feed has fewer than 4 entries the parser reads")
			# the images the feed points at are served too
			image = get(items[0]["image_url"])
			self.assertTrue(image.headers["Content-Type"].startswith("image/"))
			Image.open(io.BytesIO(image.content)).load()

	def test_every_newspaper_cover_is_served_as_a_jpeg_for_any_day(self):
		for slug in list(KNOWN_SLUGS)[:3]:
			for day in (1, 15, 31):
				response = get(FREEDOM_FORUM_URL.format(day, slug))
				self.assertEqual(response.headers["Content-Type"], "image/jpeg")
				self.assertEqual(Image.open(io.BytesIO(response.content)).size, (700, 1166))

	def test_wikipedia_answers_the_two_questions_the_datasource_asks(self):
		potd = get("https://en.wikipedia.org/w/api.php", params={ "action": "query", "format": "json", "formatversion": "2", "prop": "images", "titles": "Template:POTD/2030-01-01" }).json()
		filename = potd["query"]["pages"][0]["images"][0]["title"]
		info = get("https://en.wikipedia.org/w/api.php", params={ "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1280, "titles": filename }).json()
		url = next(iter(info["query"]["pages"].values()))["imageinfo"][0]["thumburl"]
		image = get(url)
		self.assertEqual(image.headers["Content-Type"], "image/jpeg")
		Image.open(io.BytesIO(image.content)).load()

	def test_any_other_address_is_a_loud_error_not_the_network(self):
		for url in ("https://example.com/", "https://xkcd.com/other", "https://en.wikipedia.org/w/api.php?action=other"):
			with self.assertRaisesRegex(httpx.ConnectError, "offline test: no canned response"):
				get(url)

	def test_fixture_files_are_text_the_recorder_can_replace(self):
		self.assertIn("<feed", fixture_text("xkcd-atom.xml"))
		self.assertTrue(fixture_text("wikipedia-potd-images.json").lstrip().startswith("{"))

if __name__ == "__main__":
	unittest.main()
