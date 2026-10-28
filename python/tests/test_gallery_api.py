"""
The Gallery's routes (#238): list, show, pin, remove, add a picture, keep one the panel showed, and what each tells the web app.

Run through the real application (`WebApiTestBase`): its token, its errors and its OpenAPI document are the ones a browser meets.
"""
import hashlib
import io
import unittest
from datetime import datetime, timezone

from PIL import Image

from ..datasources.ai import generate as generate_module
from ..datasources.gallery.gallery import encode
from ..datasources.gallery.offer import GALLERY_ID
from ..datasources.gallery.store import PREFIX, GalleryStore
from ..model.service_container import ServiceContainer
from ..task.messages import Telemetry
from ..task.telemetry_hub import TelemetryHub
from .test_web_api import WebApiTestBase

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
BASE = f"/api/datasource/{GALLERY_ID}"

def picture(color: str = "red", size=(64, 48), fmt: str = "PNG") -> bytes:
	out = io.BytesIO()
	Image.new("RGB", size, color).save(out, fmt)
	return out.getvalue()

class GalleryApiBase(WebApiTestBase):
	def setUp(self):
		super().setUp()
		# the hub the web app asks for what the panel showed, and tells what changed (the application makes it at start)
		self.hub = TelemetryHub()
		root = self.app.state.root_container
		assert isinstance(root, ServiceContainer)
		root.add_service(TelemetryHub, self.hub)
		self.store = GalleryStore(self.cm.datasource_manager(GALLERY_ID))

	def keep(self, color: str = "red", **meta) -> str:
		data = encode(Image.new("RGB", (64, 48), color))
		self.store.keep(data, { "title": color, "origin": "ai-image", "width": 64, "height": 48, **meta }, NOW, 100, 10 ** 9)
		return self.store.items()[0]["id"]

	def told(self) -> list[str]:
		return [e["kind"] for e in self.hub.since(0) if str(e["kind"]).startswith("gallery-")]

class TestListing(GalleryApiBase):
	def test_an_empty_gallery_lists_nothing_with_its_limits(self):
		body = self.client.get(f"{BASE}/items").json()
		self.assertEqual(body, { "items": [], "count": 0, "bytes": 0, "maxPictures": 200, "maxBytes": 512 * 1024 * 1024 })

	def test_the_pictures_are_listed_newest_first_with_what_is_known_of_each(self):
		first, second = self.keep("red", prompt="a red cat"), self.keep("blue")
		body = self.client.get(f"{BASE}/items").json()
		self.assertEqual([i["id"] for i in body["items"]], [second, first])
		self.assertEqual(body["count"], 2)
		self.assertEqual(body["bytes"], sum(i["size"] for i in body["items"]))
		item = body["items"][1]
		self.assertEqual((item["title"], item["origin"], item["prompt"], item["pinned"], item["width"]), ("red", "ai-image", "a red cat", False, 64))

	def test_the_limits_are_the_settings(self):
		self.write_datasource_settings(GALLERY_ID, { "_schema": "urn:inky:storage:schema:datasource:gallery:1", "maxPictures": 7, "maxMB": 2 })
		body = self.client.get(f"{BASE}/items").json()
		self.assertEqual((body["maxPictures"], body["maxBytes"]), (7, 2 * 1024 * 1024))

class TestImage(GalleryApiBase):
	def test_a_picture_comes_back_whole_or_as_a_small_one_and_may_be_kept_for_ever(self):
		item_id = self.keep("red")
		full = self.client.get(f"{BASE}/items/{item_id}/image?size=full")
		self.assertEqual((full.status_code, full.headers["content-type"]), (200, "image/jpeg"))
		self.assertIn("immutable", full.headers["cache-control"])
		self.assertEqual(self.store.read(item_id), full.content)
		self.assertEqual(Image.open(io.BytesIO(full.content)).size, (64, 48))
		# a bigger picture, for a thumbnail that is smaller
		data = encode(Image.new("RGB", (1200, 800), "white"))
		self.store.keep(data, { "title": "big" }, NOW, 100, 10 ** 9)
		big = self.store.items()[0]["id"]
		thumb = self.client.get(f"{BASE}/items/{big}/image")
		self.assertEqual(max(Image.open(io.BytesIO(thumb.content)).size), 320)
		self.assertLess(len(thumb.content), len(self.client.get(f"{BASE}/items/{big}/image?size=full").content))

	def test_an_id_that_is_not_there_or_not_an_id_is_a_404_that_does_not_echo_it(self):
		for item_id in ("0" * 32, "../../settings/system-settings", "A" * 32, "abc"):
			with self.subTest(item_id=item_id):
				response = self.client.get(f"{BASE}/items/{item_id}/image")
				self.assertIn(response.status_code, (404,))
				self.assertNotIn("settings", response.text)
				self.assertEqual(response.json()["success"], False)

	def test_a_size_that_is_neither_is_refused(self):
		self.assertEqual(self.client.get(f"{BASE}/items/{self.keep()}/image?size=huge").status_code, 422)

