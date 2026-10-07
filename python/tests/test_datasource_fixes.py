"""
Offline tests for the datasources: fake images, feeds and HTTP transports; nothing here needs the internet,
the test storage's datasources/ or plugins/ folders, or a browser.
"""
import asyncio
import io
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import httpx
import openai
from PIL import Image

from ..datasources import data_source
from ..datasources.clock.clock import Clock, ClockAsync
from ..datasources.comic import comic_feed, comic_parser
from ..datasources.comic.comic_feed import ComicFeedAsync, _compose_image
from ..datasources.countdown import countdown
from ..datasources.countdown.countdown import CountdownAsync
from ..datasources.data_source import DataSourceExecutionContext, target_dimensions
from ..datasources.image_folder.image_folder import ImageFolderAsync, grab_image
from ..datasources.newspaper.newspaper import NewspaperAsync
from ..datasources.openai_image import openai_image
from ..datasources.openai_image.openai_image import OpenAIAsync
from ..datasources.wpotd import wpotd
from ..datasources.wpotd.wpotd import WpotdAsync
from ..datasources.year_progress import year_progress
from ..datasources.year_progress.year_progress import YearProgressAsync
from ..model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..task.async_http_worker_pool import client_var

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
TZ_TOKYO = timezone(timedelta(hours=9))

