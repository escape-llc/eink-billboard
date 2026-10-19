"""
Push a message or a picture to the panel from a script (#366): `POST /api/display/message`, `POST /api/display/image`, `DELETE /api/display/message/{id}`. The text becomes a themed page, a picture
is checked and fitted, and either is shown over everything for a few minutes as a priority image that the API can take down again.
"""
import datetime
import io
import os
import shutil
import time
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from PIL import Image

from ..model.configuration_manager import StaticConfigurationManager
from ..task.application import MAX_PUSHED_ACTIVE, Application, PushRefused
from ..task.display_messages import PriorityImage, PriorityRevoke
from ..task.message_router import MessageRouter
from ..task.messages import PushedImage, Telemetry
from ..utils.image_utils import chrome_command
from ..utils.message_image import MAX_TEXT_CHARACTERS, plain_message_image, render_message_image, text_size
from ..utils.upload_image import MAX_UPLOAD_BYTES, MAX_UPLOAD_PIXELS, decode_upload
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
HAVE_CHROME = shutil.which(chrome_command()) is not None
SIZE = (80, 48)

def picture(fmt: str = "PNG", size: tuple[int, int] = (40, 40), color: Any = "red", **options: Any) -> bytes:
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, fmt, **options)
	return buffer.getvalue()

