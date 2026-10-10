import os
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
from PIL import Image

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.rss import rss
from ..datasources.rss.rss import RssAsync, parse_stories, plain_text
from ..model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import client_var
from ..utils.image_utils import LINUX_CHROME_HEADLESS, WIN_CHROME_HEADLESS, os_type
from .fake_internet import FakeInternet, fixture_text
from .test_datasource_fixes import STATIC, FakeDatasourceSettings, FakeRenderSession, _Cob

NEWS = "https://news.example.test/feed.xml"
FEEDS = [
	{ "name": "News", "url": NEWS },
	{ "name": "Notes", "url": "https://notes.example.test/atom.xml" },
	{ "name": "Cookie wall", "url": "https://news.example.test/page" },
	{ "name": "Not the web", "url": "file:///etc/passwd" },
]

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: the display document and a theme."""
	THEME = { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 }
	def __init__(self, display):
		self.display = display
	def open(self, name: str):
		return _Cob(self.display if name == "display" else self.THEME)

def make_context(orientation: str = "landscape", feeds: list|None = None) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, cast(Any, FakeDatasourceSettings({ "feeds": FEEDS if feeds is None else feeds })))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({ "orientation": orientation })))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, (800, 480), datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))

class TestParsing(unittest.TestCase):
	def test_plain_text_drops_markup_and_reads_entities(self):
		self.assertEqual(plain_text("<p>The <b>long</b>   crossing &amp; more</p>"), "The long crossing & more")
		# markup that arrived escaped is dropped too
		self.assertEqual(plain_text("&lt;p&gt;Escaped &lt;i&gt;markup&lt;/i&gt;&lt;/p&gt;"), "Escaped markup")
		self.assertEqual(plain_text(None), "")

	def test_a_long_text_is_cut_at_a_word(self):
		cut = plain_text("alpha beta gamma delta epsilon", 14)
		self.assertEqual(cut, "alpha beta…")
		self.assertEqual(plain_text("short", 14), "short")

	def test_an_rss_feed_gives_its_stories_in_the_feeds_order(self):
		stories = parse_stories(fixture_text("rss-news.xml").encode(), "News")
		self.assertEqual(len(stories), 6)
		first = stories[0]
		self.assertEqual(first["title"], "Council & mayor agree on a new bridge")
		self.assertEqual(first["summary"], "The long-awaited crossing will open in 2029, after years of argument about the cost.")
		self.assertEqual((first["feed"], first["feed_title"], first["published"]), ("News", "Example Daily", "Oct 7, 2026"))

	def test_a_stories_picture_comes_from_its_media_its_enclosure_or_its_text(self):
		stories = parse_stories(fixture_text("rss-news.xml").encode(), "News")
		self.assertEqual([s["picture_url"] for s in stories[:4]],
			["https://img.example.test/bridge.jpg", "https://img.example.test/library.png", "https://img.example.test/market.gif", None])

	def test_an_atom_feed_reads_the_same_way(self):
		stories = parse_stories(fixture_text("rss-atom.xml").encode(), "Notes")
		self.assertEqual([s["title"] for s in stories], ["Second note", "First note"])
		self.assertEqual([s["summary"] for s in stories], ["Written later.", "Written first."])

	def test_a_page_that_is_no_feed_is_an_error(self):
		with self.assertRaisesRegex(RuntimeError, "not a feed"):
			parse_stories(b"<html><body>Please accept cookies</body></html>", "x")
		with self.assertRaisesRegex(RuntimeError, "no entries"):
			parse_stories(b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>', "x")

	def test_no_more_than_the_limit_is_listed(self):
		items = "".join(f"<item><title>Story {n}</title></item>" for n in range(rss.MAX_STORIES + 5))
		feed = f'<?xml version="1.0"?><rss version="2.0"><channel><title>Long</title>{items}</channel></rss>'
		self.assertEqual(len(parse_stories(feed.encode(), "Long")), rss.MAX_STORIES)

class TestOpen(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	async def test_the_named_feed_is_fetched_from_the_address_in_the_settings(self):
		stories = await RssAsync("rss", "rss").open_async(make_context(), { "feed": "News" })
		self.assertEqual(len(stories), 6)
		self.assertEqual([str(r.url) for r in self.fake.requests], [NEWS])
		# say who is asking, as feeds often refuse an unnamed client
		self.assertIn("eink-billboard", self.fake.requests[0].headers["User-Agent"])

	async def test_a_name_that_is_not_in_the_settings_is_permanent(self):
		for params, pattern in (({ "feed": "Gone" }, "'Gone' is not in the RSS Feed settings"), ({}, "'feed' setting is required"), ({ "feed": "Not the web" }, "no http or https address")):
			with self.subTest(params), self.assertRaisesRegex(PermanentError, pattern):
				await RssAsync("rss", "rss").open_async(make_context(), params)
		self.assertEqual(self.fake.requests, [], "nothing is fetched for a feed that cannot be chosen")

	async def test_a_site_that_answers_with_a_web_page_is_a_failure_that_can_be_retried(self):
		with self.assertRaisesRegex(RuntimeError, "not a feed") as raised:
			await RssAsync("rss", "rss").open_async(make_context(), { "feed": "Cookie wall" })
		self.assertNotIsInstance(raised.exception, PermanentError)

	async def test_a_feed_that_is_too_big_is_refused(self):
		big = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (rss.MAX_FEED_BYTES + 1))))
		client_var.set(big)
		with self.assertRaisesRegex(RuntimeError, "too large"):
			await RssAsync("rss", "rss").open_async(make_context(), { "feed": "News" })

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	async def story(self, index: int = 0) -> dict:
		return (await RssAsync("rss", "rss").open_async(make_context(), { "feed": "News" }))[index]

	async def render(self, params: dict, story: dict, orientation: str = "landscape"):
		with patch.object(rss, "RenderSession", FakeRenderSession):
			result = await RssAsync("rss", "rss").render_async(make_context(orientation), params, story)
		assert FakeRenderSession.last is not None
		return result, FakeRenderSession.last

	async def test_one_story_is_one_page_headed_with_the_feeds_name(self):
		result, session = await self.render({ "feed": "News", "fontSize": "normal" }, await self.story())
		assert result is not None
		self.assertEqual(result.title, "Council & mayor agree on a new bridge")
		self.assertEqual(session.params["heading"], "News")
		self.assertEqual(session.params["story"]["title"], "Council & mayor agree on a new bridge")
		self.assertEqual(session.dimensions, (800, 480))

	async def test_the_title_setting_replaces_the_heading(self):
		_, session = await self.render({ "feed": "News", "title": "Town news" }, await self.story())
		self.assertEqual(session.params["heading"], "Town news")

	async def test_a_portrait_display_gets_a_portrait_page(self):
		_, session = await self.render({ "feed": "News" }, await self.story(), "portrait")
		self.assertEqual(session.dimensions, (480, 800))

	async def test_the_text_size_scales_the_page(self):
		scales = {}
		for size in ("x-small", "normal", "x-large", "bogus"):
			_, session = await self.render({ "feed": "News", "fontSize": size }, await self.story())
			scales[size] = session.params["font_scale"]
		self.assertLess(scales["x-small"], scales["normal"])
		self.assertLess(scales["normal"], scales["x-large"])
		self.assertEqual(scales["bogus"], 1.0)

	async def test_a_picture_is_fetched_only_when_asked_for_and_is_embedded(self):
		story = await self.story()
		_, session = await self.render({ "feed": "News", "includeImages": False }, story)
		self.assertIsNone(session.params["story"]["picture"])
		self.assertFalse([r for r in self.fake.requests if r.url.host == "img.example.test"])
		_, session = await self.render({ "feed": "News", "includeImages": True }, story)
		self.assertTrue(session.params["story"]["picture"].startswith("data:image/jpeg;base64,"))

	async def test_a_picture_that_cannot_be_fetched_leaves_the_story_without_it(self):
		client_var.set(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
		story = { "feed": "News", "feed_title": "", "title": "T", "summary": "S", "published": "", "picture_url": "https://img.example.test/missing.jpg" }
		result, session = await self.render({ "feed": "News", "includeImages": True }, story)
		assert result is not None and session is not None
		self.assertIsNone(session.params["story"]["picture"])

	async def test_nothing_to_show_is_none(self):
		with patch.object(rss, "RenderSession", FakeRenderSession):
			self.assertIsNone(await RssAsync("rss", "rss").render_async(make_context(), { "feed": "News" }, None))

CHROME = WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The page as Chromium draws it, with and without a picture, on both orientations; the images are in .test-output/rss for a look."""
	def setUp(self):
		client_var.set(httpx.AsyncClient(transport=FakeInternet()))

	async def test_pages_are_drawn_at_the_display_size(self):
		folder = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.joinpath(".test-output", "rss")
		folder.mkdir(parents=True, exist_ok=True)
		ds = RssAsync("rss", "rss")
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
			stories = await ds.open_async(make_context(orientation), { "feed": "News" })
			for number, include in ((0, True), (3, False)):
				with self.subTest(orientation=orientation, story=number):
					result = await ds.render_async(make_context(orientation), { "feed": "News", "includeImages": include, "fontSize": "normal" }, stories[number])
					assert result is not None
					self.assertEqual(result.image.size, size)
					result.image.save(folder.joinpath(f"{orientation}-{number}.png"))
					self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")
					self.assertIsInstance(result.image, Image.Image)
