import asyncio
import hashlib
import io
import threading
import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image
from starlette.websockets import WebSocketDisconnect

from ..task.configure_event import ConfigureNotify
from ..task.messages import Telemetry
from ..task.telemetry_hub import QUEUE_SIZE, TelemetryHub, safe_value
from ..utils.image_compositor import ImageCompositor, ImageOverlay
from ..task.display_messages import DisplayImage
from ..web.deps import SESSION_COOKIE
from .test_web_api import WebApiTestBase

ZONE = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=ZONE)

def shown(hub: TelemetryHub, color: str = "red", title: str = "Page") -> str:
	"""Tell the hub the display drew a page of that color; the image's digest."""
	img = Image.new("RGB", (800, 480), color)
	digest = hashlib.sha256(img.tobytes()).hexdigest()
	hub.accept(Telemetry(NOW, "display", { "kind": "shown", "title": title, "digest": digest, "width": 800, "height": 480, "layers": [{ "layer": "background", "title": title }], "image": img }))
	return digest

class TestEvents(unittest.TestCase):
	def test_an_event_is_small_safe_json_with_a_sequence_and_a_zone(self):
		hub = TelemetryHub()
		# a schedule item says its title, and nothing more of itself
		track = type("Track", (), { "title": "Morning slides", "content": { "key": "SECRET" } })()
		hub.accept(Telemetry(NOW, "playlist_layer", { "state": "playing", "current_track": track, "current_track_index": 0,
			"current_playlist": { "info": type("P", (), { "name": "Main" })() }, "current_playlist_index": 0 }))
		[event] = hub.since(0)
		self.assertEqual(event, { "seq": 1, "ts": "2026-10-11T12:00:00-07:00", "source": "playlist_layer", "kind": "track-ended",
			"values": { "state": "playing", "current_track": "Morning slides", "current_track_index": 0, "current_playlist": "Main", "current_playlist_index": 0 } })

	def test_the_kind_comes_from_the_values_or_the_state(self):
		hub = TelemetryHub()
		hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting", "schedule_ts": NOW, "delta": timedelta(minutes=5) }))
		hub.accept(Telemetry(NOW, "playlist_layer", { "state": "error", "kind": "track-failed", "message": "Track 'X' failed (strike 1 of 3): ConnectError" }))
		hub.accept(Telemetry(NOW, "playlist_layer", { "state": "faulted" }))
		waiting, failed, faulted = hub.since(0)
		self.assertEqual((waiting["kind"], waiting["values"]["delta"], waiting["values"]["schedule_ts"]), ("waiting", 300.0, "2026-10-11T12:00:00-07:00"))
		self.assertEqual((failed["kind"], failed["message"]), ("track-failed", "Track 'X' failed (strike 1 of 3): ConnectError"))
		self.assertNotIn("message", failed["values"])
		self.assertEqual(faulted["kind"], "faulted")

	def test_what_is_not_json_says_only_its_name(self):
		class Secretive:
			def __str__(self):
				return "https://x/?key=SECRET"
		self.assertEqual(safe_value({ "a": Secretive(), "b": [1, "x" * 1000], "c": { "d": { "e": { "f": 1 } } } }),
			{ "a": "Secretive", "b": [1, "x" * 299 + "…"], "c": { "d": { "e": "dict" } } })

	def test_a_configuration_that_failed_is_an_event_and_other_messages_are_not(self):
		hub = TelemetryHub()
		hub.accept(ConfigureNotify(NOW, "playlist-layer", True, "Traceback with a secret"))  # type: ignore[call-arg]
		hub.accept(ConfigureNotify(NOW, "timer-layer", False, None))  # type: ignore[call-arg]
		[event] = hub.since(0)
		self.assertEqual((event["kind"], event["message"]), ("configure-failed", "'playlist-layer' could not be configured."))
		self.assertNotIn("secret", str(event))

	def test_the_ring_keeps_the_newest(self):
		hub = TelemetryHub(max_events=3)
		for n in range(5):
			hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting", "n": n }))
		self.assertEqual([e["seq"] for e in hub.since(0)], [3, 4, 5])
		self.assertEqual([e["seq"] for e in hub.since(4)], [5])

	def test_many_threads_at_once_get_distinct_sequence_numbers(self):
		hub = TelemetryHub(max_events=1000)
		def send():
			for _ in range(100):
				hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		threads = [threading.Thread(target=send) for _ in range(8)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		self.assertEqual(sorted(e["seq"] for e in hub.since(0)), list(range(1, 801)))

class TestImages(unittest.TestCase):
	def test_a_shown_page_is_kept_by_its_digest_and_the_event_holds_only_the_digest(self):
		hub = TelemetryHub()
		digest = shown(hub)
		event = hub.current()
		assert event is not None
		self.assertEqual((event["kind"], event["values"]["digest"]), ("shown", digest))
		self.assertNotIn("image", event["values"])
		self.assertEqual(event["values"]["layers"], [{ "layer": "background", "title": "Page" }], "the layers arrive whole")
		thumb = Image.open(io.BytesIO(hub.image(digest, "thumb") or b""))
		self.assertEqual(thumb.size, (320, 192))
		self.assertEqual(Image.open(io.BytesIO(hub.image(digest, "full") or b"")).size, (800, 480))
		self.assertIsNone(hub.image("0" * 64))

	def test_only_the_last_few_are_kept(self):
		hub = TelemetryHub(max_images=2)
		first, second, third = shown(hub, "red"), shown(hub, "green"), shown(hub, "blue")
		self.assertIsNone(hub.image(first))
		self.assertIsNotNone(hub.image(second))
		self.assertIsNotNone(hub.image(third))

	def test_the_layers_of_what_is_shown_are_described(self):
		comp = ImageCompositor()
		page = lambda title, layer="background": DisplayImage(NOW, title, Image.new("RGB", (8, 6)), layer=layer)  # noqa: E731
		comp.set_layer_background(page("Photo"))
		comp.set_layer_overlays([ImageOverlay(Image.new("RGB", (2, 2)), (0, 0))])
		self.assertEqual(comp.layers(), [{ "layer": "background", "title": "Photo" }, { "layer": "overlays", "count": 1 }])
		comp.set_layer_forground(page("Poem", "blend"))
		self.assertEqual(comp.layers(), [{ "layer": "background", "title": "Photo" }, { "layer": "blend", "title": "Poem" }])
		comp.set_layer_forground(page("Calendar", "override"))
		self.assertEqual(comp.layers(), [{ "layer": "override", "title": "Calendar" }])

class TestSubscribers(unittest.IsolatedAsyncioTestCase):
	async def test_each_subscriber_gets_every_event_from_any_thread(self):
		hub = TelemetryHub()
		a, b = hub.subscribe(asyncio.get_running_loop()), hub.subscribe(asyncio.get_running_loop())
		await asyncio.to_thread(hub.accept, Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		for sub in (a, b):
			self.assertEqual((await asyncio.wait_for(sub.next(), 1))["seq"], 1)
		hub.unsubscribe(a)
		hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		await asyncio.sleep(0)
		self.assertTrue(a.queue.empty())
		self.assertEqual((await asyncio.wait_for(b.next(), 1))["seq"], 2)

	async def test_a_slow_subscriber_loses_its_oldest_events_and_is_told(self):
		hub = TelemetryHub()
		sub = hub.subscribe(asyncio.get_running_loop())
		for _ in range(QUEUE_SIZE + 5):
			hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		await asyncio.sleep(0)
		gap = await sub.next()
		self.assertEqual((gap["kind"], gap["missed"]), ("gap", 5))
		self.assertEqual((await sub.next())["seq"], 6, "the oldest were dropped")

class TestRoutes(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.hub = TelemetryHub()
		self.app.state.root_container.add_service(TelemetryHub, self.hub)

	def test_recent_events_and_what_is_shown_now(self):
		self.assertIsNone(self.client.get("/api/display/current").json())
		self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		digest = shown(self.hub)
		self.assertEqual([e["kind"] for e in self.client.get("/api/telemetry").json()], ["waiting", "shown"])
		self.assertEqual([e["kind"] for e in self.client.get("/api/telemetry?since=1").json()], ["shown"])
		self.assertEqual(self.client.get("/api/display/current").json()["values"]["digest"], digest)

	def test_an_image_by_its_digest_and_nothing_else(self):
		digest = shown(self.hub)
		resp = self.client.get(f"/api/display/images/{digest}")
		self.assertEqual((resp.status_code, resp.headers["content-type"]), (200, "image/png"))
		self.assertIn("immutable", resp.headers["cache-control"])
		self.assertEqual(Image.open(io.BytesIO(self.client.get(f"/api/display/images/{digest}?size=full").content)).size, (800, 480))
		for bad in ("0" * 64, "..%2F..%2Fsettings", "not-hex", digest.upper()):
			with self.subTest(bad):
				resp = self.client.get(f"/api/display/images/{bad}")
				self.assertEqual(resp.status_code, 404)
				self.assertNotIn(bad, resp.text, "the answer does not echo the URL")
		self.assertEqual(self.client.get(f"/api/display/images/{digest}?size=huge").status_code, 422)

	def test_the_link_sends_the_history_then_follows(self):
		self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
		self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "playing" }))
		with self.client.websocket_connect("/api/telemetry/ws?since=1") as ws:
			self.assertEqual(ws.receive_json()["seq"], 2)
			self.hub.accept(Telemetry(NOW, "application", { "kind": "config-changed", "area": "settings", "message": "The settings changed." }))
			event = ws.receive_json()
			self.assertEqual((event["seq"], event["kind"], event["message"]), (3, "config-changed", "The settings changed."))

	def test_another_sites_page_may_not_connect(self):
		with self.assertRaises(WebSocketDisconnect) as refused:
			with self.client.websocket_connect("/api/telemetry/ws", headers={ "Origin": "https://evil.example" }) as ws:
				ws.receive_json()
		self.assertEqual(refused.exception.code, 4403)
		with self.client.websocket_connect("/api/telemetry/ws", headers={ "Origin": "http://testserver" }) as ws:
			self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
			self.assertEqual(ws.receive_json()["kind"], "waiting")

class TestRoutesWithAToken(WebApiTestBase):
	token = "s3cret"

	def setUp(self):
		super().setUp()
		self.hub = TelemetryHub()
		self.app.state.root_container.add_service(TelemetryHub, self.hub)

	def test_the_link_needs_a_session_or_the_token(self):
		with self.assertRaises(WebSocketDisconnect) as refused:
			with self.client.websocket_connect("/api/telemetry/ws") as ws:
				ws.receive_json()
		self.assertEqual(refused.exception.code, 4401)
		self.assertEqual(self.client.get("/api/telemetry").status_code, 401)
		with self.client.websocket_connect("/api/telemetry/ws", headers={ "Authorization": "Bearer s3cret" }) as ws:
			self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
			self.assertEqual(ws.receive_json()["kind"], "waiting")
		session = self.app.state.sessions.create()
		self.client.cookies.set(SESSION_COOKIE, session)
		with self.client.websocket_connect("/api/telemetry/ws?since=1") as ws:
			self.hub.accept(Telemetry(NOW, "timer_layer", { "state": "waiting" }))
			self.assertEqual(ws.receive_json()["seq"], 2)