class TestUpload(unittest.TestCase):
	def test_each_format_is_fitted_to_the_panel_as_rgb(self):
		for fmt in ("PNG", "JPEG", "GIF", "WEBP"):
			with self.subTest(fmt):
				image = decode_upload(picture(fmt), SIZE)
				self.assertEqual((image.size, image.mode), (SIZE, "RGB"))

	def test_the_whole_picture_is_shown_on_a_margin_of_its_own_colors(self):
		image = decode_upload(picture("PNG", (40, 40), "red"), SIZE)
		# a square on a wide panel: red in the middle and red-ish at the sides, never white bars
		self.assertEqual(image.getpixel((40, 24)), (255, 0, 0))
		corner = image.getpixel((1, 1))
		self.assertGreater(corner[0], 200)
		self.assertLess(corner[2], 80)

	def test_a_picture_with_a_transparent_part_is_put_on_white(self):
		buffer = io.BytesIO()
		Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(buffer, "PNG")
		image = decode_upload(buffer.getvalue(), (40, 40))
		self.assertEqual(image.getpixel((20, 20)), (255, 255, 255))

	def test_a_phones_rotation_is_applied(self):
		portrait = Image.new("RGB", (60, 20), "blue")
		exif = Image.Exif()
		exif[0x0112] = 6   # rotate to show
		buffer = io.BytesIO()
		portrait.save(buffer, "JPEG", exif=exif)
		image = decode_upload(buffer.getvalue(), (20, 60))
		# turned upright, the 60 x 20 picture is 20 x 60: it fills a 20 x 60 panel
		self.assertEqual(image.size, (20, 60))
		self.assertLess(image.getpixel((10, 5))[0], 60)

	def test_only_the_first_frame_of_an_animation_is_used(self):
		frames = [Image.new("RGB", (20, 20), "red"), Image.new("RGB", (20, 20), "blue")]
		buffer = io.BytesIO()
		frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:], duration=100)
		image = decode_upload(buffer.getvalue(), (20, 20))
		self.assertGreater(image.getpixel((10, 10))[0], 200)

	def test_nothing_is_refused(self):
		with self.assertRaisesRegex(ValueError, "no picture"):
			decode_upload(b"", SIZE)

	def test_what_is_not_a_picture_is_refused_by_its_content_not_its_name(self):
		for data in (b"hello", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", b"%PDF-1.4", b"GIF89a-broken"):
			with self.subTest(data[:10]):
				with self.assertRaisesRegex(ValueError, "not a picture"):
					decode_upload(data, SIZE)

	def test_a_format_that_is_not_on_the_list_is_refused(self):
		buffer = io.BytesIO()
		Image.new("RGB", (10, 10)).save(buffer, "BMP")
		with self.assertRaisesRegex(ValueError, "not a picture"):
			decode_upload(buffer.getvalue(), SIZE)

	def test_a_body_that_is_too_large_is_refused(self):
		with self.assertRaisesRegex(ValueError, "larger than"):
			decode_upload(b"x" * (MAX_UPLOAD_BYTES + 1), SIZE)

	def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded(self):
		# a few kilobytes of file that would be 81 million pixels
		side = int(MAX_UPLOAD_PIXELS ** 0.5) + 500
		buffer = io.BytesIO()
		Image.new("1", (side, side)).save(buffer, "PNG")
		self.assertLess(len(buffer.getvalue()), MAX_UPLOAD_BYTES)
		with patch.object(Image.Image, "load", side_effect=AssertionError("decoded")):
			with self.assertRaisesRegex(ValueError, "million pixels"):
				decode_upload(buffer.getvalue(), SIZE)

	def test_a_damaged_picture_is_refused_in_our_words(self):
		data = bytearray(picture("PNG", (200, 200), "red"))
		del data[len(data) // 2:len(data) - 12]
		with self.assertRaisesRegex(ValueError, "damaged"):
			decode_upload(bytes(data), SIZE)

class TestMessageImage(unittest.TestCase):
	def test_short_words_are_big_and_a_paragraph_is_smaller(self):
		sizes = [text_size((800, 480), "", text) for text in ("Hi", "Someone is at the door", "x" * 100, "x" * 300, "x" * 900)]
		self.assertEqual(sizes, sorted(sizes, reverse=True))
		self.assertGreater(sizes[0], sizes[-1] * 2)

	def test_lines_count_as_much_as_letters(self):
		self.assertLess(text_size((800, 480), "", "a\nb\nc\nd\ne\nf"), text_size((800, 480), "", "abcdef"))

	def test_a_narrow_page_has_smaller_type(self):
		self.assertLess(text_size((200, 480), "", "Hello there"), text_size((800, 480), "", "Hello there"))

	def test_the_plain_page_is_the_panels_size_with_something_on_it_and_fits_a_flood_of_text(self):
		for size in ((800, 480), (400, 300), (480, 800)):
			with self.subTest(size):
				image = plain_message_image(size, "Doorbell", "Someone is at the door\n" * 80)
				self.assertEqual(image.size, size)
				self.assertNotEqual(image.convert("L").getextrema(), (255, 255))

	def test_without_the_static_files_the_plain_page_is_drawn(self):
		image = render_message_image(None, (400, 300), "T", "text")
		self.assertEqual(image.size, (400, 300))

	@unittest.skipUnless(HAVE_CHROME, "needs the headless browser (EINK_CHROME, or chromium-headless-shell on PATH)")
	def test_the_themed_page_is_drawn_by_the_browser_and_escapes_what_it_is_given(self):
		stm = StaticConfigurationManager(STATIC)
		image = render_message_image(stm, (800, 480), "<b>Doorbell</b>", "Someone is at the door <script>1</script>")
		self.assertEqual(image.size, (800, 480))
		self.assertNotEqual(image.convert("L").getextrema(), (255, 255))

class Recorder:
	"""A router that records what goes where."""
	def __init__(self) -> None:
		self.sent: list[tuple[str, Any]] = []
	def send(self, route: str, msg: Any) -> None:
		self.sent.append((route, msg))

def application(test: unittest.TestCase, orientation: str = "landscape") -> tuple[Application, Recorder]:
	"""An Application that is configured the way the display settings leave it, with nothing started."""
	cm = temp_configuration_manager(test)
	cob = cm.settings_manager().open("display")
	rev, content = cob.get()
	cob.save(rev, { **(content or {}), "orientation": orientation })
	app = Application("TestApp")
	app.cm = cm
	recorder = Recorder()
	app.router = cast(MessageRouter, recorder)
	app._panel = (800, 480)
	app.playlist_layer = cast(Any, SimpleNamespace(halted=False))
	return app, recorder

def queued(app: Application) -> list:
	items = []
	while not app.msg_queue.empty():
		items.append(app.msg_queue.get_nowait())
	return items

class TestApplicationPush(unittest.TestCase):
	def test_the_size_is_the_panels_and_swapped_for_a_portrait_display(self):
		self.assertEqual(application(self)[0].content_size(), (800, 480))
		self.assertEqual(application(self, "portrait")[0].content_size(), (480, 800))

	def test_before_the_display_is_up_it_is_a_503(self):
		app = Application("TestApp")
		with self.assertRaises(PushRefused) as caught:
			app.content_size()
		self.assertEqual(caught.exception.status, 503)
		with self.assertRaises(PushRefused):
			app.push_image("t", Image.new("RGB", SIZE), 1)

	def test_a_push_is_handed_to_the_applications_own_thread(self):
		app, _ = application(self)
		pushed = app.push_image("Doorbell", Image.new("RGB", SIZE), 3)
		[msg] = queued(app)
		assert isinstance(msg, PushedImage)
		self.assertEqual((msg.title, msg.duration), ("Doorbell", datetime.timedelta(minutes=3)))
		self.assertEqual((pushed.title, len(pushed.id)), ("Doorbell", 32))

	def test_the_same_title_is_made_unique_while_the_first_is_about(self):
		app, _ = application(self)
		titles = [app.push_image("Doorbell", Image.new("RGB", SIZE), 1).title for _ in range(3)]
		self.assertEqual(titles, ["Doorbell", "Doorbell (2)", "Doorbell (3)"])

	def test_a_title_comes_free_when_its_message_is_over(self):
		app, _ = application(self)
		app.push_image("Doorbell", Image.new("RGB", SIZE), 1)
		# its time, and the slack for waiting behind others, has passed
		app._pushed = { key: (title, time.monotonic() - 1) for key, (title, _) in app._pushed.items() }
		self.assertEqual(app.push_image("Doorbell", Image.new("RGB", SIZE), 1).title, "Doorbell")

	def test_a_device_nobody_has_claimed_refuses(self):
		app, _ = application(self)
		app.setup_notice = lambda: ["Open http://pi.local", "Setup code 1234 5678"]
		with self.assertRaises(PushRefused) as caught:
			app.push_image("t", Image.new("RGB", SIZE), 1)
		self.assertEqual(caught.exception.status, 403)
		self.assertIn("claimed", caught.exception.message)
		self.assertEqual(queued(app), [])

	def test_too_many_waiting_is_a_429_and_a_finished_one_makes_room(self):
		app, _ = application(self)
		for number in range(MAX_PUSHED_ACTIVE):
			app.push_image(f"m{number}", Image.new("RGB", SIZE), 1)
		with self.assertRaises(PushRefused) as caught:
			app.push_image("one more", Image.new("RGB", SIZE), 1)
		self.assertEqual(caught.exception.status, 429)
		first = next(iter(app._pushed))
		app._pushed[first] = (app._pushed[first][0], time.monotonic() - 1)
		app.push_image("one more", Image.new("RGB", SIZE), 1)

	def test_an_application_that_has_stopped_says_so_and_keeps_nothing(self):
		app, _ = application(self)
		def refuse(msg: Any) -> None:
			raise ValueError("stopped")
		app.accept = refuse  # type: ignore[method-assign]
		with self.assertRaises(PushRefused) as caught:
			app.push_image("t", Image.new("RGB", SIZE), 1)
		self.assertEqual(caught.exception.status, 503)
		self.assertEqual(app._pushed, {})

	def test_the_least_wait_is_the_panels_rest_and_the_commit_timer(self):
		app, _ = application(self)
		self.assertEqual(app.push_image("a", Image.new("RGB", SIZE), 1).starts_in_seconds, 2)
		app.display = cast(Any, SimpleNamespace(display=SimpleNamespace(ready_in=lambda: 40.0)))
		self.assertEqual(app.push_image("b", Image.new("RGB", SIZE), 1).starts_in_seconds, 42)

	def test_the_push_reaches_the_display_as_a_priority_image_marked_as_the_apis(self):
		app, recorder = application(self)
		app.push_image("Doorbell", Image.new("RGB", SIZE, "red"), 2)
		[msg] = queued(app)
		app._pushed_image(msg)
		display = [m for route, m in recorder.sent if route == "display"]
		[shown] = display
		assert isinstance(shown, PriorityImage)
		self.assertEqual((shown.title, shown.duration, shown.origin), ("Doorbell", datetime.timedelta(minutes=2), { "kind": "api", "title": "Doorbell", "plugin": "Push API" }))
		told = [m for route, m in recorder.sent if route == "telemetry"]
		self.assertEqual([m.values["kind"] for m in told if isinstance(m, Telemetry)], ["pushed"])

	def test_a_message_is_taken_down_by_its_id_and_only_once(self):
		app, recorder = application(self)
		first = app.push_image("Doorbell", Image.new("RGB", SIZE), 5)
		second = app.push_image("Doorbell", Image.new("RGB", SIZE), 5)
		self.assertTrue(app.revoke_pushed(second.id))
		[revoke] = [m for route, m in recorder.sent if route == "display"]
		assert isinstance(revoke, PriorityRevoke)
		self.assertEqual(revoke.title, "Doorbell (2)", "the second one, not both")
		self.assertFalse(app.revoke_pushed(second.id))
		self.assertFalse(app.revoke_pushed("nothing"))
		self.assertTrue(app.revoke_pushed(first.id))

class PushApiBase(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.application, self.recorder = application(self)
		self.application.cm = self.cm
		self.app.state.root_container.add_service(Application, self.application)
		# the page is made by the browser in CI; here a solid one of the right size says what was asked for
		self.made: list[tuple[tuple[int, int], str, str]] = []
		def render(stm, size, title, text, theme=None):
			self.made.append((size, title, text))
			return Image.new("RGB", size, "white")
		patcher = patch("python.web.routers.display.render_message_image", render)
		patcher.start()
		self.addCleanup(patcher.stop)

class TestPushMessage(PushApiBase):
	def test_a_message_is_made_into_a_page_and_queued(self):
		resp = self.client.post("/api/display/message", json={ "text": "Someone is at the door", "title": "Doorbell", "minutes": 2 })
		self.assertEqual(resp.status_code, 200, resp.text)
		body = resp.json()
		self.assertTrue(body["success"])
		self.assertEqual((body["title"], body["startsInSeconds"], len(body["id"])), ("Doorbell", 2, 32))
		self.assertEqual(self.made, [((800, 480), "Doorbell", "Someone is at the door")])
		[msg] = queued(self.application)
		assert isinstance(msg, PushedImage)
		self.assertEqual((msg.title, msg.duration), ("Doorbell", datetime.timedelta(minutes=2)))

	def test_the_defaults_are_five_minutes_and_the_title_message(self):
		body = self.client.post("/api/display/message", json={ "text": "hello" }).json()
		self.assertEqual(body["title"], "Message")
		[msg] = queued(self.application)
		self.assertEqual(msg.duration, datetime.timedelta(minutes=5))
		self.assertEqual(self.made[0][1], "")

	def test_the_page_is_made_at_the_swapped_size_on_a_portrait_display(self):
		app, _ = application(self, "portrait")
		self.application.cm = app.cm
		self.client.post("/api/display/message", json={ "text": "hello" })
		self.assertEqual(self.made[0][0], (480, 800))

	def test_what_is_not_acceptable_is_a_422_in_the_uniform_shape(self):
		for body in ({}, { "text": "" }, { "text": "x" * (MAX_TEXT_CHARACTERS + 1) }, { "text": "hi", "minutes": 0 }, { "text": "hi", "minutes": 61 }, { "text": "hi", "title": "t" * 200 }, { "text": 5 }):
			with self.subTest(body):
				resp = self.client.post("/api/display/message", json=body)
				self.assertEqual(resp.status_code, 422)
				self.assertFalse(resp.json()["success"])
		self.assertEqual(queued(self.application), [])
		self.assertEqual(self.made, [])

	def test_control_characters_are_dropped_and_a_text_of_nothing_else_is_refused(self):
		self.client.post("/api/display/message", json={ "text": "Hello\x00 \x1b[31mthere\x07\nline two", "title": "T\x00" })
		self.assertEqual(self.made[0][1:], ("T", "Hello [31mthere\nline two"))
		resp = self.client.post("/api/display/message", json={ "text": "\x00\x01  " })
		self.assertEqual(resp.status_code, 422)
		self.assertEqual(resp.json()["errors"][0]["path"], ["text"])

	def test_html_is_text(self):
		self.client.post("/api/display/message", json={ "text": "<script>alert(1)</script>" })
		self.assertEqual(self.made[0][2], "<script>alert(1)</script>", "it is handed on as text: the page escapes it")

	def test_a_device_that_is_not_claimed_is_a_403(self):
		self.application.setup_notice = lambda: ["Setup code 1234 5678"]
		resp = self.client.post("/api/display/message", json={ "text": "hello" })
		self.assertEqual(resp.status_code, 403)
		self.assertEqual(set(resp.json()), { "success", "message", "id" })

	def test_too_many_are_a_429(self):
		for _ in range(MAX_PUSHED_ACTIVE):
			self.assertEqual(self.client.post("/api/display/message", json={ "text": "hello" }).status_code, 200)
		resp = self.client.post("/api/display/message", json={ "text": "hello" })
		self.assertEqual(resp.status_code, 429)

	def test_before_the_layers_exist_it_is_a_503(self):
		self.application.playlist_layer = None
		self.assertEqual(self.client.post("/api/display/message", json={ "text": "hello" }).status_code, 503)

class TestPushImage(PushApiBase):
	def post(self, data: bytes, query: str = "", content_type: str = "image/png"):
		return self.client.post(f"/api/display/image{query}", content=data, headers={ "Content-Type": content_type })

	def test_a_picture_is_fitted_and_queued(self):
		resp = self.post(picture("PNG", (60, 60), "blue"), "?title=Camera&minutes=3")
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(resp.json()["title"], "Camera")
		[msg] = queued(self.application)
		assert isinstance(msg, PushedImage)
		self.assertEqual((msg.img.size, msg.duration), ((800, 480), datetime.timedelta(minutes=3)))

	def test_a_jpeg_works_whatever_the_sender_calls_it(self):
		self.assertEqual(self.post(picture("JPEG"), content_type="application/octet-stream").status_code, 200)

	def test_the_default_title_is_picture(self):
		self.assertEqual(self.post(picture("PNG")).json()["title"], "Picture")

	def test_what_is_not_a_picture_is_a_415_and_nothing_is_queued(self):
		resp = self.post(b"not a picture at all")
		self.assertEqual(resp.status_code, 415)
		self.assertFalse(resp.json()["success"])
		self.assertEqual(queued(self.application), [])

	def test_an_empty_body_is_a_422(self):
		self.assertEqual(self.post(b"").status_code, 422)

	def test_a_body_that_says_it_is_too_large_is_cut_off_at_once(self):
		resp = self.client.post("/api/display/image", content=b"x", headers={ "Content-Length": str(MAX_UPLOAD_BYTES + 1), "Content-Type": "image/png" })
		self.assertEqual(resp.status_code, 413)
		self.assertEqual(queued(self.application), [])

	def test_a_body_that_is_too_large_is_a_413_however_it_arrives(self):
		def chunks():
			for _ in range(MAX_UPLOAD_BYTES // (1024 * 1024) + 2):
				yield b"x" * (1024 * 1024)
		resp = self.client.post("/api/display/image", content=chunks(), headers={ "Content-Type": "image/png" })
		self.assertEqual(resp.status_code, 413)
		self.assertEqual(queued(self.application), [])

	def test_a_picture_of_too_many_pixels_is_refused(self):
		side = int(MAX_UPLOAD_PIXELS ** 0.5) + 500
		buffer = io.BytesIO()
		Image.new("1", (side, side)).save(buffer, "PNG")
		self.assertEqual(self.post(buffer.getvalue()).status_code, 422)

	def test_minutes_are_checked_in_the_address(self):
		for query in ("?minutes=0", "?minutes=61", "?minutes=soon", "?title=" + "t" * 200):
			with self.subTest(query):
				self.assertEqual(self.post(picture("PNG"), query).status_code, 422)

	def test_a_device_that_is_not_claimed_is_a_403(self):
		self.application.setup_notice = lambda: ["Setup code 1234 5678"]
		self.assertEqual(self.post(picture("PNG")).status_code, 403)

class TestTakeDown(PushApiBase):
	def test_a_message_is_taken_down_by_its_id(self):
		pushed = self.client.post("/api/display/message", json={ "text": "hello", "title": "Doorbell" }).json()
		resp = self.client.delete(f"/api/display/message/{pushed['id']}")
		self.assertEqual((resp.status_code, resp.json()), (200, { "success": True }))
		[revoke] = [m for route, m in self.recorder.sent if route == "display"]
		assert isinstance(revoke, PriorityRevoke)
		self.assertEqual(revoke.title, "Doorbell")

	def test_a_second_delete_and_a_stranger_are_404s(self):
		pushed = self.client.post("/api/display/message", json={ "text": "hello" }).json()
		self.assertEqual(self.client.delete(f"/api/display/message/{pushed['id']}").status_code, 200)
		for message_id in (pushed["id"], "nothing", "..%2F..%2Fetc", "0" * 32):
			with self.subTest(message_id):
				resp = self.client.delete(f"/api/display/message/{message_id}")
				self.assertEqual(resp.status_code, 404)
				self.assertEqual(set(resp.json()), { "success", "message", "id" })

class TestPushNeedsTheToken(PushApiBase):
	token = "e2e-secret"
	auth = "required"
	local = False

	def test_without_the_token_nothing_is_taken(self):
		for resp in (self.client.post("/api/display/message", json={ "text": "hello" }),
				self.client.post("/api/display/image", content=picture("PNG")), self.client.delete("/api/display/message/x")):
			self.assertEqual(resp.status_code, 401)
		self.assertEqual(queued(self.application), [])

	def test_with_the_token_it_is_taken(self):
		resp = self.client.post("/api/display/message", json={ "text": "hello" }, headers={ "Authorization": f"Bearer {self.token}" })
		self.assertEqual(resp.status_code, 200, resp.text)

if __name__ == "__main__":
	unittest.main()