class _Cob:
	def __init__(self, value):
		self.value = value
	def get(self):
		return "rev", self.value

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: only the display document."""
	def __init__(self, display):
		self.display = display
	def open(self, name: str):
		assert name == "display"
		return _Cob(self.display)

def make_dsec(orientation="landscape", dimensions=(800, 480), ts=None) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({"orientation": orientation})))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, dimensions, ts or datetime(2026, 10, 7, 12, 0, tzinfo=TZ_TOKYO))

def png_bytes(size=(40, 30), color="red", mode="RGB") -> bytes:
	b = io.BytesIO()
	Image.new(mode, size, color).save(b, "PNG")
	return b.getvalue()

def mock_client(handler) -> httpx.AsyncClient:
	return httpx.AsyncClient(transport=httpx.MockTransport(handler))

class TestTargetDimensions(unittest.TestCase):
	def test_landscape_unchanged_portrait_swapped(self):
		self.assertEqual(target_dimensions(make_dsec("landscape")), (800, 480))
		self.assertEqual(target_dimensions(make_dsec("portrait")), (480, 800))
	def test_explicit_settings_win(self):
		self.assertEqual(target_dimensions(make_dsec("landscape"), {"orientation": "portrait"}), (480, 800))
	def test_unavailable_settings_means_landscape(self):
		dsec = DataSourceExecutionContext(ServiceContainer(), (800, 480), datetime.now())
		self.assertEqual(target_dimensions(dsec), (800, 480))

# ---------------------------------------------------------------- 1. OpenAI

class FakeImages:
	def __init__(self, owner):
		self.owner = owner
	async def generate(self, **args):
		self.owner.calls.append(args)
		if self.owner.error is not None:
			raise self.owner.error
		import base64
		return SimpleNamespace(data=[SimpleNamespace(url="http://x/i.png", b64_json=base64.b64encode(png_bytes((4, 4))).decode())])

class FakeAI:
	def __init__(self, error=None):
		self.calls: list[dict] = []
		self.error = error
		self.closed = False
		self.images = FakeImages(self)
	async def __aenter__(self):
		return self
	async def __aexit__(self, *exc):
		self.closed = True
	async def close(self):
		self.closed = True

class TestOpenAI(unittest.IsolatedAsyncioTestCase):
	async def _size(self, model, orientation):
		ai = FakeAI()
		await OpenAIAsync.fetch_image(logging.getLogger("t"), ai, "a cat", model=model, orientation=orientation)
		return ai.calls[0]["size"]
	async def test_landscape_gets_wide_size(self):
		self.assertEqual(await self._size("gpt-image-1", "landscape"), "1536x1024")
		with patch.object(openai_image, "get_image_async", return_value=Image.new("RGB", (2, 2))):
			self.assertEqual(await self._size("dall-e-3", "landscape"), "1792x1024")
	async def test_portrait_gets_tall_size_and_horizontal_still_means_wide(self):
		self.assertEqual(await self._size("gpt-image-1", "portrait"), "1024x1536")
		with patch.object(openai_image, "get_image_async", return_value=Image.new("RGB", (2, 2))):
			self.assertEqual(await self._size("dall-e-3", "portrait"), "1024x1792")
			self.assertEqual(await self._size("dall-e-3", "horizontal"), "1792x1024")
	async def _dispatch(self, ai: FakeAI):
		ds = OpenAIAsync("openai-image", "openai-image")
		with patch.object(openai, "AsyncOpenAI", return_value=ai):
			return await ds._dispatch_image(cast(Any, None), "sk-secretsecret123", "gpt-image-1", "medium", "p", False, "landscape")
	async def test_client_is_closed(self):
		ai = FakeAI()
		img = await self._dispatch(ai)
		self.assertIsNotNone(img)
		self.assertTrue(ai.closed)
	async def test_client_is_closed_on_error(self):
		ai = FakeAI(error=RuntimeError("boom"))
		with self.assertRaises(RuntimeError):
			await self._dispatch(ai)
		self.assertTrue(ai.closed)
	async def test_bad_request_with_missing_or_text_body(self):
		resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
		for body in (None, "plain text body", {"message": "nope"}, {"error": 1}):
			with self.subTest(body=body):
				ai = FakeAI(error=openai.BadRequestError("bad", response=resp, body=body))
				with self.assertRaises(RuntimeError) as cm:
					await self._dispatch(ai)
				self.assertNotIsInstance(cm.exception, AttributeError)
				self.assertIn("Bad Request", str(cm.exception))
	async def test_key_is_redacted_from_errors_and_logs(self):
		msg = "Incorrect API key provided: sk-proj-abcDEF123_456-xyz. You can find your API key at https://platform.openai.com."
		ai = FakeAI(error=RuntimeError(msg))
		with self.assertLogs(openai_image.__name__, level="DEBUG") as logs, self.assertRaises(RuntimeError) as cm:
			await self._dispatch(ai)
		everything = str(cm.exception) + "\n".join(logs.output)
		self.assertNotIn("abcDEF123", everything)
		self.assertNotIn("sk-secretsecret123", everything)
		self.assertIn("sk-***", str(cm.exception))
	async def test_bad_request_message_is_redacted_too(self):
		resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
		ai = FakeAI(error=openai.BadRequestError("bad", response=resp, body={"message": "key sk-abcdef123456 is bad"}))
		with self.assertRaises(RuntimeError) as cm:
			await self._dispatch(ai)
		self.assertNotIn("abcdef123456", str(cm.exception))

# ---------------------------------------------------------------- 2. comic

class TestComic(unittest.IsolatedAsyncioTestCase):
	def _font(self, size=16):
		return StaticConfigurationManager(STATIC).get_font("Jost", font_size=size)
	def test_caption_taller_than_image_area_does_not_raise(self):
		item = {"title": "t", "caption": "word " * 200}
		out = _compose_image(io.BytesIO(png_bytes((100, 50))), item, self._font(), 200, 40)
		self.assertEqual(out.size, (200, 40))
	def test_rgba_comic_is_composited_on_white(self):
		src = io.BytesIO()
		Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(src, "PNG")
		src.seek(0)
		out = _compose_image(src, {"title": "", "caption": ""}, None, 40, 40)
		self.assertEqual(out.getpixel((20, 20)), (255, 255, 255))
	def test_palette_comic_with_transparency_is_composited_on_white(self):
		src = io.BytesIO()
		img = Image.new("P", (20, 20), 0)
		img.putpalette([0, 0, 0] * 256)
		img.save(src, "PNG", transparency=0)
		src.seek(0)
		out = _compose_image(src, {"title": "", "caption": ""}, None, 40, 40)
		self.assertEqual(out.getpixel((20, 20)), (255, 255, 255))
	async def _generate(self, orientation, **params):
		seen = {}
		ds = ComicFeedAsync("comic", "comic")
		async def fake(item, caption_font, width, height):
			seen.update(font=caption_font, size=(width, height))
			return Image.new("RGB", (width, height))
		ds._download_and_compose_image = fake  # type: ignore[method-assign]
		await ds._generate_image(make_dsec(orientation), params, {"title": "t", "caption": "c", "image_url": "http://x"})
		return seen
	async def test_boolean_title_caption_enables_font(self):
		self.assertIsNotNone((await self._generate("landscape", titleCaption=True))["font"])
		self.assertIsNone((await self._generate("landscape", titleCaption=False))["font"])
		self.assertIsNone((await self._generate("landscape"))["font"])
	async def test_portrait_swaps_dimensions(self):
		self.assertEqual((await self._generate("portrait", titleCaption=True))["size"], (480, 800))
		self.assertEqual((await self._generate("landscape"))["size"], (800, 480))
	async def test_feed_errors(self):
		client_var.set(mock_client(lambda req: httpx.Response(503)))
		with self.assertRaises(httpx.HTTPStatusError):
			await comic_parser.get_items_async("XKCD")
	async def test_html_instead_of_feed_gives_empty_list_and_error(self):
		html = "<html><body><h1>Please enable cookies</h1></body></html>"
		client_var.set(mock_client(lambda req: httpx.Response(200, text=html, headers={"Content-Type": "text/html"})))
		with self.assertLogs(comic_parser.__name__, level="ERROR") as logs:
			items = await comic_parser.get_items_async("XKCD")
		self.assertEqual(items, [])
		self.assertIn("XKCD", "\n".join(logs.output))
	async def test_real_feed_still_parses(self):
		atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title><entry><title>T</title>
		<link href="http://x/1"/><id>1</id><updated>2026-01-01T00:00:00Z</updated>
		<summary type="html">&lt;img src="http://x/a.png" alt="alt text" /&gt;</summary></entry></feed>"""
		client_var.set(mock_client(lambda req: httpx.Response(200, text=atom, headers={"Content-Type": "application/atom+xml"})))
		items = await comic_parser.get_items_async("XKCD")
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0]["image_url"], "http://x/a.png")