class TestChanges(GalleryApiBase):
	def test_a_picture_is_pinned_and_unpinned_and_the_web_app_is_told(self):
		item_id = self.keep()
		self.assertEqual(self.client.put(f"{BASE}/items/{item_id}/pin", json={ "pinned": True }).json(), { "success": True })
		self.assertTrue(self.store.items()[0]["pinned"])
		self.client.put(f"{BASE}/items/{item_id}/pin", json={ "pinned": False })
		self.assertFalse(self.store.items()[0]["pinned"])
		self.assertEqual(self.told(), ["gallery-pinned", "gallery-pinned"])

	def test_pinning_needs_a_yes_or_no_and_a_picture(self):
		item_id = self.keep()
		self.assertEqual(self.client.put(f"{BASE}/items/{item_id}/pin", json={ "pinned": "yes" }).status_code, 422)
		self.assertEqual(self.client.put(f"{BASE}/items/{'0' * 32}/pin", json={ "pinned": True }).status_code, 404)
		self.assertEqual(self.told(), [])

	def test_a_picture_is_removed_with_its_file_and_the_web_app_is_told(self):
		item_id = self.keep()
		self.assertEqual(self.client.delete(f"{BASE}/items/{item_id}").json(), { "success": True })
		self.assertEqual(self.store.items(), [])
		self.assertEqual(self.cm.datasource_manager(GALLERY_ID).list_blobs(PREFIX), [])
		self.assertEqual(self.client.delete(f"{BASE}/items/{item_id}").status_code, 404)
		self.assertEqual(self.told(), ["gallery-removed"])

class TestAdding(GalleryApiBase):
	def add(self, data: bytes, query: str = "", content_type: str = "image/png"):
		return self.client.post(f"{BASE}/items{query}", content=data, headers={ "Content-Type": content_type })

	def test_a_picture_from_the_person_is_kept_whole_under_its_title_and_told(self):
		response = self.add(picture("red", (400, 300)), "?title=My%20cat")
		body = response.json()
		self.assertEqual((response.status_code, body["success"], body["kept"]), (200, True, True))
		[item] = self.store.items()
		self.assertEqual((item["id"], item["title"], item["origin"], item["width"], item["height"], item["pinned"]), (body["id"], "My cat", "upload", 400, 300, False))
		self.assertEqual(self.told(), ["gallery-kept"])

	def test_the_same_picture_twice_is_said_to_be_there_already_and_told_once(self):
		self.add(picture("red"))
		again = self.add(picture("red")).json()
		self.assertEqual((again["kept"], again["success"]), (False, True))
		self.assertEqual((len(self.store.items()), self.told()), (1, ["gallery-kept"]))

	def test_what_is_not_a_picture_is_refused_in_words_and_nothing_is_kept(self):
		for data, status in ((b"", 422), (b"not a picture at all", 415), (b"GIF89a" + b"\x00" * 4, 415), (picture("red", (300, 300))[:80], 422)):
			with self.subTest(data=data[:10]):
				self.assertEqual(self.add(data).status_code, status)
		self.assertEqual((self.store.items(), self.told()), ([], []))

	def test_a_body_larger_than_a_picture_may_be_is_refused_before_it_is_read(self):
		from ..utils.upload_image import MAX_UPLOAD_BYTES
		response = self.client.post(f"{BASE}/items", content=b"x", headers={ "Content-Length": str(MAX_UPLOAD_BYTES + 1), "Content-Type": "image/png" })
		self.assertEqual(response.status_code, 413)

	def test_going_over_the_limits_removes_the_oldest_and_says_so(self):
		self.write_datasource_settings(GALLERY_ID, { "_schema": "urn:inky:storage:schema:datasource:gallery:1", "maxPictures": 1, "maxMB": 512 })
		self.add(picture("red"))
		self.add(picture("blue"))
		self.assertEqual(len(self.store.items()), 1)
		self.assertEqual(self.told(), ["gallery-kept", "gallery-kept", "gallery-evicted"])
		# each says which routes changed, so the web app's cache asks for the list again
		for e in self.hub.since(0):
			if str(e["kind"]).startswith("gallery-"):
				self.assertEqual(e["values"]["changed"], ["/api/datasource/gallery"])

	def test_a_picture_bigger_than_the_whole_pool_is_refused(self):
		self.write_datasource_settings(GALLERY_ID, { "_schema": "urn:inky:storage:schema:datasource:gallery:1", "maxPictures": 10, "maxMB": 0.000001 })
		self.assertEqual(self.add(picture("red", (200, 200))).status_code, 413)

