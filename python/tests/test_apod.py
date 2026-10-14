import unittest
from datetime import date, datetime
from unittest.mock import patch

import httpx

from ..datasources.apod import apod
from ..datasources.apod.apod import ApodAsync, chosen_day, day_id, picture_of, random_day
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import client_var
from .fake_internet import FakeInternet
from .test_datasource_fixes import TZ_TOKYO, make_dsec, mock_client, png_bytes

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=TZ_TOKYO)

class TestWords(unittest.TestCase):
	def test_a_day_is_named_as_the_api_does(self):
		self.assertEqual([day_id(date(2026, 10, 14)), day_id(date(1995, 6, 16))], ["261014", "950616"])

	def test_a_chosen_day_is_a_date_or_none_and_a_bad_one_is_a_settings_problem(self):
		self.assertIsNone(chosen_day({}))
		self.assertIsNone(chosen_day({ "customDate": "" }))
		self.assertEqual(chosen_day({ "customDate": "2020-02-29" }), date(2020, 2, 29))
		with self.assertRaises(PermanentError):
			chosen_day({ "customDate": "yesterday" })

	def test_a_random_day_is_between_the_first_picture_and_yesterday(self):
		days = [random_day(date(2026, 10, 14)) for _ in range(300)]
		self.assertTrue(all(apod.FIRST_DAY <= d < date(2026, 10, 14) for d in days))

	def test_only_a_picture_with_an_image_address_is_kept(self):
		self.assertEqual(picture_of({ "date": "2026-10-13", "title": "Mars &amp; Bees", "media_type": "image", "hdurl": "https://a.example/b.jpg" }),
			{ "date": "2026-10-13", "title": "Mars & Bees", "url": "https://a.example/b.jpg" })
		for bad in ({ "media_type": "video", "hdurl": "https://a.example/b.jpg" }, { "media_type": "image" }, { "media_type": "image", "hdurl": "http://a.example/b.jpg" }, "x", None):
			self.assertIsNone(picture_of(bad))

class TestOpen(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	def asked(self) -> list[str]:
		return [r.url.path.rsplit("/", 1)[-1] for r in self.fake.requests]

	async def test_today_is_the_latest_picture_and_a_video_is_passed_over(self):
		[item] = await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), {})
		# the newest day of the fixture is a video: the one before it is shown
		self.assertEqual((item["date"], item["title"]), ("2026-10-13", "Mars and the Beehive & an Aurora"))
		self.assertTrue(item["url"].startswith("https://assets.science.nasa.gov/"))
		self.assertEqual(self.asked(), ["apod-basic"])

	async def test_a_chosen_day_is_asked_for_by_its_id(self):
		[item] = await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), { "customDate": "2020-02-29" })
		self.assertEqual((item["date"], self.asked()), ("2020-02-29", ["200229"]))

	async def test_a_chosen_day_with_no_picture_says_so(self):
		client_var.set(mock_client(lambda request: httpx.Response(404, json={ "code": "rest_post_invalid_id" })))
		with self.assertRaisesRegex(PermanentError, "no Picture of the Day for 2020-10-10"):
			await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), { "customDate": "2020-10-10" })

	async def test_a_chosen_day_with_a_video_says_so(self):
		client_var.set(mock_client(lambda request: httpx.Response(200, json={ "date": "2020-10-10", "media_type": "video", "url": "https://x.example/v" })))
		with self.assertRaisesRegex(PermanentError, "not a picture"):
			await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), { "customDate": "2020-10-10" })

	async def test_a_random_day_is_tried_again_when_it_has_no_picture(self):
		answers = iter([404, 404, 200])
		def handler(request: httpx.Request) -> httpx.Response:
			if next(answers) == 404:
				return httpx.Response(404, json={ "code": "rest_post_invalid_id" })
			return httpx.Response(200, json={ "date": "2010-01-01", "title": "T", "media_type": "image", "hdurl": "https://assets.science.nasa.gov/p.jpg" })
		client_var.set(mock_client(handler))
		[item] = await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), { "randomizeDate": True, "customDate": "2020-02-29" })
		self.assertEqual(item["date"], "2010-01-01")
		# after the tries it gives up, in our words
		client_var.set(mock_client(lambda request: httpx.Response(404, json={})))
		with self.assertRaisesRegex(RuntimeError, "no picture for a random day after 6 tries"):
			await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), { "randomizeDate": True })

	async def test_nasa_failing_is_worded_without_the_address(self):
		client_var.set(mock_client(lambda request: httpx.Response(503)))
		with self.assertLogs(apod.__name__, level="ERROR"), self.assertRaises(RuntimeError) as raised:
			await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), {})
		self.assertNotIn("nasa.gov", str(raised.exception))

	async def test_a_latest_list_without_a_picture_is_an_error(self):
		client_var.set(mock_client(lambda request: httpx.Response(200, json=[{ "media_type": "video" }])))
		with self.assertRaisesRegex(RuntimeError, "no picture in NASA's latest"):
			await ApodAsync("apod", "APOD").open_async(make_dsec(ts=NOW), {})

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))

	async def test_the_picture_fits_the_screen_with_a_blurred_margin_and_a_portrait_screen_is_swapped(self):
		ds = ApodAsync("apod", "APOD")
		[item] = await ds.open_async(make_dsec(ts=NOW), {})
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
			result = await ds.render_async(make_dsec(orientation, ts=NOW), {}, item)
			assert result is not None
			self.assertEqual(result.image.size, size)
			self.assertIn("Mars and the Beehive", result.title or "")
		self.assertNotEqual(result.image.getpixel((2, 2)), (255, 255, 255), "the margin is the picture's own color, not white")

	async def test_nothing_to_render_without_a_state(self):
		self.assertIsNone(await ApodAsync("apod", "APOD").render_async(make_dsec(), {}, None))
		self.assertIsNone(await ApodAsync("apod", "APOD").render_async(make_dsec(), {}, { "title": "x" }))

	async def test_a_download_that_is_too_big_or_not_a_picture_is_worded(self):
		state = { "date": "2026-10-13", "title": "T", "url": "https://assets.science.nasa.gov/p.jpg" }
		client_var.set(mock_client(lambda request: httpx.Response(200, content=b"x" * 5000, headers={ "Content-Type": "image/jpeg" })))
		with patch.object(apod, "MAX_IMAGE_BYTES", 1000), self.assertLogs(apod.__name__, level="ERROR"), self.assertRaisesRegex(RuntimeError, "could not load the picture"):
			await ApodAsync("apod", "APOD").render_async(make_dsec(ts=NOW), {}, state)
		client_var.set(mock_client(lambda request: httpx.Response(200, content=b"<html>", headers={ "Content-Type": "text/html" })))
		with self.assertLogs(apod.__name__, level="ERROR"), self.assertRaisesRegex(RuntimeError, "could not load the picture"):
			await ApodAsync("apod", "APOD").render_async(make_dsec(ts=NOW), {}, state)
		client_var.set(mock_client(lambda request: httpx.Response(200, content=png_bytes((40, 30)), headers={ "Content-Type": "image/png" })))
		result = await ApodAsync("apod", "APOD").render_async(make_dsec(ts=NOW), {}, state)
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))

if __name__ == "__main__":
	unittest.main()