# ---------------------------------------------------------------- 3. clock

class TestClock(unittest.IsolatedAsyncioTestCase):
	@staticmethod
	def _hour_cells(hour_index):
		hours = {
			0: [[5,0],[5,1],[5,2]],
			2: [[5,6],[5,7],[5,8],[5,9],[5,10]],
			1: [[6,8],[6,9],[6,10]],
			11: [[8,5],[8,6],[8,7],[8,8],[8,9],[8,10]],
		}
		return hours[hour_index]
	def test_half_past_plus_three_says_the_next_hour(self):
		# 2:33 is "twenty-five TO three"
		cells = Clock.translate_word_grid_positions(2, 33)
		for c in self._hour_cells(2):
			self.assertIn(c, cells)
		for c in [[3, 9], [3, 10]]:
			self.assertIn(c, cells, "TO")
		for c in self._hour_cells(1):
			self.assertNotIn(c, cells, "TWO must not be lit")
	def test_hour_wraps(self):
		# 12:40 -> hour%12 == 0 -> "twenty to ONE"; 23:40 -> 11 -> "twenty to TWELVE"
		self.assertTrue(all(c in Clock.translate_word_grid_positions(0, 40) for c in self._hour_cells(0)))
		self.assertTrue(all(c in Clock.translate_word_grid_positions(11, 40) for c in self._hour_cells(11)))
	def test_past_still_uses_the_current_hour(self):
		cells = Clock.translate_word_grid_positions(2, 32)
		for c in self._hour_cells(1):
			self.assertIn(c, cells)
		self.assertNotIn([3, 9], cells)
	async def test_colors_accept_tuples_lists_and_strings(self):
		ds = ClockAsync("clock", "clock")
		for primary in ((255, 255, 255), [255, 255, 255], "#ffffff", "white", None, ""):
			with self.subTest(primary=primary):
				state = await ds.open_async(cast(Any, None), {"primaryColor": primary, "secondaryColor": (1, 2, 3)})
				self.assertEqual(state["primary_color"], (255, 255, 255))
				self.assertEqual(state["secondary_color"], (1, 2, 3))
	async def test_invalid_color_is_a_clear_error(self):
		with self.assertRaisesRegex(ValueError, "primaryColor"):
			await ClockAsync("clock", "clock").open_async(cast(Any, None), {"primaryColor": "not-a-color"})
	async def test_draw_failure_is_logged_with_traceback(self):
		ds = ClockAsync("clock", "clock")
		state = {"clock_face": "Divided Clock", "primary_color": (1, 2, 3), "secondary_color": (4, 5, 6)}
		with patch.object(Clock, "draw_divided_clock", side_effect=ZeroDivisionError("kaboom")), self.assertLogs(ds.logger, level="ERROR") as logs:
			result = await ds.render_async(make_dsec(), {}, state)
		self.assertIsNone(result)
		self.assertTrue(any(r.exc_info for r in logs.records), "the traceback was not logged")
	async def test_portrait_faces_have_portrait_size(self):
		ds = ClockAsync("clock", "clock")
		for face in ("Gradient Clock", "Digital Clock", "Divided Clock", "Word Clock"):
			with self.subTest(face=face):
				state = {"clock_face": face, "primary_color": (255, 255, 255), "secondary_color": (0, 0, 0)}
				result = await ds.render_async(make_dsec("portrait"), {}, state)
				assert result is not None
				self.assertEqual(result.image.size, (480, 800))

