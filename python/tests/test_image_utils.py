import asyncio
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from ..utils import image_utils
from ..utils.image_utils import apply_image_enhancement, blurred_margin, render_html_arglist, render_html_arglist_async, stream_to_buffer, to_rgb

POSIX = os.name == "posix"

def _alive(pid: int) -> bool:
	"""True when the process exists and is not a zombie."""
	try:
		with open(f"/proc/{pid}/stat") as f:
			return f.read().rsplit(")", 1)[1].split()[0] != "Z"
	except (FileNotFoundError, ProcessLookupError):
		return False

@unittest.skipUnless(POSIX, "fake chrome is a shell script")
class TestChromeRender(unittest.TestCase):
	def setUp(self):
		self.work = tempfile.TemporaryDirectory()
		self.addCleanup(self.work.cleanup)
		# every render's temporary files land here, so the tests can see what was left behind
		self.tmp = os.path.join(self.work.name, "tmp")
		os.mkdir(self.tmp)
		p = patch.object(tempfile, "tempdir", self.tmp)
		p.start()
		self.addCleanup(p.stop)
	def _script(self, name: str, body: str) -> str:
		path = os.path.join(self.work.name, name)
		with open(path, "w") as f:
			f.write(f"#!/bin/sh\n{body}\n")
		os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
		return path
	def _python_script(self, name: str, body: str) -> str:
		path = os.path.join(self.work.name, name)
		with open(path, "w") as f:
			f.write(f"#!{sys.executable}\n{body}\n")
		os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
		return path
	def test_timeout_kills_child_and_group(self):
		pidfile = os.path.join(self.work.name, "pids")
		script = self._script("sleeper", f"sleep 300 &\necho $! > {pidfile}\nsleep 300")
		with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script), patch.object(image_utils, "CHROME_TIMEOUT_SECONDS", 1.0):
			start = time.monotonic()
			result = render_html_arglist("<html></html>", [])
			elapsed = time.monotonic() - start
		self.assertIsNone(result)
		self.assertLess(elapsed, 10)
		with open(pidfile) as f:
			grandchild = int(f.read().strip())
		time.sleep(0.2)
		self.assertFalse(_alive(grandchild), "the child's own child survived the timeout")
		self.assertEqual(os.listdir(self.tmp), [], "temporary files left behind")
	def test_failed_render_leaves_no_temp_files(self):
		script = self._script("failing", "echo boom >&2\nexit 1")
		with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script):
			self.assertIsNone(render_html_arglist("<html></html>", []))
		self.assertEqual(os.listdir(self.tmp), [])
	def test_empty_screenshot_is_a_failure(self):
		# exits 0 but never writes the screenshot: the pre-created empty PNG must not count
		script = self._script("lazy", "exit 0")
		with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script):
			self.assertIsNone(render_html_arglist("<html></html>", []))
		self.assertEqual(os.listdir(self.tmp), [])
	def test_success_uses_private_profile_each_time(self):
		log = os.path.join(self.work.name, "args.log")
		script = self._python_script("fake_chrome", f"""
import sys
from PIL import Image
shot = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--screenshot=')][0]
prof = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--user-data-dir=')]
open({log!r}, 'a').write((prof[0] if prof else '') + '\\n')
Image.new('RGB', (8, 6), 'red').save(shot, 'PNG')
""")
		with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script):
			a = render_html_arglist("<html></html>", [])
			b = render_html_arglist("<html></html>", [])
		self.assertIsNotNone(a)
		assert a is not None
		self.assertEqual(a.size, (8, 6))
		self.assertIsNotNone(b)
		with open(log) as f:
			profiles = f.read().split()
		self.assertEqual(len(profiles), 2)
		self.assertNotEqual(profiles[0], profiles[1])
		self.assertEqual(os.listdir(self.tmp), [])
	def test_does_not_log_the_html(self):
		script = self._script("failing", "exit 1")
		with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script), self.assertLogs(image_utils.logger, level="DEBUG") as cm:
			render_html_arglist("<html>SECRET-MARKER-XYZ</html>", [])
		self.assertNotIn("SECRET-MARKER-XYZ", "\n".join(cm.output))
	def test_async_render_does_not_block_the_loop(self):
		script = self._script("sleeper", "sleep 300")
		async def go():
			ticks = 0
			stop = False
			async def ticker():
				nonlocal ticks
				while not stop:
					await asyncio.sleep(0.05)
					ticks += 1
			t = asyncio.create_task(ticker())
			with patch.object(image_utils, "LINUX_CHROME_HEADLESS", script), patch.object(image_utils, "CHROME_TIMEOUT_SECONDS", 1.0):
				result = await render_html_arglist_async("<html></html>", [])
			stop = True
			await t
			return result, ticks
		result, ticks = asyncio.run(go())
		self.assertIsNone(result)
		self.assertGreater(ticks, 8, "the event loop was blocked while Chromium ran")

