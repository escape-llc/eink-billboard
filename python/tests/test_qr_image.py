import base64
import io
import unittest

import segno
from PIL import Image

from ..utils.qr_image import QUIET_ZONE, qr_data_uri

URL = "http://192.168.1.100:8080/#/claim/12345678"

def decode(uri: str) -> Image.Image:
	prefix = "data:image/png;base64,"
	assert uri.startswith(prefix)
	return Image.open(io.BytesIO(base64.b64decode(uri[len(prefix):]))).convert("RGB")

class TestQrImage(unittest.TestCase):
	def test_it_is_black_and_white_only_and_fits_the_box(self):
		for box in (150, 288, 400):
			with self.subTest(box=box):
				image = decode(qr_data_uri(URL, box))
				self.assertLessEqual(max(image.size), box)
				self.assertEqual({ color for _, color in image.getcolors() }, { (0, 0, 0), (255, 255, 255) })

	def test_a_module_is_a_whole_number_of_pixels(self):
		modules, _ = segno.make(URL, error="m").symbol_size(scale=1, border=QUIET_ZONE)
		image = decode(qr_data_uri(URL, 288))
		self.assertEqual(image.width % modules, 0)
		self.assertEqual(image.width, image.height)

	def test_it_carries_the_text(self):
		"""Each module of the picture is the code's own: read back at one pixel a module, it is the matrix of the same text."""
		image = decode(qr_data_uri(URL, 288))
		modules, _ = segno.make(URL, error="m").symbol_size(scale=1, border=QUIET_ZONE)
		scale = image.width // modules
		matrix = segno.make(URL, error="m").matrix
		for y, row in enumerate(matrix):
			for x, dark in enumerate(row):
				pixel = image.getpixel(((x + QUIET_ZONE) * scale + scale // 2, (y + QUIET_ZONE) * scale + scale // 2))
				self.assertEqual(pixel == (0, 0, 0), bool(dark))

	def test_a_tiny_box_still_gets_two_pixels_a_module(self):
		modules, _ = segno.make(URL, error="m").symbol_size(scale=1, border=QUIET_ZONE)
		self.assertEqual(decode(qr_data_uri(URL, 10)).width, 2 * modules)