# ---------------------------------------------------------------- 4. countdown / year progress

class FakeRenderSession:
	"""Records what would have been rendered; produces an image of the requested size."""
	last: "FakeRenderSession|None" = None
	def __init__(self, *a, **k):
		FakeRenderSession.last = self
	def render(self, dimensions, template_params={}):
		self.dimensions = tuple(dimensions)
		self.params = template_params
		return Image.new("RGB", tuple(dimensions), "white")

class TestCountdown(unittest.TestCase):
	def _gen(self, ts, target):
		stm = StaticConfigurationManager(STATIC)
		with patch.object(countdown, "RenderSession", FakeRenderSession):
			countdown.generate_image(ts, stm, (800, 480), {"targetDate": target})
		assert FakeRenderSession.last is not None
		return FakeRenderSession.last
	def test_same_local_day_is_zero_days(self):
		# 2026-10-08 08:00 in Tokyo is still Oct 7 in US/Eastern
		rs = self._gen(datetime(2026, 10, 8, 8, 0, tzinfo=TZ_TOKYO), "2026-10-08")
		self.assertEqual(rs.params["day_count"], 0)
		self.assertEqual(rs.params["label"], "Today")
	def test_future_and_past(self):
		ts = datetime(2026, 10, 8, 8, 0, tzinfo=TZ_TOKYO)
		future = self._gen(ts, "2026-10-11")
		self.assertEqual((future.params["day_count"], future.params["label"]), (3, "Days Left"))
		past = self._gen(ts, "2026-10-05")
		self.assertEqual((past.params["day_count"], past.params["label"]), (3, "Days Passed"))
	def test_date_uses_the_timestamps_own_zone(self):
		# 23:30 UTC on the 7th is the 8th in Tokyo; the zone of the timestamp decides
		self.assertEqual(self._gen(datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc), "2026-10-08").params["day_count"], 1)
		self.assertEqual(self._gen(datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc).astimezone(TZ_TOKYO), "2026-10-08").params["day_count"], 0)

class TestYearProgress(unittest.TestCase):
	def _gen(self, ts):
		stm = StaticConfigurationManager(STATIC)
		with patch.object(year_progress, "RenderSession", FakeRenderSession):
			year_progress.generate_image(ts, stm, (800, 480), {})
		assert FakeRenderSession.last is not None
		return FakeRenderSession.last
	def test_dec_31_morning_is_not_100_percent_or_zero_days(self):
		rs = self._gen(datetime(2026, 12, 31, 8, 0, tzinfo=TZ_TOKYO))
		self.assertEqual(rs.params["year_percent"], 99)
		self.assertEqual(rs.params["days_left"], 1)
	def test_start_of_year(self):
		rs = self._gen(datetime(2026, 1, 1, 0, 0, tzinfo=TZ_TOKYO))
		self.assertEqual((rs.params["year"], rs.params["year_percent"], rs.params["days_left"]), (2026, 0, 365))
	def test_year_is_the_timestamps_own(self):
		# Jan 1 00:30 in Tokyo is still Dec 31 in US/Eastern
		self.assertEqual(self._gen(datetime(2027, 1, 1, 0, 30, tzinfo=TZ_TOKYO)).params["year"], 2027)
	def test_mid_year(self):
		rs = self._gen(datetime(2026, 7, 2, 12, 0, tzinfo=TZ_TOKYO))
		self.assertEqual(rs.params["year_percent"], 50)

