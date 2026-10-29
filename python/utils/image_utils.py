import asyncio
import io
import sys
import shutil
import signal
from typing import Any, Callable, Mapping

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from io import BytesIO
import os
import logging
import tempfile
import subprocess
import threading
from dataclasses import dataclass
import psutil
from dotenv import load_dotenv
from httpx import AsyncClient
from ..task.async_http_worker_pool import client_var
from .url_guard import stream_checked

logger = logging.getLogger(__name__)

# a download larger than this is refused (an image for an e-Ink display never needs more)
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
# a Chromium render that takes longer than this is killed
CHROME_TIMEOUT_SECONDS = 60.0
# how many Chromium renders may run at once in this process (the layers each render on their own thread). One Chromium costs about 75 to 110 MB, so a small board does one at a time;
# `EINK_RENDER_SLOTS` says otherwise. A render that has waited this long for a slot gives up, as a render that takes too long does.
RENDER_SLOTS_ENV = "EINK_RENDER_SLOTS"
SMALL_MEMORY_BYTES = 800 * 1024 * 1024
RENDER_SLOT_WAIT_SECONDS = 180.0

@dataclass(frozen=True)
class Downloaded:
	"""What `download` got: the status (200, or 304 for a conditional request the origin answered with "not modified"), the headers, and the body (None for a 304)."""
	status: int
	headers: Mapping[str, str]
	body: BytesIO|None

async def download(client: AsyncClient, url: str, headers: Mapping[str, str]|None = None, ctok: Callable[[str], bool]|None = None, max_bytes: int|None = DEFAULT_MAX_DOWNLOAD_BYTES, guarded: bool = True, conditional: bool = False) -> Downloaded:
	"""
	Download `url` into memory; refuse (RuntimeError) more than `max_bytes`, checked up front (Content-Length) and while streaming. None disables the cap.
	`guarded` (the default) checks the address and every redirect with `url_guard` (not this device, not link-local, ...): the address is usually taken
	from a feed or an answer. `guarded=False` is only for an address that is our own constant.
	`conditional` says `headers` hold `If-None-Match` or `If-Modified-Since`: a 304 is then an answer (no body), not an error.
	"""
	opener = stream_checked(client, "GET", url, headers) if guarded else client.stream("GET", url, headers=headers, follow_redirects=True)
	async with opener as resp:
		if conditional and resp.status_code == 304:
			return Downloaded(304, dict(resp.headers), None)
		resp.raise_for_status()
		ct = resp.headers.get("Content-Type", "")
		if ctok and not ctok(ct):
			raise RuntimeError(f"Unexpected content type: '{ct}'.")
		if max_bytes is not None:
			try:
				declared = int(resp.headers.get("Content-Length", ""))
			except ValueError:
				declared = None
			if declared is not None and declared > max_bytes:
				raise RuntimeError(f"Download too large: {declared} bytes (limit {max_bytes}).")
		buffer = io.BytesIO()
		async for chunk in resp.aiter_bytes():
			buffer.write(chunk)
			if max_bytes is not None and buffer.tell() > max_bytes:
				raise RuntimeError(f"Download too large: more than {max_bytes} bytes.")
		buffer.seek(0)
		return Downloaded(resp.status_code, dict(resp.headers), buffer)

async def stream_to_buffer(client: AsyncClient, url: str, headers: Mapping[str, str]|None = None, ctok: Callable[[str], bool]|None = None, max_bytes: int|None = DEFAULT_MAX_DOWNLOAD_BYTES, guarded: bool = True) -> BytesIO:
	"""`download`'s body: the way a data source gets a picture or a feed with nothing kept (see `datasources/content_cache.py` for one that is kept)."""
	got = await download(client, url, headers, ctok, max_bytes, guarded)
	assert got.body is not None
	return got.body

async def get_image_async(image_url:str) -> Image.Image | None:
	client = client_var.get()
	buffer = await stream_to_buffer(client, image_url, ctok=lambda ct: ct.startswith("image/"))
	img = Image.open(buffer)
	# Image.open is lazy: decode now so a truncated/corrupt body fails here, where the caller can handle it
	img.load()
	return img

def to_rgb(img: Image.Image) -> Image.Image:
	"""
	Return `img` as RGB (or leave it when it already is RGB or L): palette, bilevel and CMYK images do not support the
	filters and enhancements we apply. Transparency is composited onto white (e-Ink "paper"), not dropped to black.
	"""
	if img.mode in ("RGB", "L"):
		return img
	if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
		rgba = img.convert("RGBA")
		background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
		return Image.alpha_composite(background, rgba).convert("RGB")
	return img.convert("RGB")

