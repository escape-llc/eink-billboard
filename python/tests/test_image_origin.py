"""Which track or task made the image on the panel: the router a plugin sends through marks its images, and the layers say where they came from."""
import unittest
from datetime import datetime, timedelta

from PIL import Image

from ..task.display_messages import DisplayImage, OverlayImage, PriorityImage
from ..task.message_router import MessageRouter, Route
from ..task.source_router import SourceRouter, image_source
from ..utils.image_compositor import ImageCompositor, ImageOverlay

NOW = datetime(2026, 10, 12, 12, 0)
IMG = Image.new("RGB", (8, 6))

class Catcher:
	def __init__(self):
		self.got = []
	def accept(self, msg):
		self.got.append(msg)

class TestSourceRouter(unittest.TestCase):
	def setUp(self):
		self.catcher = Catcher()
		self.real = MessageRouter()
		self.real.addRoute(Route("display", [self.catcher]))
		self.origin = image_source("playlist", "Morning Joe", "Slide Show", "Main")
		self.router = SourceRouter(self.real, self.origin)

	def test_every_kind_of_image_is_marked(self):
		for msg in (DisplayImage(NOW, "a", IMG), PriorityImage(NOW, "b", IMG, timedelta(minutes=1)), OverlayImage(NOW, "k", "top-left", "c", IMG)):
			self.router.send("display", msg)
		self.assertEqual([m.origin for m in self.catcher.got], [self.origin] * 3)
		self.assertEqual([m.title for m in self.catcher.got], ["a", "b", "c"], "nothing else changes")

	def test_a_message_that_has_an_origin_keeps_it(self):
		own = { "kind": "device", "title": "x", "plugin": "y" }
		self.router.send("display", DisplayImage(NOW, "a", IMG, origin=own))
		self.assertEqual(self.catcher.got[0].origin, own)

	def test_other_routes_and_messages_pass_through(self):
		self.router.addRoute(Route("other", [self.catcher]))
		self.router.send("other", DisplayImage(NOW, "a", IMG))
		self.assertIsNone(self.catcher.got[0].origin)

class TestOriginOnTheLayers(unittest.TestCase):
	def test_the_layers_say_where_each_came_from(self):
		comp = ImageCompositor()
		bg, ov = image_source("playlist", "Photo", "Slide Show", "Main"), image_source("timer", "Clock", "Overlay")
		comp.set_layer_background(DisplayImage(NOW, "Photo", IMG, origin=bg))
		comp.set_layer_overlays([ImageOverlay(Image.new("RGB", (2, 2)), (0, 0), origin=ov)])
		self.assertEqual(comp.layers(), [{ "layer": "background", "title": "Photo", "origin": bg }, { "layer": "overlays", "count": 1, "origins": [ov] }])
		comp.set_layer_priority(PriorityImage(NOW, "Alert", IMG, timedelta(minutes=1), origin=ov))
		self.assertEqual(comp.layers(), [{ "layer": "priority", "title": "Alert", "origin": ov }])

class TestOriginInTheTelemetry(unittest.TestCase):
	def test_the_hub_keeps_the_origin_of_every_layer(self):
		from ..task.messages import Telemetry
		from ..task.telemetry_hub import TelemetryHub
		bg, ov = image_source("playlist", "Photo", "Slide Show", "Main"), image_source("timer", "Clock", "Overlay")
		hub = TelemetryHub()
		layers = [{ "layer": "background", "title": "Photo", "origin": bg }, { "layer": "overlays", "count": 1, "origins": [ov] }]
		hub.accept(Telemetry(NOW.astimezone(), "display", { "kind": "shown", "title": "Photo", "layers": layers }))
		self.assertEqual(hub.since(0)[0]["values"]["layers"], layers)
