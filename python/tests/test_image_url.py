"""
The Image from a Web Address data source (#367): one picture from an address, fetched each time it is shown, through the URL guard, treated as untrusted, and fitted to the panel on a blurred margin.
Its Test button asks the same question the data source does.
"""
import unittest
from datetime import datetime
from typing import Any, cast
from unittest.mock import patch

import httpx

from ..datasources.image_url import image_url
from ..datasources.image_url.image_url import ImageUrlAsync, address_of, picture_address, picture_content_type
from ..model.configuration_manager import DatasourceConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool, client_var
from ..utils import url_guard
from ..utils.upload_image import MAX_UPLOAD_BYTES
from .fake_internet import FakeInternet
from .test_datasource_fixes import TZ_TOKYO, FakeDatasourceSettings, make_dsec
from .test_web_api import WebApiTestBase

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=TZ_TOKYO)
CAMERA = "https://camera.example.test"
PUBLIC = "93.184.216.34"

def pictures_dsec(pictures: list, **kw):
	"""A context whose data source has these pictures in its settings (as a user typed them once, in the data source's settings)."""
	dsec = make_dsec(**kw)
	dsec.provider.add_service(DatasourceConfigurationManager, cast(Any, FakeDatasourceSettings({ "pictures": pictures })))  # type: ignore[attr-defined]
	return dsec

class TestAddress(unittest.TestCase):
	def test_an_address_is_taken_as_typed_without_the_spaces_round_it(self):
		self.assertEqual(address_of("  https://camera.example.test/snapshot.jpg "), "https://camera.example.test/snapshot.jpg")

	def test_no_address_and_no_scheme_are_settings_problems_with_what_to_do(self):
		for url in (None, "", "   ", 7):
			with self.subTest(url), self.assertRaisesRegex(PermanentError, "Enter the picture"):
				address_of(url)
		for url in ("ftp://camera.example.test/a.jpg", "file:///etc/passwd", "camera.example.test/a.jpg", "javascript:alert(1)"):
			with self.subTest(url), self.assertRaisesRegex(PermanentError, "http://"):
				address_of(url)

	def test_a_task_names_the_picture_and_the_address_comes_from_the_data_sources_settings(self):
		dsec = pictures_dsec([{ "name": "Garage", "url": "https://camera.example.test/garage.jpg" }, { "name": "Gate", "url": " https://camera.example.test/gate.jpg " }])
		self.assertEqual(picture_address(dsec, "Garage"), "https://camera.example.test/garage.jpg")
		self.assertEqual(picture_address(dsec, "Gate"), "https://camera.example.test/gate.jpg")

	def test_no_picture_chosen_one_that_is_gone_or_one_with_no_web_address_are_settings_problems(self):
		dsec = pictures_dsec([{ "name": "Garage", "url": "https://camera.example.test/garage.jpg" }, { "name": "Odd", "url": "file:///etc/passwd" }])
		for name in (None, "", 7):
			with self.subTest(name), self.assertRaisesRegex(PermanentError, "Choose the picture"):
				picture_address(dsec, name)
		with self.assertRaisesRegex(PermanentError, "'Roof' is not in"):
			picture_address(dsec, "Roof")
		with self.assertRaisesRegex(PermanentError, "http://"):
			picture_address(dsec, "Odd")
		with self.assertRaisesRegex(PermanentError, "'Garage' is not in"):
			picture_address(pictures_dsec([]), "Garage")

	def test_a_server_that_does_not_say_what_it_sends_is_not_refused_for_it(self):
		for content_type in ("image/jpeg", "IMAGE/PNG; charset=binary", "application/octet-stream", "", "  "):
			with self.subTest(content_type):
				self.assertTrue(picture_content_type(content_type))
		for content_type in ("text/html", "application/json", "text/plain; charset=utf-8"):
			with self.subTest(content_type):
				self.assertFalse(picture_content_type(content_type))