def keep_as_jpeg(img: Image.Image) -> bytes:
	"""A picture as the Gallery keeps it: a JPEG at high quality (a drawn picture or a photograph; a PNG of it would be several times as large).
	One encoder for every way in (a producer, an upload, a page's original the display kept), so the same picture is the same bytes and is kept once."""
	out = io.BytesIO()
	to_rgb(img).save(out, "JPEG", quality=92)
	return out.getvalue()

def blurred_margin(img: Image.Image, size: tuple[int, int], enlarge: bool = True) -> Image.Image:
	"""
	`img` fitted inside `size` (the whole picture, never cropped, the aspect ratio kept) and centred on a blurred, enlarged copy of itself, so the margin
	is the picture's own colors, not white bars. The one way a data source fills the margin of a picture whose shape is not the panel's.
	`enlarge=False` leaves a picture that is smaller than `size` at its own size. The blur grows with the canvas (8 pixels on a 480 pixel side).
	"""
	size = (max(1, size[0]), max(1, size[1]))
	img = to_rgb(img)
	if img.size == size:
		return img
	scale = min(size[0] / img.width, size[1] / img.height)
	if enlarge or scale < 1:
		img = ImageOps.contain(img, size, Image.Resampling.LANCZOS)
	canvas = ImageOps.fit(img, size).filter(ImageFilter.BoxBlur(max(1, round(min(size) / 60))))
	canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
	return canvas

# how far a page is turned for the panel, by the display's orientation (a portrait page is turned a quarter counter-clockwise)
ORIENTATION_DEGREES = { "landscape": 0, "portrait": 90 }

def change_orientation(image: Image.Image, orientation: str, rotate180=False) -> Image.Image:
	"""The page as the panel takes it: turned for the orientation, and half a turn more for a panel mounted upside down."""
	if orientation not in ORIENTATION_DEGREES:
		raise ValueError(f"Invalid orientation: {orientation}")
	degrees = (ORIENTATION_DEGREES[orientation] + (180 if rotate180 else 0)) % 360
	return image if degrees == 0 else image.rotate(degrees, expand=True)

def resize_image(image: Image.Image, desired_size: tuple[int, int]) -> Image.Image:
	"""Exactly `desired_size`: scaled to cover it and cropped about the centre (a page is already the panel's shape, so this only trims a pixel or two)."""
	size = (int(desired_size[0]), int(desired_size[1]))
	if image.size == size:
		return image
	return ImageOps.fit(image, size, Image.Resampling.LANCZOS)

# the display's picture settings, in the order they are applied, each with the PIL enhancer it drives; 1.0 (or unset) leaves a picture as it is
ENHANCEMENTS = (
	("imageSettings-brightness", ImageEnhance.Brightness),
	("imageSettings-contrast", ImageEnhance.Contrast),
	("imageSettings-saturation", ImageEnhance.Color),
	("imageSettings-sharpness", ImageEnhance.Sharpness),
)

def apply_image_enhancement(img: Image.Image, image_settings: Mapping[str,Any]|None) -> Image.Image:
	"""The picture with the display's picture settings applied; the same object when none of them changes anything."""
	steps = [(enhancer, factor) for key, enhancer in ENHANCEMENTS if (factor := (image_settings or {}).get(key)) is not None and factor != 1.0]
	if not steps:
		return img
	# ImageEnhance fails on palette ('P') and bilevel ('1') frames
	img = to_rgb(img)
	for enhancer, factor in steps:
		img = enhancer(img).enhance(factor)
	return img

def _remove_quietly(path: str|None) -> None:
	if path:
		try:
			os.remove(path)
		except FileNotFoundError:
			pass
		except OSError as e:
			logger.warning(f"Could not remove temporary file: {e}")

def render_html_arglist(html_str: str, arglist: list[str]) -> Image.Image | None:
	"""Render HTML to an image with headless Chromium. Blocking: from async code use render_html_arglist_async."""
	# Chromium opens a page from a file: the page is written to one of its own, removed afterwards whatever happens
	fd, page_path = tempfile.mkstemp(suffix=".html")
	try:
		with os.fdopen(fd, "wb") as page:
			page.write(html_str.encode("utf-8"))
		logger.debug(f"render html ({len(html_str)} chars)")
		return render_chrome_headless_arglist(page_path, arglist)
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")
		return None
	finally:
		_remove_quietly(page_path)