class TestStreamToBuffer(unittest.IsolatedAsyncioTestCase):
	def _client(self, body: bytes, headers=None):
		def handler(request: httpx.Request) -> httpx.Response:
			return httpx.Response(200, content=body, headers=headers or {"Content-Type": "image/png"})
		return httpx.AsyncClient(transport=httpx.MockTransport(handler))
	async def test_within_cap(self):
		async with self._client(b"x" * 100) as c:
			buf = await stream_to_buffer(c, "http://x/a.png", max_bytes=1000)
		self.assertEqual(len(buf.getvalue()), 100)
	async def test_content_length_over_cap(self):
		async with self._client(b"x" * 100) as c:
			with self.assertRaisesRegex(RuntimeError, "too large"):
				await stream_to_buffer(c, "http://x/a.png", max_bytes=50)
	async def test_streamed_bytes_over_cap_without_content_length(self):
		async def gen():
			for _ in range(10):
				yield b"x" * 10
		def handler(request):
			return httpx.Response(200, content=gen(), headers={"Content-Type": "image/png"})
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
			with self.assertRaisesRegex(RuntimeError, "too large"):
				await stream_to_buffer(c, "http://x/a.png", max_bytes=35)

class TestEnhancement(unittest.TestCase):
	SETTINGS = {"imageSettings-brightness": 1.2, "imageSettings-contrast": 1.1, "imageSettings-saturation": 0.9}
	def test_modes_do_not_raise(self):
		for mode in ("P", "1", "LA", "RGBA", "L", "RGB", "CMYK"):
			with self.subTest(mode=mode):
				img = Image.new(mode, (10, 8))
				out = apply_image_enhancement(img, self.SETTINGS)
				self.assertEqual(out.size, (10, 8))
	def test_rgba_is_composited_on_white(self):
		img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
		out = to_rgb(img)
		self.assertEqual(out.mode, "RGB")
		self.assertEqual(out.getpixel((0, 0)), (255, 255, 255))
	def test_palette_with_transparency_is_composited_on_white(self):
		img = Image.new("P", (4, 4), 0)
		img.putpalette([0, 0, 0] * 256)
		img.info["transparency"] = 0
		self.assertEqual(to_rgb(img).getpixel((0, 0)), (255, 255, 255))
	def test_no_settings_returns_same_image(self):
		img = Image.new("P", (2, 2))
		self.assertIs(apply_image_enhancement(img, None), img)
		self.assertIs(apply_image_enhancement(img, {"imageSettings-brightness": 1.0}), img)

class TestBlurredMargin(unittest.TestCase):
	def _two_tone(self, size):
		img = Image.new("RGB", size, (0, 0, 255))
		img.paste((255, 0, 0), (0, 0, size[0] // 2, size[1]))
		return img
	def test_the_picture_is_whole_in_the_middle_and_the_margin_is_its_own_color(self):
		out = blurred_margin(self._two_tone((400, 400)), (800, 480))
		self.assertEqual(out.size, (800, 480))
		# 480 square in the middle (160..640): red left half, blue right half; the margins are blurred copies of those colors, never white
		self.assertEqual(out.getpixel((300, 240)), (255, 0, 0))
		self.assertEqual(out.getpixel((500, 240)), (0, 0, 255))
		self.assertEqual(out.getpixel((5, 240))[0] > 150, True)
		self.assertNotEqual(out.getpixel((5, 5)), (255, 255, 255))
		self.assertNotEqual(out.getpixel((795, 5)), (255, 255, 255))
	def test_a_picture_that_fits_is_returned_and_a_small_one_is_enlarged_unless_asked_not_to(self):
		src = Image.new("RGB", (800, 480))
		self.assertIs(blurred_margin(src, (800, 480)), src)
		small = self._two_tone((100, 50))
		# not enlarged: the 100 pixel picture is at 350..450, its blue half starts at 400
		self.assertEqual(blurred_margin(small, (800, 480), enlarge=False).getpixel((401, 240)), (0, 0, 255))
		self.assertEqual(blurred_margin(small, (800, 480), enlarge=False).getpixel((399, 240)), (255, 0, 0))
		self.assertEqual(blurred_margin(small, (800, 480)).getpixel((100, 240)), (255, 0, 0))
	def test_every_mode_and_a_portrait_target_work(self):
		for mode in ("P", "1", "LA", "RGBA", "L", "RGB"):
			with self.subTest(mode=mode):
				self.assertEqual(blurred_margin(Image.new(mode, (40, 30)), (48, 80)).size, (48, 80))

if __name__ == "__main__":
	unittest.main()


class TestChromeCommand(unittest.TestCase):
	def test_the_environment_overrides_the_platform_default(self):
		from unittest.mock import patch as _patch
		# the `.env` file is not read here (a developer's own would answer for the missing variable)
		_patch.object(image_utils, "_env_file_read", True).start()
		self.addCleanup(_patch.stopall)
		with _patch.dict(os.environ, { "EINK_CHROME": sys.executable }):
			self.assertEqual(image_utils.chrome_command(), sys.executable)
		# a browser that is not on this machine is not used (a `.env` written on another one)
		with _patch.dict(os.environ, { "EINK_CHROME": "/not/here/headless_shell" }), self.assertLogs(image_utils.logger, level="WARNING"):
			self.assertIn(image_utils.chrome_command(), (image_utils.WIN_CHROME_HEADLESS, image_utils.LINUX_CHROME_HEADLESS))
		with _patch.dict(os.environ, { "EINK_CHROME": "" }):
			self.assertIn(image_utils.chrome_command(), (image_utils.WIN_CHROME_HEADLESS, image_utils.LINUX_CHROME_HEADLESS))
		env = { k: v for k, v in os.environ.items() if k != "EINK_CHROME" }
		with _patch.dict(os.environ, env, clear=True):
			self.assertIn(image_utils.chrome_command(), (image_utils.WIN_CHROME_HEADLESS, image_utils.LINUX_CHROME_HEADLESS))