class TestPicture(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))
		# the fake hosts have no DNS: the URL guard is given a public address (see fake_internet.install)
		async def public(host: str, port: int) -> list[str]:
			return [PUBLIC]
		patcher = patch.object(url_guard, "_resolve", public)
		patcher.start()
		self.addCleanup(patcher.stop)

	async def show(self, path: str, size=(800, 480), orientation="landscape", **params):
		source = ImageUrlAsync("image-url", "Image from a Web Address")
		dsec = pictures_dsec([{ "name": "Camera", "url": f"{CAMERA}{path}" }], orientation=orientation, dimensions=size, ts=NOW)
		[item] = await source.open_async(dsec, { "picture": "Camera", **params })
		return await source.render_async(dsec, { "picture": "Camera", **params }, item)

	async def test_a_picture_is_shown_whole_on_a_margin_of_its_own_colors(self):
		result = await self.show("/snapshot.jpg")
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))
		self.assertEqual(result.title, "Picture from camera.example.test")
		# the picture is 16:9 on a 5:3 panel: nothing is white, the margin is the picture's own
		self.assertNotEqual(result.image.convert("RGB").getpixel((400, 2)), (255, 255, 255))

	async def test_a_portrait_picture_on_a_landscape_panel_is_not_cropped(self):
		result = await self.show("/portrait.png")
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))
		# the middle column is the picture's own gradient, the sides are blurred copies of it, so no white bars
		self.assertNotEqual(result.image.convert("RGB").getpixel((2, 240)), (255, 255, 255))

	async def test_the_size_is_swapped_for_a_portrait_panel(self):
		result = await self.show("/snapshot.jpg", orientation="portrait")
		assert result is not None
		self.assertEqual(result.image.size, (480, 800))

	async def test_a_small_picture_is_not_enlarged_but_still_fills_the_panel(self):
		result = await self.show("/octet")
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))

	async def test_without_shrink_to_fit_the_picture_is_given_as_it_is(self):
		result = await self.show("/snapshot.jpg", shrinkToFit=False)
		assert result is not None
		self.assertEqual(result.image.size, (1280, 720))

	async def test_a_camera_that_sends_no_content_type_or_octet_stream_works(self):
		for path in ("/octet", "/anonymous"):
			with self.subTest(path):
				self.assertIsNotNone(await self.show(path))

	async def test_only_the_first_frame_of_an_animation_is_used(self):
		result = await self.show("/animated.gif", shrinkToFit=False)
		assert result is not None
		self.assertGreater(result.image.convert("RGB").getpixel((10, 10))[0], 200)

	async def test_it_is_fetched_every_time_it_is_shown(self):
		await self.show("/snapshot.jpg")
		await self.show("/snapshot.jpg")
		self.assertEqual([r.url.path for r in self.fake.requests], ["/snapshot.jpg", "/snapshot.jpg"])

	async def test_nothing_to_render_is_nothing(self):
		source = ImageUrlAsync("image-url", "Image from a Web Address")
		self.assertIsNone(await source.render_async(make_dsec(ts=NOW), {}, None))