class TestSavingWhatWasShown(GalleryApiBase):
	def shown(self, color: str = "red") -> str:
		"""What the panel showed, as the hub keeps it (the digest names it)."""
		image = Image.new("RGB", (80, 60), color)
		digest = hashlib.sha256(image.tobytes()).hexdigest()
		self.hub.accept(Telemetry(NOW, "display", { "kind": "shown", "title": "A shown page", "digest": digest, "image": image }))
		return digest

	def test_a_shown_picture_is_kept_as_it_was_shown(self):
		digest = self.shown()
		response = self.client.post(f"{BASE}/items/from-display", json={ "digest": digest, "title": "Nice one" })
		self.assertEqual((response.status_code, response.json()["kept"]), (200, True))
		[item] = self.store.items()
		self.assertEqual((item["title"], item["origin"], item["width"], item["height"]), ("Nice one", "display", 80, 60))

	def test_it_is_a_picture_the_device_still_has_and_a_digest_or_it_is_refused(self):
		self.assertEqual(self.client.post(f"{BASE}/items/from-display", json={ "digest": "0" * 64 }).status_code, 404)
		for body in ({ "digest": "../etc" }, { "digest": 5 }, {}, { "digest": "0" * 64, "title": 3 }):
			with self.subTest(body=body):
				self.assertEqual(self.client.post(f"{BASE}/items/from-display", json=body).status_code, 422)
		self.assertEqual(self.store.items(), [])

class TestProducerSwitch(unittest.TestCase):
	"""A task says whether its pictures are kept (`keepInGallery`, default on): the producer offers them unless the task says no."""
	def run_generate(self, params: dict) -> list:
		import asyncio
		from unittest.mock import MagicMock
		from .test_datasource_fixes import make_dsec
		image_source = MagicMock()
		async def open_async(dsec, p):
			return Image.new("RGB", (64, 64), "red")
		image_source.open_async = open_async
		dsec = make_dsec()
		dsec.use = lambda source_id, kind: (image_source, dsec)  # type: ignore[method-assign]
		offers: list = []
		original = generate_module.offer_to_gallery
		generate_module.offer_to_gallery = lambda *args: offers.append(args)
		self.addCleanup(setattr, generate_module, "offer_to_gallery", original)
		asyncio.run(generate_module.generate(dsec, { "imageSource": "openai-image", **params }, "a cat", "Generated Image", "ai-image"))
		return offers

	def test_it_is_offered_unless_the_task_says_not_to(self):
		self.assertEqual(len(self.run_generate({})), 1)
		self.assertEqual(len(self.run_generate({ "keepInGallery": True })), 1)
		self.assertEqual(self.run_generate({ "keepInGallery": False }), [])

	def test_both_paid_pictures_have_the_switch_and_it_is_on(self):
		from ..model.configuration_manager import ConfigurationManager
		for info in ConfigurationManager().enum_datasources():
			if info["info"]["id"] in ("ai-image", "weather-image"):
				prop = next(p for p in info["info"]["instanceSettings"]["schema"]["properties"] if p["name"] == "keepInGallery")
				self.assertEqual((prop["type"], prop["default"]), ("boolean", True), info["info"]["id"])