class TestRenderAsyncKeepsLoopFree(unittest.IsolatedAsyncioTestCase):
	async def test_countdown_and_year_progress_render_off_the_loop(self):
		main = __import__("threading").get_ident()
		seen = []
		class Session(FakeRenderSession):
			def render(self, dimensions, template_params={}):
				seen.append(__import__("threading").get_ident())
				return super().render(dimensions, template_params)
		with patch.object(countdown, "RenderSession", Session), patch.object(year_progress, "RenderSession", Session):
			a = await CountdownAsync("c", "c").render_async(make_dsec("portrait"), {"targetDate": "2026-12-25"}, {})
			b = await YearProgressAsync("y", "y").render_async(make_dsec("portrait"), {}, {})
		assert a is not None and b is not None
		self.assertEqual(a.image.size, (480, 800))
		self.assertEqual(b.image.size, (480, 800))
		self.assertTrue(all(t != main for t in seen), "Chromium render ran on the event loop thread")

# ---------------------------------------------------------------- 7/11. image folder

class TestImageFolder(unittest.TestCase):
	def test_every_mode_loads_with_padding(self):
		log = logging.getLogger("t")
		with tempfile.TemporaryDirectory() as d:
			for mode in ("P", "1", "LA", "RGBA", "L", "RGB"):
				p = os.path.join(d, f"{mode}.png")
				Image.new(mode, (40, 30)).save(p)
				with self.subTest(mode=mode):
					img = grab_image(p, (80, 48), True, log)
					self.assertIsNotNone(img, f"{mode} image was skipped")
					assert img is not None
					self.assertEqual(img.size, (80, 48))
			p = os.path.join(d, "anim.gif")
			Image.new("P", (40, 30)).save(p)
			self.assertIsNotNone(grab_image(p, (80, 48), True, log))
	def test_portrait_target_gives_portrait_image(self):
		with tempfile.TemporaryDirectory() as d:
			p = os.path.join(d, "a.png")
			Image.new("RGB", (400, 300)).save(p)
			img = grab_image(p, (480, 800), True, logging.getLogger("t"))
			assert img is not None
			self.assertEqual(img.size, (480, 800))
	def test_transparent_png_is_padded_on_white_not_black(self):
		with tempfile.TemporaryDirectory() as d:
			p = os.path.join(d, "a.png")
			Image.new("RGBA", (40, 30), (0, 0, 0, 0)).save(p)
			img = grab_image(p, (40, 30), False, logging.getLogger("t"))
			assert img is not None
			self.assertEqual(img.convert("RGB").getpixel((5, 5)), (255, 255, 255))
	def test_missing_folder_is_a_clear_error(self):
		ds = ImageFolderAsync("f", "f")
		with self.assertRaisesRegex(ValueError, "not a folder"):
			asyncio.run(ds.open_async(cast(Any, None), {"folder": "/definitely/not/here"}))
	def test_empty_folder_gives_empty_list(self):
		ds = ImageFolderAsync("f", "f")
		with tempfile.TemporaryDirectory() as d:
			self.assertEqual(asyncio.run(ds.open_async(cast(Any, None), {"folder": d})), [])
	def test_render_uses_portrait_dimensions(self):
		ds = ImageFolderAsync("f", "f")
		with tempfile.TemporaryDirectory() as d:
			p = os.path.join(d, "a.png")
			Image.new("RGB", (400, 300)).save(p)
			result = asyncio.run(ds.render_async(make_dsec("portrait"), {}, p))
			assert result is not None
			self.assertEqual(result.image.size, (480, 800))