async def render_html_arglist_async(html_str: str, arglist: list[str]) -> Image.Image | None:
	"""Same as render_html_arglist, run in a worker thread so the event loop keeps running while Chromium works."""
	return await asyncio.to_thread(render_html_arglist, html_str, arglist)

# the headless shell, never a regular Chrome (which draws a page differently); the browser by its name on PATH; a machine that keeps it elsewhere says where in `EINK_CHROME` (the environment, or a `.env` file: see `.env.example`)
WIN_CHROME_HEADLESS = "chrome-headless-shell"
LINUX_CHROME_HEADLESS = "chromium-headless-shell"
CHROME_ENV = "EINK_CHROME"

_env_file_read = False
_missing_chrome: set[str] = set()

def chrome_command() -> str:
	"""
	The headless browser to run: `EINK_CHROME` (a path, or a name on `PATH`) when it is set, in the environment or in the repository's `.env` file,
	else the platform's usual name on `PATH`. Read on every render, so a test or a developer can point it elsewhere.
	"""
	global _env_file_read
	if not _env_file_read:
		_env_file_read = True
		# a `.env` beside the source tree (never one the environment already answers: a real variable wins)
		load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))
	default = WIN_CHROME_HEADLESS if sys.platform == "win32" else LINUX_CHROME_HEADLESS
	configured = os.environ.get(CHROME_ENV)
	if not configured:
		return default
	# a path that is not here is no use on this machine (a `.env` made on Windows, seen from a container that mounts the checkout): the usual name is tried
	if shutil.which(configured) is None:
		if configured not in _missing_chrome:
			_missing_chrome.add(configured)
			logger.warning(f"{CHROME_ENV} names a browser that is not here, using '{default}' instead.")
		return default
	return configured

def _kill_process_tree(proc: subprocess.Popen) -> None:
	"""Kill the child and everything it started (Chromium spawns helper processes)."""
	try:
		# sys.platform: the type checker narrows on it, and the POSIX calls exist only on the other branch
		if sys.platform == "win32":
			subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
		else:
			os.killpg(proc.pid, signal.SIGKILL)
	except Exception:
		pass
	try:
		proc.kill()
	except Exception:
		pass

_slots: threading.BoundedSemaphore|None = None
_slots_lock = threading.Lock()

def render_slot_count() -> int:
	"""How many renders may run at once: `EINK_RENDER_SLOTS` when it is a whole number of 1 or more, else 1 on a board with less than about 1 GB (a Pi Zero 2 W or 3 A+: 512 MB) and 2 elsewhere."""
	configured = (os.environ.get(RENDER_SLOTS_ENV) or "").strip()
	if configured.isdigit() and int(configured) >= 1:
		return int(configured)
	try:
		total = psutil.virtual_memory().total
	except Exception:
		return 2
	return 1 if total < SMALL_MEMORY_BYTES else 2

def _render_slots() -> threading.BoundedSemaphore:
	global _slots
	with _slots_lock:
		if _slots is None:
			count = render_slot_count()
			logger.info(f"Chromium renders at once: {count}")
			_slots = threading.BoundedSemaphore(count)
		return _slots

# the fontconfig file the renderer starts with: text without antialiasing (see the file)
FONTS_CONF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "render", "fonts.conf")

# How every page is rendered, besides its own size (the caller's arguments): what each group is for
CHROME_FLAGS = (
	# a screenshot of the page, with no window and nothing around it
	"--headless=new", "--hide-scrollbars",
	# no GPU on a Pi: draw in software, in the one process, and keep shared memory small (a container's /dev/shm is 64 MB)
	"--disable-gpu", "--use-gl=swiftshader", "--in-process-gpu", "--disable-zero-copy", "--disable-gpu-memory-buffer-compositor-resources", "--disable-dev-shm-usage",
	# text is drawn in one colour (a subpixel fringe would be dithered on the panel); fontconfig turns the antialiasing off (`FONTS_CONF`)
	"--disable-lcd-text",
	# a page runs no script and needs nothing else (plugin.html's Content-Security-Policy); a JIT costs memory and buys nothing
	"--js-flags=--jitless", "--disable-extensions", "--disable-plugins", "--mute-audio",
	# Chromium's sandbox needs privileges the service does not have; the page can do nothing (no script, no network)
	"--no-sandbox",
)