class TestWhatCanGoWrong(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))
		self.names: dict[str, list[str]] = {}
		async def resolve(host: str, port: int) -> list[str]:
			return self.names.get(host, [PUBLIC])
		patcher = patch.object(url_guard, "_resolve", resolve)
		patcher.start()
		self.addCleanup(patcher.stop)

	async def show(self, url: str):
		source = ImageUrlAsync("image-url", "Image from a Web Address")
		dsec = pictures_dsec([{ "name": "Camera", "url": url }], ts=NOW)
		[item] = await source.open_async(dsec, { "picture": "Camera" })
		return await source.render_async(dsec, { "picture": "Camera" }, item)

	async def test_an_address_on_this_device_is_refused_for_good_in_our_words(self):
		self.names["inside.example.test"] = ["127.0.0.1"]
		with self.assertRaises(PermanentError) as caught:
			await self.show("https://inside.example.test/snapshot.jpg")
		self.assertNotIn("inside.example.test", str(caught.exception), "the address is not repeated")
		self.assertEqual(self.fake.requests, [], "nothing was asked")

	async def test_the_metadata_address_is_refused(self):
		with self.assertRaises(PermanentError):
			await self.show("http://169.254.169.254/latest/meta-data/")

	async def test_a_page_that_is_not_a_picture_says_so_without_the_address(self):
		with self.assertRaises(RuntimeError) as caught:
			await self.show(f"{CAMERA}/page")
		self.assertIn("not a picture", str(caught.exception))
		self.assertNotIn("camera.example.test", str(caught.exception))

	async def test_a_server_error_is_a_failure_of_the_slot_not_a_settings_problem(self):
		with self.assertRaises(httpx.HTTPStatusError):
			await self.show(f"{CAMERA}/forbidden")

	async def test_a_picture_that_is_too_large_is_refused(self):
		with patch.object(image_url, "MAX_IMAGE_BYTES", 500), self.assertRaisesRegex(RuntimeError, "too large"):
			await self.show(f"{CAMERA}/snapshot.jpg")

	async def test_a_small_file_that_holds_a_huge_picture_is_refused_before_it_is_decoded(self):
		with self.assertRaisesRegex(RuntimeError, "million pixels"):
			await self.show(f"{CAMERA}/huge.png")

	async def test_something_that_is_not_an_image_at_all_is_refused_by_its_content(self):
		def handler(request: httpx.Request) -> httpx.Response:
			return httpx.Response(200, content=b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", headers={ "Content-Type": "image/svg+xml" })
		client_var.set(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
		with self.assertRaisesRegex(RuntimeError, "not a picture the device can use"):
			await self.show(f"{CAMERA}/anything.svg")

class TestTestRoute(WebApiTestBase):
	"""What the Test button asks: can the server fetch this address and read it as a picture?"""
	URL = "/api/datasource/image-url/test"

	def setUp(self):
		super().setUp()
		names = { "camera.example.test": [PUBLIC], "inside.example.test": ["127.0.0.1"] }
		async def resolve(host: str, port: int) -> list[str]:
			if host not in names:
				raise OSError("no such host")
			return names[host]
		patcher = patch.object(url_guard, "_resolve", resolve)
		patcher.start()
		self.addCleanup(patcher.stop)

	def ask(self, value, transport=None) -> dict:
		"""POST the question; the answer is always 200 with `{ ok, message }`. `transport` replaces the fake internet."""
		with patch.object(AsyncHttpWorkerPool, "default_transport", transport or AsyncHttpWorkerPool.default_transport):
			resp = self.client.post(self.URL, json={ "value": value })
		self.assertEqual(resp.status_code, 200, resp.text)
		answer = resp.json()
		self.assertEqual(sorted(answer), ["message", "ok"])
		return answer

	def test_a_picture_is_measured_and_named(self):
		self.assertEqual(self.ask(f"{CAMERA}/snapshot.jpg"), { "ok": True, "message": "A 1280 x 720 JPEG picture." })
		self.assertEqual(self.ask(f"{CAMERA}/portrait.png"), { "ok": True, "message": "A 300 x 600 PNG picture." })
		self.assertEqual(self.ask(f"{CAMERA}/octet")["ok"], True)

	def test_nothing_typed_is_a_no(self):
		for value in ("", "   ", None, 7):
			self.assertEqual(self.ask(value), { "ok": False, "message": "Enter an address first." })

	def test_a_page_that_is_no_picture_is_a_no(self):
		answer = self.ask(f"{CAMERA}/page")
		self.assertFalse(answer["ok"])
		self.assertIn("not a picture", answer["message"])

	def test_an_address_on_this_device_is_refused_and_not_repeated(self):
		answer = self.ask("https://inside.example.test/snapshot.jpg")
		self.assertFalse(answer["ok"])
		self.assertNotIn("inside.example.test", answer["message"])

	def test_what_can_go_wrong_is_told_in_words_and_never_holds_the_address(self):
		def status(code):
			return httpx.MockTransport(lambda r: httpx.Response(code))
		def raises(exc):
			def handler(request):
				raise exc
			return httpx.MockTransport(handler)
		url = f"{CAMERA}/snapshot.jpg?key=SECRET"
		self.assertEqual(self.ask(url, status(404))["message"], "The server answered 404.")
		self.assertEqual(self.ask(url, raises(httpx.ReadTimeout("slow")))["message"], "The server did not answer in time.")
		self.assertEqual(self.ask(url, raises(httpx.ConnectError("refused")))["message"], "Could not connect to the server.")
		self.assertEqual(self.ask(url, raises(httpx.DecodingError("bad")))["message"], "The request failed (DecodingError).")
		self.assertIn("too large", self.ask(url, httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (MAX_UPLOAD_BYTES + 1))))["message"])
		for transport in (status(500), raises(httpx.ConnectError("https://camera.example.test/?key=SECRET"))):
			self.assertNotIn("SECRET", self.ask(url, transport)["message"])

	def test_the_huge_picture_is_a_no_and_is_not_decoded(self):
		answer = self.ask(f"{CAMERA}/huge.png")
		self.assertFalse(answer["ok"])
		self.assertIn("million pixels", answer["message"])

	def test_the_descriptor_names_the_route_and_it_exists(self):
		info = next(d["info"] for d in self.cm.enum_datasources() if d["info"]["id"] == "image-url")
		pictures = next(p for p in info["settings"]["schema"]["properties"] if p["name"] == "pictures")
		url_field = next(p for p in pictures["items"]["properties"] if p["name"] == "url")
		self.assertEqual(url_field["test"]["url"], self.URL)
		self.assertEqual(self.client.post(self.URL, json={ "value": "" }).status_code, 200)

if __name__ == "__main__":
	unittest.main()