# ---------------------------------------------------------------- 9. wpotd

class TestWpotd(unittest.IsolatedAsyncioTestCase):
	def test_big_image_fits_inside_the_box(self):
		ds = WpotdAsync("w", "w")
		src = Image.new("RGB", (4000, 3000), (255, 0, 0))
		out = ds._shrink_to_fit(src, 800, 480)
		self.assertEqual(out.size, (800, 480))
		# 4:3 into 800x480 is 640x480: white bars left and right, picture in the middle
		self.assertEqual(out.getpixel((10, 240)), (255, 255, 255))
		self.assertEqual(out.getpixel((400, 240)), (255, 0, 0))
		self.assertEqual(out.getpixel((789, 240)), (255, 255, 255))
	def test_tall_image_fits_inside_the_box(self):
		out = WpotdAsync("w", "w")._shrink_to_fit(Image.new("RGB", (3000, 4000), (255, 0, 0)), 800, 480)
		self.assertEqual(out.size, (800, 480))
		self.assertEqual(out.getpixel((400, 240)), (255, 0, 0))
		self.assertEqual(out.getpixel((200, 240)), (255, 255, 255))
	def test_wide_image_fits_inside_the_box(self):
		out = WpotdAsync("w", "w")._shrink_to_fit(Image.new("RGB", (4000, 1000), (255, 0, 0)), 800, 480)
		self.assertEqual(out.size, (800, 480))
		self.assertEqual(out.getpixel((400, 5)), (255, 255, 255))
		self.assertEqual(out.getpixel((400, 240)), (255, 0, 0))
	def test_small_image_is_centred_not_enlarged(self):
		out = WpotdAsync("w", "w")._shrink_to_fit(Image.new("RGB", (100, 50), (255, 0, 0)), 800, 480)
		self.assertEqual(out.size, (800, 480))
		self.assertEqual(out.getpixel((400, 240)), (255, 0, 0))
		self.assertEqual(out.getpixel((300, 240)), (255, 255, 255))
	async def test_render_fits_portrait_canvas(self):
		ds = WpotdAsync("w", "w")
		client_var.set(mock_client(lambda req: httpx.Response(200, content=png_bytes((400, 300)), headers={"Content-Type": "image/png"})))
		result = await ds.render_async(make_dsec("portrait"), {"shrinkToFit": True}, {"url": "http://x/a.png", "date": "d"})
		assert result is not None
		self.assertEqual(result.image.size, (480, 800))
	async def test_thumbnail_is_requested_and_used(self):
		seen = []
		def handler(req: httpx.Request):
			seen.append(dict(req.url.params))
			if req.url.params.get("prop") == "images":
				return httpx.Response(200, json={"query": {"pages": [{"images": [{"title": "File:A.jpg"}]}]}})
			return httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [{"url": "http://orig/A.jpg", "thumburl": "http://thumb/A.jpg"}]}}}})
		client_var.set(mock_client(handler))
		ds = WpotdAsync("w", "w")
		state = await ds.open_async(make_dsec("landscape"), {"customDate": "2026-01-02"})
		self.assertEqual(state[0]["url"], "http://thumb/A.jpg")
		info = [p for p in seen if p.get("prop") == "imageinfo"][0]
		self.assertEqual(info["iiurlwidth"], "1600")
		self.assertIn("url", info["iiprop"])
	async def test_falls_back_to_original_without_thumbnail(self):
		def handler(req: httpx.Request):
			if req.url.params.get("prop") == "images":
				return httpx.Response(200, json={"query": {"pages": [{"images": [{"title": "File:A.jpg"}]}]}})
			return httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [{"url": "http://orig/A.jpg"}]}}}})
		client_var.set(mock_client(handler))
		state = await WpotdAsync("w", "w").open_async(make_dsec(), {"customDate": "2026-01-02"})
		self.assertEqual(state[0]["url"], "http://orig/A.jpg")
	async def test_svg_error_names_the_datasource(self):
		ds = WpotdAsync("w", "My Wiki Source")
		with self.assertLogs(wpotd.__name__, level="WARNING") as logs, self.assertRaises(RuntimeError) as cm:
			await ds._download_image("http://x/a.svg")
		self.assertIn("My Wiki Source", str(cm.exception))
		self.assertNotIn("{self.name}", str(cm.exception) + "\n".join(logs.output))
		self.assertIn("My Wiki Source", "\n".join(logs.output))
	async def test_oversized_download_is_refused(self):
		client_var.set(mock_client(lambda req: httpx.Response(200, content=b"x" * 5000, headers={"Content-Type": "image/png"})))
		with patch.object(wpotd, "MAX_IMAGE_BYTES", 1000), self.assertLogs(wpotd.__name__, level="ERROR"), self.assertRaises(RuntimeError):
			await WpotdAsync("w", "w")._download_image("http://x/a.png")