# The kernel's out-of-memory killer takes the highest score first: a render is the one to lose, never the app (#568).
# Written by a shell that then becomes Chromium (exec), so every helper Chromium forks inherits it; raising one's own score needs no privilege. Where /proc is not there it is skipped.
CHROME_OOM_SCORE_ADJ = 1000
_OOM_WRAPPER = f'echo {CHROME_OOM_SCORE_ADJ} 2>/dev/null >/proc/self/oom_score_adj; exec "$@"'

def _oom_kills() -> int|None:
	"""How many of this cgroup's processes the out-of-memory killer has killed (cgroup v2's `memory.events`; a container's own cgroup is its root), None where it cannot be read."""
	if sys.platform != "linux":
		return None
	try:
		with open("/proc/self/cgroup", encoding="utf-8") as f:
			group = next((line.strip()[3:] for line in f if line.startswith("0::")), None)
		if group is None:
			return None
		with open(os.path.join("/sys/fs/cgroup", group.lstrip("/"), "memory.events"), encoding="utf-8") as f:
			for line in f:
				key, _, value = line.partition(" ")
				if key == "oom_kill":
					return int(value)
	except (OSError, ValueError):
		pass
	return None

def render_chrome_headless_arglist(source_html_path: str, arglist: list[str], timeout: float|None = None):
	"""Render the page with headless Chromium, when one of the render slots is free (see `render_slot_count`). None when it failed, timed out, or no slot came free."""
	slots = _render_slots()
	if not slots.acquire(timeout=RENDER_SLOT_WAIT_SECONDS):
		logger.error(f"Render gave up after waiting {RENDER_SLOT_WAIT_SECONDS:g} seconds for a free Chromium slot.")
		return None
	try:
		return _render_chrome_headless(source_html_path, arglist, timeout)
	finally:
		slots.release()

def _render_chrome_headless(source_html_path: str, arglist: list[str], timeout: float|None = None):
	image = None
	img_file_path = None
	profile_dir = None
	timeout = CHROME_TIMEOUT_SECONDS if timeout is None else timeout
	try:
		# Output file for the screenshot (mkstemp creates it empty: success is judged by its size)
		fd, img_file_path = tempfile.mkstemp(suffix=".png")
		os.close(fd)
		# every render gets its own profile so concurrent renders do not share (and lock) one
		profile_dir = tempfile.mkdtemp(prefix="eink-chrome-")
		command = [chrome_command(), source_html_path, f"--screenshot={img_file_path}", f"--user-data-dir={profile_dir}", *CHROME_FLAGS, *arglist]
		# declared before the branch: the type checker reads only this platform's branch
		popen_kwargs: dict[str, Any]
		if sys.platform == "win32":
			popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
		else:
			# own session/process group, so the whole tree can be killed; Chromium's text rendering is fontconfig's, so it gets ours (Windows has no fontconfig: the panel never runs there)
			popen_kwargs = {"start_new_session": True, "env": { **os.environ, "FONTCONFIG_FILE": FONTS_CONF }}
			command = ["/bin/sh", "-c", _OOM_WRAPPER, "sh", *command]
		oom_before = _oom_kills()
		proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kwargs)
		try:
			_, stderr = proc.communicate(timeout=timeout)
		except subprocess.TimeoutExpired:
			logger.error(f"Render timed out after {timeout} seconds; killing Chromium.")
			_kill_process_tree(proc)
			try:
				proc.communicate(timeout=5)
			except Exception:
				pass
			return None

		# Check if the process failed or the output file is missing/empty
		if proc.returncode != 0 or not os.path.exists(img_file_path) or os.path.getsize(img_file_path) == 0:
			# our timeout has already returned: a SIGKILL now is the kernel's, and the counter also sees a helper killed while the browser lived on
			oom_after = _oom_kills()
			if oom_before is not None and oom_after is not None and oom_after > oom_before:
				logger.error(f"Failed to render: out of memory, the kernel killed Chromium (exit code {proc.returncode}).")
			elif sys.platform != "win32" and proc.returncode == -signal.SIGKILL:
				logger.error("Failed to render: Chromium was killed (SIGKILL), most likely out of memory.")
			else:
				logger.error(f"Failed to render (exit code {proc.returncode}):")
			logger.error(stderr.decode('utf-8', errors='replace'))
			return None

		# a copy, so the file is closed (and can be removed) before the picture is used
		with Image.open(img_file_path) as screenshot:
			image = screenshot.copy()
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")
	finally:
		_remove_quietly(img_file_path)
		if profile_dir:
			shutil.rmtree(profile_dir, ignore_errors=True)

	return image
