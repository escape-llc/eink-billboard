import asyncio
import io
import platform
import shutil
import signal
from typing import Any, Callable, Mapping

from PIL import Image, ImageEnhance
from io import BytesIO
import os
import logging
import hashlib
import tempfile
import subprocess
from httpx import AsyncClient
from ..task.async_http_worker_pool import client_var

logger = logging.getLogger(__name__)

# a download larger than this is refused (an image for an e-Ink display never needs more)
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
# a Chromium render that takes longer than this is killed
CHROME_TIMEOUT_SECONDS = 60.0

async def stream_to_buffer(client: AsyncClient, url: str, headers: Mapping[str, str]|None = None, ctok: Callable[[str], bool]|None = None, max_bytes: int|None = DEFAULT_MAX_DOWNLOAD_BYTES) -> BytesIO:
	"""Download `url` into memory; refuse (RuntimeError) more than `max_bytes`, checked up front (Content-Length) and while streaming. None disables the cap."""
	async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
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
		return buffer

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

def resize_image(image: Image.Image, desired_size: tuple[int, int], image_settings: list[str] = []) -> Image.Image:
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
WIN_CHROME_HEADLESS = "C:\\Users\\Public\\chrome-headless-shell-win64\\chrome-headless-shell.exe"
LINUX_CHROME_HEADLESS = "chromium-headless-shell"

def _kill_process_tree(proc: subprocess.Popen) -> None:
	"""Kill the child and everything it started (Chromium spawns helper processes)."""
	try:
		if os_type == "Windows":
			subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
		else:
			os.killpg(proc.pid, signal.SIGKILL)
	except Exception:
		pass
	try:
		proc.kill()
	except Exception:
		pass

def render_chrome_headless_arglist(source_html_path: str, arglist: list[str], timeout: float|None = None):
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
			# TODO by OS platform from .env.xxx file
			WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS,
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
		if os_type == "Windows":
			popen_kwargs: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP")}
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