# ---------------------------------------------------------------- 10. newspaper

class TestNewspaper(unittest.IsolatedAsyncioTestCase):
	TS = datetime(2026, 10, 7, 12, 0, tzinfo=TZ_TOKYO)
	def _pad(self, size, dims):
		ds = NewspaperAsync("n", "n")
		return ds._pad_to_ratio(Image.new("RGB", size, (10, 10, 10)), dims)
	def test_narrow_cover_gets_wider_canvas(self):
		out = self._pad((700, 1166), (800, 480))
		self.assertEqual(out.height, 1166)
		self.assertAlmostEqual(out.width / out.height, 800 / 480, delta=0.01)
		self.assertEqual(out.getpixel((out.width // 2, 500)), (10, 10, 10))
		self.assertEqual(out.getpixel((2, 500)), (255, 255, 255))
	def test_wide_cover_gets_taller_canvas(self):
		out = self._pad((1000, 300), (800, 480))
		self.assertEqual(out.width, 1000)
		self.assertAlmostEqual(out.width / out.height, 800 / 480, delta=0.01)
	def test_ratio_for_portrait_target(self):
		out = self._pad((1000, 1000), (480, 800))
		self.assertAlmostEqual(out.width / out.height, 480 / 800, delta=0.01)
	def test_matching_ratio_untouched(self):
		src = Image.new("RGB", (800, 480))
		self.assertIs(NewspaperAsync("n", "n")._pad_to_ratio(src, (800, 480)), src)
	async def test_unknown_slug_is_a_clear_error(self):
		with self.assertRaisesRegex(ValueError, "Unknown newspaper"):
			await NewspaperAsync("n", "n").open_async(make_dsec(), {"slug": "../../etc/passwd"})
	async def test_known_slug_any_case(self):
		self.assertEqual(await NewspaperAsync("n", "n").open_async(make_dsec(), {"slug": "ny_nyt"}), ["NY_NYT"])
		self.assertEqual(await NewspaperAsync("n", "n").open_async(make_dsec(), {"slug": "NY_NYT"}), ["NY_NYT"])
	async def test_falls_back_to_previous_day_on_errors(self):
		# +1 day: timeout, today: garbage that is not an image, yesterday: a real cover
		def handler(req: httpx.Request):
			path = req.url.path
			if "jpg8/" in path:
				raise httpx.ConnectTimeout("slow", request=req)
			if "jpg7/" in path:
				return httpx.Response(200, content=b"<html>not a jpeg</html>", headers={"Content-Type": "image/jpeg"})
			if "jpg6/" in path:
				return httpx.Response(200, content=png_bytes((600, 900)), headers={"Content-Type": "image/png"})
			return httpx.Response(404)
		client_var.set(mock_client(handler))
		result = await NewspaperAsync("n", "n").render_async(make_dsec("landscape"), {}, "NY_NYT")
		assert result is not None
		self.assertAlmostEqual(result.image.width / result.image.height, 800 / 480, delta=0.01)
	async def test_all_days_failing_is_an_error(self):
		client_var.set(mock_client(lambda req: httpx.Response(404)))
		with self.assertRaisesRegex(RuntimeError, "not found"):
			await NewspaperAsync("n", "n").render_async(make_dsec(), {}, "NY_NYT")

if __name__ == "__main__":
	unittest.main()
