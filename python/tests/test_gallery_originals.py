"""
Saving the picture a page was made from (#768): a picture source's slide carries its original to the display, which keeps it beside the panel's picture when that page
is the whole of the panel; "Save to Gallery" keeps the original (under the source's id), or the panel's picture when there is none or the person asks for it.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from PIL import Image

from ..datasources.gallery.gallery import encode
from ..datasources.gallery.offer import GALLERY_ID
from ..task.display import Display
from ..task.display_messages import BlendImage, DisplayImage, KeptOriginal, PriorityImage, SourcePicture
from ..task.message_router import MessageRouter
from ..task.messages import Telemetry
from ..task.telemetry_hub import TelemetryHub
from ..utils.image_compositor import ImageCompositor, ImageOverlay
from ..utils.upload_image import MAX_UPLOAD_PIXELS
from .test_gallery_api import GalleryApiBase
import unittest

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
PANEL = (80, 48)

def picture(color: str, size=(120, 90)) -> Image.Image:
	return Image.new("RGB", size, color)

def slide(color: str, source: str | None = "museum-art", layer="background") -> DisplayImage:
	original = SourcePicture(picture(color), source) if source else None
	return DisplayImage(NOW, color, picture(color, PANEL), layer=layer, original=original)  # type: ignore[arg-type]

class TestWhichOriginal(unittest.TestCase):
	"""The original is the one of the page that is the whole of the panel: never a picture under another one washed over it."""
	def test_a_background_page_has_its_own_even_with_overlays_on_it(self):
		comp = ImageCompositor()
		self.assertIsNone(comp.original())
		comp.set_layer_background(slide("red"))
		comp.set_layer_overlays([ImageOverlay(picture("white", (4, 4)), (0, 0))])
		original = comp.original()
		assert original is not None
		self.assertEqual((original.source, original.image.size), ("museum-art", (120, 90)))

	def test_a_drawn_page_has_none(self):
		comp = ImageCompositor()
		comp.set_layer_background(slide("red", source=None))
		self.assertIsNone(comp.original())

	def test_an_override_page_has_its_own_and_a_blend_or_a_priority_hides_the_one_under_it(self):
		comp = ImageCompositor()
		comp.set_layer_background(slide("red"))
		# a captioned painting is an override page: the painting is its original
		comp.set_layer_forground(slide("blue", source="nasa-apod", layer="override"))
		self.assertEqual(comp.original().source, "nasa-apod")  # type: ignore[union-attr]
		comp.set_layer_forground(slide("blue", layer="blend"))
		self.assertIsNone(comp.original())
		comp.set_layer_forground(None)
		comp.set_layer_blend(BlendImage(NOW, "wash", picture("green", PANEL), timedelta(minutes=1)))
		self.assertIsNone(comp.original())
		comp.set_layer_blend(None)
		comp.set_layer_priority(PriorityImage(NOW, "Alert", picture("black", PANEL), timedelta(minutes=1)))
		self.assertIsNone(comp.original())

class TestTheDisplayKeepsIt(unittest.TestCase):
	def test_as_the_gallery_keeps_a_picture_so_the_same_one_is_the_same_bytes(self):
		display = Display("Display", MessageRouter())
		image = picture("red")
		kept = display._keep_original(SourcePicture(image, "ai-image"))
		assert kept is not None
		self.assertEqual((kept.data, kept.width, kept.height, kept.source), (encode(image), 120, 90, "ai-image"))

	def test_a_picture_larger_than_an_upload_may_be_is_not_kept(self):
		class Huge:
			size = (MAX_UPLOAD_PIXELS, 2)
		self.assertIsNone(Display("Display", MessageRouter())._keep_original(SourcePicture(Huge(), "image-url")))  # type: ignore[arg-type]

def shown(hub: TelemetryHub, color: str = "red", original: KeptOriginal | None = None) -> str:
	image = picture(color, PANEL)
	digest = hashlib.sha256(image.tobytes()).hexdigest()
	hub.accept(Telemetry(NOW, "display", { "kind": "shown", "title": f"A {color} page", "digest": digest, "image": image, **({ "original": original } if original else {}) }))
	return digest

def kept_original(color: str, source: str = "museum-art", size=(300, 200)) -> KeptOriginal:
	return KeptOriginal(encode(picture(color, size)), size[0], size[1], source)

class TestTheHubKeepsIt(unittest.TestCase):
	def test_beside_the_panel_picture_and_the_event_says_only_that_there_is_one(self):
		hub = TelemetryHub()
		original = kept_original("red")
		digest = shown(hub, "red", original)
		plain = shown(hub, "blue")
		self.assertIs(hub.original(digest), original)
		self.assertIsNone(hub.original(plain))
		first, second = hub.since(0)
		self.assertIs(first["values"]["original"], True)
		self.assertNotIn("original", second["values"])
		self.assertNotIn(original.data, repr(first).encode())

	def test_it_goes_with_its_picture_when_the_hub_lets_that_go(self):
		hub = TelemetryHub(max_images=1)
		digest = shown(hub, "red", kept_original("red"))
		shown(hub, "blue")
		self.assertIsNone(hub.original(digest))

class TestSavingTheOriginal(GalleryApiBase):
	def test_a_page_with_an_original_is_kept_as_that_picture_under_its_source(self):
		original = kept_original("red")
		digest = shown(self.hub, "red", original)
		body = self.client.post(f"{GALLERY_BASE}/items/from-display", json={ "digest": digest, "title": "A painting" }).json()
		self.assertEqual((body["kept"], body["original"]), (True, True))
		[item] = self.store.items()
		self.assertEqual((item["title"], item["origin"], item["width"], item["height"]), ("A painting", "museum-art", 300, 200))
		self.assertEqual(self.store.read(item["id"]), original.data)

	def test_as_shown_keeps_the_panel_picture_and_a_page_without_one_is_kept_as_shown(self):
		digest = shown(self.hub, "red", kept_original("red"))
		body = self.client.post(f"{GALLERY_BASE}/items/from-display", json={ "digest": digest, "asShown": True }).json()
		self.assertEqual((body["kept"], body["original"]), (True, False))
		plain = shown(self.hub, "blue")
		self.assertFalse(self.client.post(f"{GALLERY_BASE}/items/from-display", json={ "digest": plain }).json()["original"])
		self.assertEqual([(i["origin"], i["width"]) for i in self.store.items()], [("display", PANEL[0]), ("display", PANEL[0])])
		self.assertEqual(self.client.post(f"{GALLERY_BASE}/items/from-display", json={ "digest": plain, "asShown": "yes" }).status_code, 422)

	def test_a_paid_picture_already_kept_by_itself_is_there_already(self):
		# the Generated Image offered its picture as it was drawn; its slide's original is the same picture, encoded the same way
		drawn = picture("purple", (256, 160))
		self.store.keep(encode(drawn), { "title": "drawn", "origin": "ai-image", "width": 256, "height": 160 }, NOW, 100, 10 ** 9)
		digest = shown(self.hub, "purple", KeptOriginal(encode(drawn), 256, 160, "ai-image"))
		body = self.client.post(f"{GALLERY_BASE}/items/from-display", json={ "digest": digest }).json()
		self.assertEqual((body["kept"], len(self.store.items())), (False, 1))

GALLERY_BASE = f"/api/datasource/{GALLERY_ID}"
