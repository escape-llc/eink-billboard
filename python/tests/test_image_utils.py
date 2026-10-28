import asyncio
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import psutil
from PIL import Image

from ..utils import image_utils
from ..utils.image_utils import apply_image_enhancement, blurred_margin, change_orientation, resize_image, render_html_arglist, render_html_arglist_async, stream_to_buffer, to_rgb

def _alive(pid: int) -> bool:
	"""True when the process exists and is not a zombie (Linux keeps a killed child's entry until it is reaped)."""
	try:
		return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
	except psutil.NoSuchProcess:
		return False

class TestChromeRender(unittest.TestCase):
	"""
	The render's handling of the browser process, with a fake browser: a Python script, made runnable as the browser is, by a shebang on POSIX and a `.cmd` shim on Windows
	(which `CreateProcess` runs through `cmd.exe`), so both platforms' process handling is tested: the process group and `killpg` here, `CREATE_NEW_PROCESS_GROUP` and `taskkill /T` there.
	"""
	def setUp(self):
		self.work = tempfile.TemporaryDirectory()
		self.addCleanup(self.work.cleanup)
		# every render's temporary files land here, so the tests can see what was left behind
		self.tmp = os.path.join(self.work.name, "tmp")
		os.mkdir(self.tmp)
		p = patch.object(tempfile, "tempdir", self.tmp)
		p.start()
		self.addCleanup(p.stop)
	def _browser(self, name: str, body: str) -> str:
		"""A fake browser running `body` (Python), and the patch that makes the render start it (`EINK_CHROME` in a `.env` would otherwise win)."""
		script = os.path.join(self.work.name, f"{name}.py")
		with open(script, "w", encoding="utf-8") as f:
			f.write(f"#!{sys.executable}\n{body}\n")
		if os.name == "nt":
			path = os.path.join(self.work.name, f"{name}.cmd")
			with open(path, "w", encoding="utf-8") as f:
				f.write(f'@"{sys.executable}" "{script}" %*\n')
		else:
			path = script
			os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
		patcher = patch.object(image_utils, "chrome_command", lambda: path)
		patcher.start()
		self.addCleanup(patcher.stop)
		return path
	def test_timeout_kills_child_and_group(self):
		pidfile = os.path.join(self.work.name, "pids")
		self._browser("sleeper", f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
with open({pidfile!r}, "w") as f:
	f.write(str(child.pid))
time.sleep(300)
""")
		# long enough for the fake (a shell, then Python, then its child) to start on a slow machine
		with patch.object(image_utils, "CHROME_TIMEOUT_SECONDS", 3.0):
			start = time.monotonic()
			result = render_html_arglist("<html></html>", [])
			elapsed = time.monotonic() - start
		self.assertIsNone(result)
		self.assertLess(elapsed, 15)
		with open(pidfile) as f:
			grandchild = int(f.read().strip())
		deadline = time.monotonic() + 5
		while _alive(grandchild) and time.monotonic() < deadline:
			time.sleep(0.1)
		self.assertFalse(_alive(grandchild), "the child's own child survived the timeout")
		self.assertEqual(os.listdir(self.tmp), [], "temporary files left behind")
	def test_failed_render_leaves_no_temp_files(self):
		self._browser("failing", "import sys\nsys.stderr.write('boom')\nsys.exit(1)")
		self.assertIsNone(render_html_arglist("<html></html>", []))
		self.assertEqual(os.listdir(self.tmp), [])
	def test_empty_screenshot_is_a_failure(self):
		# exits 0 but never writes the screenshot: the pre-created empty PNG must not count
		self._browser("lazy", "pass")
		self.assertIsNone(render_html_arglist("<html></html>", []))
		self.assertEqual(os.listdir(self.tmp), [])
	def test_success_uses_private_profile_each_time(self):
		log = os.path.join(self.work.name, "args.log")
		self._browser("fake_chrome", f"""
import sys
from PIL import Image
shot = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--screenshot=')][0]
prof = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--user-data-dir=')]
open({log!r}, 'a').write((prof[0] if prof else '') + '\\n')
Image.new('RGB', (8, 6), 'red').save(shot, 'PNG')
""")
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
		self._browser("failing", "import sys\nsys.exit(1)")
		with self.assertLogs(image_utils.logger, level="DEBUG") as cm:
			render_html_arglist("<html>SECRET-MARKER-XYZ</html>", [])
		self.assertNotIn("SECRET-MARKER-XYZ", "\n".join(cm.output))
	def test_async_render_does_not_block_the_loop(self):
		self._browser("sleeper", "import time\ntime.sleep(300)")
		async def go():
			ticks = 0
			stop = False
			async def ticker():
				nonlocal ticks
				while not stop:
					await asyncio.sleep(0.05)
					ticks += 1
			t = asyncio.create_task(ticker())
			with patch.object(image_utils, "CHROME_TIMEOUT_SECONDS", 1.0):
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

class TestRenderSlots(unittest.TestCase):
	"""How many Chromium renders run at once: one on a small board (a Chromium costs about 75 to 110 MB), two elsewhere, or what `EINK_RENDER_SLOTS` says."""
	@staticmethod
	def memory(megabytes: int):
		return patch.object(image_utils.psutil, "virtual_memory", return_value=SimpleNamespace(total=megabytes * 1024 * 1024))

	def test_a_small_board_renders_one_at_a_time_and_a_larger_one_two(self):
		env = { k: v for k, v in os.environ.items() if k != image_utils.RENDER_SLOTS_ENV }
		with patch.dict(os.environ, env, clear=True):
			for megabytes, slots in ((416, 1), (512, 1), (700, 1), (926, 2), (1900, 2), (8000, 2)):
				with self.subTest(megabytes), self.memory(megabytes):
					self.assertEqual(image_utils.render_slot_count(), slots)

	def test_the_environment_decides_when_it_says_a_number(self):
		with self.memory(512):
			for value, slots in (("3", 3), (" 2 ", 2), ("1", 1), ("0", 1), ("many", 1), ("-1", 1), ("", 1)):
				with self.subTest(value), patch.dict(os.environ, { image_utils.RENDER_SLOTS_ENV: value }):
					self.assertEqual(image_utils.render_slot_count(), slots)

	def test_a_machine_that_cannot_say_how_much_memory_it_has_gets_two(self):
		env = { k: v for k, v in os.environ.items() if k != image_utils.RENDER_SLOTS_ENV }
		with patch.dict(os.environ, env, clear=True), patch.object(image_utils.psutil, "virtual_memory", side_effect=OSError("no /proc")):
			self.assertEqual(image_utils.render_slot_count(), 2)

	def run_renders(self, slots: int, renders: int) -> int:
		"""The most renders that were running at once, with `slots` slots and `renders` threads asking."""
		running = [0]
		most = [0]
		lock = threading.Lock()
		def fake(source: str, arglist: list[str], timeout: float|None = None):
			with lock:
				running[0] += 1
				most[0] = max(most[0], running[0])
			time.sleep(0.15)
			with lock:
				running[0] -= 1
			return Image.new("RGB", (2, 2))
		with patch.object(image_utils, "_slots", threading.BoundedSemaphore(slots)), patch.object(image_utils, "_render_chrome_headless", fake):
			threads = [threading.Thread(target=image_utils.render_chrome_headless_arglist, args=("x.html", [])) for _ in range(renders)]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join()
		return most[0]

	def test_renders_wait_for_a_free_slot(self):
		self.assertEqual(self.run_renders(slots=1, renders=3), 1)
		self.assertEqual(self.run_renders(slots=2, renders=4), 2)

	def test_a_render_that_waited_too_long_gives_up(self):
		held = threading.BoundedSemaphore(1)
		held.acquire()
		with patch.object(image_utils, "_slots", held), patch.object(image_utils, "RENDER_SLOT_WAIT_SECONDS", 0.2):
			with self.assertLogs(image_utils.logger, level="ERROR") as logged:
				self.assertIsNone(image_utils.render_chrome_headless_arglist("x.html", []))
		self.assertTrue(any("free Chromium slot" in line for line in logged.output))

	def test_the_slot_comes_back_when_a_render_fails(self):
		slots = threading.BoundedSemaphore(1)
		def broken(source: str, arglist: list[str], timeout: float|None = None):
			raise RuntimeError("chromium")
		with patch.object(image_utils, "_slots", slots), patch.object(image_utils, "_render_chrome_headless", broken):
			with self.assertRaises(RuntimeError):
				image_utils.render_chrome_headless_arglist("x.html", [])
			self.assertTrue(slots.acquire(blocking=False), "the slot was not given back")



class TestPanelShape(unittest.TestCase):
	"""What the display does to a page before the panel: turned for the orientation, then made exactly the panel's size."""
	def test_orientation_turns_a_portrait_page_a_quarter(self):
		page = Image.new("RGB", (480, 800))
		page.putpixel((0, 0), (255, 0, 0))
		self.assertIs(change_orientation(page, "landscape"), page)
		turned = change_orientation(page, "portrait")
		self.assertEqual(turned.size, (800, 480))
		# a quarter counter-clockwise: the top-left corner goes to the bottom-left
		self.assertEqual(turned.getpixel((0, 479)), (255, 0, 0))
		self.assertEqual(change_orientation(page, "landscape", rotate180=True).getpixel((479, 799)), (255, 0, 0))
		with self.assertRaises(ValueError):
			change_orientation(page, "sideways")
	def test_resize_is_exact_and_crops_about_the_centre(self):
		page = Image.new("RGB", (100, 50), (0, 0, 255))
		page.paste((255, 0, 0), (45, 0, 55, 50))
		self.assertIs(resize_image(page, (100, 50)), page)
		out = resize_image(page, (50, 50))
		self.assertEqual(out.size, (50, 50))
		# the middle stays in the middle; the sides are what is cropped
		self.assertEqual(out.getpixel((25, 25)), (255, 0, 0))
		self.assertEqual(resize_image(page, (800, 480)).size, (800, 480))
