"""
A picture that came from outside (the push API's `POST /api/display/image`, an Image URL data source's download): checked before anything is decoded in full, then fitted to the panel. The sender is whoever has the token, so
the body is treated as untrusted anyway: the size is bounded, only a few picture formats are taken (found by their content, never the name or the type the sender claims), the number of pixels is
bounded before the picture is loaded (a small file can hold a huge picture), and only the first frame of an animation is used. Every refusal is a `ValueError` in our words.
"""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from .image_utils import blurred_margin, to_rgb

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# a 8000 x 5000 photograph; a bigger picture is refused before it is decoded
MAX_UPLOAD_PIXELS = 40_000_000
FORMATS = ("PNG", "JPEG", "GIF", "WEBP")

def open_picture(data: bytes) -> Image.Image:
	"""The picture in `data`, checked and decoded (a `ValueError` in our words when it cannot be used): its first frame, a phone's rotation applied, not yet fitted to anything."""
	if not data:
		raise ValueError("There is no picture in the request.")
	if len(data) > MAX_UPLOAD_BYTES:
		raise ValueError(f"The picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
	try:
		picture = Image.open(io.BytesIO(data))
		picture_format = picture.format
		width, height = picture.size
	except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
		raise ValueError("That is not a picture the device can use (PNG, JPEG, GIF or WEBP).") from None
	if picture_format not in FORMATS:
		raise ValueError("That is not a picture the device can use (PNG, JPEG, GIF or WEBP).")
	if width * height > MAX_UPLOAD_PIXELS:
		raise ValueError(f"The picture has more than {MAX_UPLOAD_PIXELS // 1_000_000} million pixels: make it smaller.")
	try:
		# only the first frame of an animation; a phone's rotation is applied
		picture.seek(0)
		picture.load()
		upright = ImageOps.exif_transpose(picture) or picture
		return to_rgb(upright)
	except (OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError):
		raise ValueError("The picture is damaged, or cannot be read.") from None

def decode_upload(data: bytes, size: tuple[int, int]) -> Image.Image:
	"""The picture in `data` as an RGB image of exactly `size`: the whole picture, never cropped, on a blurred margin of its own colors (`blurred_margin`)."""
	return blurred_margin(open_picture(data), size).convert("RGB")
