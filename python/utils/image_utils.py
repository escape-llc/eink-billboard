import asyncio
import io
import platform
import sys
import shutil
import signal
from typing import Any, Callable, Mapping, Sequence

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from io import BytesIO
import os
import logging
import hashlib
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

def change_orientation(image: Image.Image, orientation: str, rotate180=False) -> Image.Image:
	if orientation == 'landscape':
		angle = 0
	elif orientation == 'portrait':
		angle = 90
	else:
		raise ValueError(f"Invalid orientation: {orientation}")

	if rotate180:
		angle = (angle + 180) % 360
	if angle == 0:
		return image
	return image.rotate(angle, expand=1)

def resize_image(image: Image.Image, desired_size: tuple[int, int], image_settings: Sequence[str] = ()) -> Image.Image:
	img_width, img_height = image.size
	desired_width, desired_height = desired_size
	desired_width, desired_height = int(desired_width), int(desired_height)

	if img_width == desired_width and img_height == desired_height:
		return image

	img_ratio = img_width / img_height
	desired_ratio = desired_width / desired_height

	keep_width = "keep-width" in image_settings

	x_offset, y_offset = 0,0
	new_width, new_height = img_width,img_height
	# Step 1: Determine crop dimensions
	desired_ratio = desired_width / desired_height
	if img_ratio > desired_ratio:
		# Image is wider than desired aspect ratio
		new_width = int(img_height * desired_ratio)
		if not keep_width:
			x_offset = (img_width - new_width) // 2
	else:
		# Image is taller than desired aspect ratio
		new_height = int(img_width / desired_ratio)
		if not keep_width:
			y_offset = (img_height - new_height) // 2

	# Step 2: Crop the image
	image = image.crop((x_offset, y_offset, x_offset + new_width, y_offset + new_height))

	# Step 3: Resize to the exact desired dimensions (if necessary)
	return image.resize((desired_width, desired_height), Image.Resampling.LANCZOS)

def apply_image_enhancement(img: Image.Image, image_settings: Mapping[str,Any]|None) -> Image.Image:
	if image_settings is None:
		return img

	keys = ("imageSettings-brightness", "imageSettings-contrast", "imageSettings-saturation", "imageSettings-sharpness")
	if all(image_settings.get(k, None) in (None, 1.0) for k in keys):
		return img
	# ImageEnhance fails on palette ('P') and bilevel ('1') frames
	img = to_rgb(img)

	brightness = image_settings.get("imageSettings-brightness", None)
	if brightness is not None and brightness != 1.0:
		# Apply Brightness
		img = ImageEnhance.Brightness(img).enhance(brightness)

	contrast = image_settings.get("imageSettings-contrast", None)
	if contrast is not None and contrast != 1.0:
		# Apply Contrast
		img = ImageEnhance.Contrast(img).enhance(contrast)

	saturation = image_settings.get("imageSettings-saturation", None)
	if saturation is not None and saturation != 1.0:
		# Apply Saturation (Color)
		img = ImageEnhance.Color(img).enhance(saturation)

	sharpness = image_settings.get("imageSettings-sharpness", None)
	if sharpness is not None and sharpness != 1.0:
		# Apply Sharpness
		img = ImageEnhance.Sharpness(img).enhance(sharpness)

	return img

def compute_image_hash(image: Image.Image) -> str:
	"""Compute SHA-256 hash of an image."""
	image = image.convert("RGB")
	img_bytes = image.tobytes()
	return hashlib.sha256(img_bytes).hexdigest()

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
	image = None
	html_file_path = None
	try:
		logger.debug(f"render html ({len(html_str)} chars)")
		with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
			html_file_path = html_file.name
			html_file.write(html_str.encode("utf-8"))
		image = render_chrome_headless_arglist(html_file_path, arglist)
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")
	finally:
		_remove_quietly(html_file_path)
	return image

async def render_html_arglist_async(html_str: str, arglist: list[str]) -> Image.Image | None:
	"""Same as render_html_arglist, run in a worker thread so the event loop keeps running while Chromium works."""
	return await asyncio.to_thread(render_html_arglist, html_str, arglist)

# DO NOT USE regular Chrome it does not render correctly
os_type = platform.system()
# the browser by its name on PATH; a machine that keeps it elsewhere says where in `EINK_CHROME` (the environment, or a `.env` file: see `.env.example`)
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
	default = WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS
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
		# sys.platform, not os_type: the type checker narrows on it, and the POSIX calls exist only on the other branch
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
		command = [
			chrome_command(),
			source_html_path,
			"--headless=new",
			f"--screenshot={img_file_path}",
			f"--user-data-dir={profile_dir}",
			"--disable-dev-shm-usage",
			"--disable-gpu",
			"--use-gl=swiftshader",
			"--hide-scrollbars",
			"--in-process-gpu",
			"--js-flags=--jitless",
			"--disable-zero-copy",
			"--disable-gpu-memory-buffer-compositor-resources",
			"--disable-extensions",
			"--disable-plugins",
			"--mute-audio",
			"--no-sandbox"
		]
		command.extend(arglist)
		# declared before the branch: the type checker reads only this platform's branch
		popen_kwargs: dict[str, Any]
		if sys.platform == "win32":
			popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
		else:
			# own session/process group, so the whole tree can be killed
			popen_kwargs = {"start_new_session": True}
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
			logger.error(f"Failed to render (exit code {proc.returncode}):")
			logger.error(stderr.decode('utf-8', errors='replace'))
			return None

		# Load the image using PIL
		with Image.open(img_file_path) as img:
			image = img.copy()
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")
	finally:
		_remove_quietly(img_file_path)
		if profile_dir:
			shutil.rmtree(profile_dir, ignore_errors=True)

	return image
