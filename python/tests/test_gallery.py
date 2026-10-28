"""
The Gallery (#238): the pictures a paid source drew, kept and shown again.

The store is tested on its own (the bounds, the pins, the index and the files that must agree, several threads at once), then the way a producer reaches it: an offer through the
`DataSourceManager`, kept in the background, told as telemetry, and shown as a list.
"""
import asyncio
import io
import threading
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from PIL import Image

from ..datasources.ai import generate as generate_module
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.gallery.gallery import GalleryAsync, encode
from ..datasources.gallery.offer import GALLERY_ID, GalleryOffer, offer_to_gallery
from ..datasources.gallery.store import INDEX, PREFIX, GalleryStore, picture_id
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, backup_file
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.message_router import MessageRouter
from .test_datasource_fixes import make_dsec
from .utils import temp_configuration_manager

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)

def jpeg(color: str, size=(64, 48)) -> bytes:
	return encode(Image.new("RGB", size, color))

def files_of(dscm: DatasourceConfigurationManager) -> set[str]:
	return set(dscm.list_blobs(PREFIX))

class TestStore(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.dscm = self.cm.datasource_manager(GALLERY_ID)
		self.store = GalleryStore(self.dscm)

	def keep(self, data: bytes, pictures: int = 100, size: int = 10 ** 9, **meta):
		return self.store.keep(data, { "title": "t", "origin": "ai-image", **meta }, NOW, pictures, size)

	def test_a_picture_is_kept_by_what_is_in_it_and_listed_newest_first(self):
		first, second = jpeg("red"), jpeg("blue")
		self.assertTrue(self.keep(first, title="first").kept)
		self.assertTrue(self.keep(second, title="second").kept)
		self.assertEqual([i["title"] for i in self.store.items()], ["second", "first"])
		self.assertEqual(self.store.read(picture_id(first)), first)
		self.assertEqual(files_of(self.dscm), { PREFIX + picture_id(first), PREFIX + picture_id(second) })

	def test_the_same_picture_twice_is_one(self):
		data = jpeg("red")
		self.assertTrue(self.keep(data).kept)
		again = self.keep(data)
		self.assertEqual((again.kept, again.reason, again.count), (False, "duplicate", 1))
		self.assertEqual(len(self.store.items()), 1)

	def test_a_picture_bigger_than_the_pool_is_not_kept_and_nothing_is_left_of_it(self):
		data = jpeg("red")
		result = self.keep(data, size=len(data) - 1)
		self.assertEqual((result.kept, result.reason), (False, "too-big"))
		self.assertEqual((self.store.items(), files_of(self.dscm)), ([], set()))

	def test_the_oldest_unpinned_picture_goes_first_when_there_are_too_many(self):
		pictures = [jpeg(c) for c in ("red", "green", "blue")]
		for data in pictures:
			self.keep(data, pictures=2)
		self.assertEqual([i["id"] for i in self.store.items()], [picture_id(pictures[2]), picture_id(pictures[1])])
		self.assertEqual(files_of(self.dscm), { PREFIX + picture_id(pictures[1]), PREFIX + picture_id(pictures[2]) })

	def test_the_oldest_goes_first_when_the_pool_is_too_big_too(self):
		pictures = [jpeg(c, (200, 150)) for c in ("red", "green", "blue")]
		room = len(pictures[1]) + len(pictures[2]) + 10
		results = [self.keep(data, size=room) for data in pictures]
		self.assertEqual([r.evicted for r in results], [0, 0, 1])
		self.assertEqual([i["id"] for i in self.store.items()], [picture_id(pictures[2]), picture_id(pictures[1])])

	def test_a_pinned_picture_is_never_taken_by_the_bounds(self):
		old, newer, newest = jpeg("red"), jpeg("green"), jpeg("blue")
		self.keep(old)
		self.assertTrue(self.store.pin(picture_id(old), True))
		self.keep(newer, pictures=2)
		result = self.keep(newest, pictures=2)
		self.assertEqual(result.evicted, 1)
		self.assertEqual({ i["id"] for i in self.store.items() }, { picture_id(old), picture_id(newest) })

	def test_a_pool_of_pins_is_over_its_bounds_rather_than_losing_one_and_the_new_picture_stays(self):
		a, b, c = jpeg("red"), jpeg("green"), jpeg("blue")
		for data in (a, b):
			self.keep(data)
			self.assertTrue(self.store.pin(picture_id(data), True))
		result = self.keep(c, pictures=1)
		self.assertEqual((result.kept, result.evicted, result.count), (True, 0, 3))

	def test_pinning_and_removing_a_picture_that_is_not_there_says_so(self):
		self.assertFalse(self.store.pin("0" * 32, True))
		self.assertFalse(self.store.remove("0" * 32))
		self.assertIsNone(self.store.read("0" * 32))

	def test_removing_a_picture_takes_its_file_too(self):
		data = jpeg("red")
		self.keep(data)
		self.assertTrue(self.store.remove(picture_id(data)))
		self.assertEqual((self.store.items(), files_of(self.dscm), self.store.read(picture_id(data))), ([], set(), None))

	def test_a_file_the_index_does_not_list_is_swept_at_the_first_use(self):
		# a crash between the bytes and the index leaves exactly this
		self.dscm.write_blob(PREFIX + "f" * 32, b"orphan")
		self.assertTrue(self.keep(jpeg("red")).kept)
		self.assertNotIn(PREFIX + "f" * 32, files_of(self.dscm))

	def test_what_the_index_lists_is_always_there_and_nothing_else_is_with_many_threads(self):
		pictures = [jpeg(c, (30 + i, 30)) for i, c in enumerate(["red", "green", "blue", "white", "black", "yellow", "orange", "purple"] * 3)]
		pictures = list({ picture_id(p): p for p in pictures }.values())
		self.assertGreater(len(pictures), 10)
		gate = threading.Barrier(len(pictures))
		def work(data: bytes) -> None:
			# each thread has its own store and manager, as the two layers and the web app do: the one lock is the index's own object
			store = GalleryStore(self.cm.datasource_manager(GALLERY_ID))
			gate.wait()
			store.keep(data, { "title": "t", "origin": "x" }, NOW, 6, 10 ** 9)
		threads = [threading.Thread(target=work, args=(p,)) for p in pictures]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		listed = { i["id"] for i in self.store.items() }
		self.assertEqual(len(listed), 6)
		self.assertEqual(files_of(self.dscm), { PREFIX + i for i in listed })

	def test_a_backup_holds_none_of_it(self):
		self.keep(jpeg("red"))
		for name in (f"datasources/{GALLERY_ID}/{INDEX}.json", f"datasources/{GALLERY_ID}/{PREFIX}abc.json"):
			self.assertIsNone(backup_file(name), name)
		self.assertIsNotNone(backup_file(f"datasources/{GALLERY_ID}/settings.json"))

class GalleryTest(unittest.TestCase):
	"""A Gallery loaded as the layers load it, and a producer's context beside it."""
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.gallery = GalleryAsync(GALLERY_ID, "Gallery")
		self.manager = DataSourceManager({ GALLERY_ID: self.gallery })
		self.sent: list[Any] = []
		router = MagicMock(spec=MessageRouter)
		router.send.side_effect = lambda route, msg: self.sent.append((route, msg))
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(DataSourceManager, self.manager)
		root.add_service(MessageRouter, router)
		self.producer = DataSourceExecutionContext(root, (800, 480), NOW)
		self.store = GalleryStore(self.cm.datasource_manager(GALLERY_ID))

	def offer(self, color="red", title="Generated Image: a cat", prompt="a cat", origin="ai-image") -> Image.Image:
		image = Image.new("RGB", (64, 48), color)
		offer_to_gallery(self.producer, origin, image, title, prompt)
		self.gallery.flush()
		return image

class TestOffers(GalleryTest):
	def test_an_offer_is_kept_in_the_background_and_told(self):
		self.offer()
		[item] = self.store.items()
		self.assertEqual((item["title"], item["origin"], item["prompt"], item["width"], item["height"]), ("Generated Image: a cat", "ai-image", "a cat", 64, 48))
		[(route, event)] = self.sent
		self.assertEqual(route, "telemetry")
		self.assertEqual((event.name, event.values["kind"], event.values["datasource"], event.values["count"]), ("data-source", "gallery-kept", "ai-image", 1))
		self.assertEqual(event.values["bytes"], item["size"])
		self.assertNotIn("a cat", str(event.values), "no prompt in telemetry")

	def test_the_picture_is_copied_so_the_producer_may_change_its_own(self):
		image = Image.new("RGB", (64, 48), "red")
		offer_to_gallery(self.producer, "ai-image", image, "t", None)
		image.paste("blue", (0, 0, 64, 48))
		self.gallery.flush()
		[item] = self.store.items()
		kept = Image.open(io.BytesIO(self.store.read(item["id"]) or b"")).convert("RGB")
		self.assertGreater(kept.getpixel((10, 10))[0], 200)

	def test_the_same_offer_twice_is_told_once(self):
		self.offer()
		self.offer()
		self.assertEqual(len(self.store.items()), 1)
		self.assertEqual(len(self.sent), 1)

	def test_going_over_the_limits_is_told_as_an_eviction(self):
		dscm = self.cm.datasource_manager(GALLERY_ID)
		cob = dscm.open()
		rev, _ = cob.get()
		cob.save(rev, { "maxPictures": 1, "maxMB": 512 })
		self.offer("red")
		self.offer("green")
		self.assertEqual(len(self.store.items()), 1)
		self.assertEqual([e.values["kind"] for _, e in self.sent], ["gallery-kept", "gallery-kept", "gallery-evicted"])

	def test_a_gallery_that_is_not_loaded_drops_the_offer_and_nothing_fails(self):
		self.manager.sources = {}
		offer_to_gallery(self.producer, "ai-image", Image.new("RGB", (8, 8)), "t", None)
		self.gallery.flush()
		self.assertEqual((self.store.items(), self.sent), ([], []))
		# nor does a producer with no manager at all
		offer_to_gallery(DataSourceExecutionContext(ServiceContainer(), (800, 480), NOW), "ai-image", Image.new("RGB", (8, 8)), "t", None)

	def test_an_offer_that_cannot_be_kept_is_a_log_line_and_the_worker_goes_on(self):
		bad = GalleryOffer(GALLERY_ID, self.producer, "x", None, "t")  # type: ignore[arg-type]
		self.gallery.accept(bad)
		self.gallery.flush()
		self.offer("blue")
		self.assertEqual(len(self.store.items()), 1)

	def test_a_message_that_is_not_an_offer_is_not_for_it(self):
		self.gallery.accept(MagicMock())
		self.gallery.flush()
		self.assertEqual(self.store.items(), [])

class TestShowing(GalleryTest):
	def run_async(self, coroutine):
		return asyncio.run(coroutine)

	def context(self) -> DataSourceExecutionContext:
		return self.producer.context_for(self.gallery)

	def test_an_empty_gallery_says_so_in_words_that_say_what_to_do(self):
		with self.assertRaises(PermanentError) as caught:
			self.run_async(self.gallery.open_async(self.context(), {}))
		self.assertIn("no pictures yet", str(caught.exception))
		with self.assertRaises(PermanentError) as caught:
			self.run_async(self.gallery.open_async(self.context(), { "pinnedOnly": True }))
		self.assertIn("no pinned", str(caught.exception))

	def test_the_list_is_the_pictures_newest_first_when_asked_and_pinned_only_when_asked(self):
		self.offer("red", "one")
		self.offer("green", "two")
		self.offer("blue", "three")
		newest = self.run_async(self.gallery.open_async(self.context(), { "order": "Newest first" }))
		self.assertEqual([i["title"] for i in newest], ["three", "two", "one"])
		self.assertTrue(self.store.pin(newest[1]["id"], True))
		pinned = self.run_async(self.gallery.open_async(self.context(), { "order": "Newest first", "pinnedOnly": True }))
		self.assertEqual([i["title"] for i in pinned], ["two"])
		shuffled = self.run_async(self.gallery.open_async(self.context(), {}))
		self.assertEqual(sorted(i["title"] for i in shuffled), ["one", "three", "two"])

	def test_a_picture_is_shown_fitted_to_the_panel_as_a_background(self):
		self.offer("red", "a red one")
		[item] = self.run_async(self.gallery.open_async(self.context(), {}))
		dsec = make_dsec()
		dsec.provider.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(GALLERY_ID))  # type: ignore[attr-defined]
		result = self.run_async(self.gallery.render_async(dsec, {}, item))
		assert result is not None
		self.assertEqual((result.image.size, result.title, result.layer), ((800, 480), "a red one", "background"))

	def test_a_picture_removed_after_the_list_was_made_is_nothing_to_show(self):
		self.offer("red")
		[item] = self.run_async(self.gallery.open_async(self.context(), {}))
		self.store.remove(item["id"])
		dsec = make_dsec()
		dsec.provider.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(GALLERY_ID))  # type: ignore[attr-defined]
		self.assertIsNone(self.run_async(self.gallery.render_async(dsec, {}, item)))
		self.assertIsNone(self.run_async(self.gallery.render_async(dsec, {}, None)))
		self.assertIsNone(self.run_async(self.gallery.render_async(dsec, {}, { "id": 3 })))

