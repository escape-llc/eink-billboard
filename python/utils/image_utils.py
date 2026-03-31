import io
import platform

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

async def stream_to_buffer(client: AsyncClient, url: str, headers: dict[str, str]|None = None) -> BytesIO:
	async with client.stream("GET", url, headers=headers) as resp:
		resp.raise_for_status()
		buffer = io.BytesIO()
		async for chunk in resp.aiter_bytes():
			buffer.write(chunk)
		buffer.seek(0)
		return buffer

async def get_image_async(image_url:str) -> Image.Image | None:
	client = client_var.get()
	buffer = await stream_to_buffer(client, image_url)
	img = Image.open(buffer)
	return img

def change_orientation(image, orientation, rotate180=False):
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

def apply_image_enhancement(img: Image.Image, image_settings: dict|None) -> Image.Image:
	if image_settings is None:
		return img

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

def render_html_arglist(html_str: str, arglist: list[str]) -> Image.Image | None:
	image = None
	try:
		logger.debug(f"{html_str}")
		with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
			html_file.write(html_str.encode("utf-8"))
			html_file_path = html_file.name

		image = render_chrome_headless_arglist(html_file_path, arglist)
		os.remove(html_file_path)
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")
	return image

# DO NOT USE regular Chrome it does not render correctly
os_type = platform.system()
WIN_CHROME_HEADLESS = "C:\\Users\\Public\\chrome-headless-shell-win64\\chrome-headless-shell.exe"
LINUX_CHROME_HEADLESS = "chromium-headless-shell"

def render_chrome_headless_arglist(source_html_path: str, arglist: list[str]):
	image = None
	try:
		# Output file for the screenshot
		with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
			img_file_path = img_file.name
		command = [
			# TODO by OS platform from .env.xxx file
			WIN_CHROME_HEADLESS if os_type == "Windows" else LINUX_CHROME_HEADLESS,
			source_html_path,
			"--headless=new",
			f"--screenshot={img_file_path}",
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
		result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		# Check if the process failed or the output file is missing
		if result.returncode != 0 or not os.path.exists(img_file_path):
			logger.error("Failed to render:")
			logger.error(result.stderr.decode('utf-8'))
			return None

		# Load the image using PIL
		with Image.open(img_file_path) as img:
			image = img.copy()

		# Remove image files
		os.remove(img_file_path)
	except Exception as e:
		logger.error(f"Failed to render: {str(e)}")

	return image