class TestGenerateOffers(unittest.TestCase):
	def test_a_generated_picture_is_offered_as_drawn_and_not_as_fitted(self):
		drawn = Image.new("RGB", (1024, 1024), "red")
		image_source = MagicMock()
		async def open_async(dsec, params):
			return drawn
		image_source.open_async = open_async
		dsec = make_dsec()
		offers: list[Any] = []
		original = generate_module.offer_to_gallery
		generate_module.offer_to_gallery = lambda *args: offers.append(args)
		self.addCleanup(setattr, generate_module, "offer_to_gallery", original)
		dsec.use = lambda source_id, kind: (image_source, dsec)  # type: ignore[method-assign]
		result = asyncio.run(generate_module.generate(dsec, { "imageSource": "openai-image" }, "a cat", "Generated Image", "ai-image"))
		[(offered_dsec, origin, picture, title, prompt)] = offers
		self.assertEqual((origin, picture.size, title, prompt), ("ai-image", (1024, 1024), "Generated Image: a cat", "a cat"))
		self.assertEqual(result.title, "Generated Image: a cat")
		self.assertEqual(result.image.size, (800, 480))

	def test_both_paid_pictures_name_themselves_as_the_origin(self):
		import inspect
		from ..datasources.ai_image import ai_image
		from ..datasources.weather_image import weather_image
		for module in (ai_image, weather_image):
			self.assertIn("self.id)", inspect.getsource(module).split("generate(", 1)[1].split("\n", 1)[0], module.__name__)
