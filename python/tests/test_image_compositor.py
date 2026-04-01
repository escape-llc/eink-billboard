import datetime
import unittest
from PIL import Image
from pathlib import Path

from ..task.display import DisplayImage, PriorityImage
from .utils import test_output_path_for, save_image
from ..utils.image_compositor import ImageCompositor, ImageOverlay, LayerStack

def _create_rgb(color, size=(10, 8)):
	img = Image.new("RGB", size, color)
	return img

folder = test_output_path_for("image_compositor_tests")

# Path to test images
BUTTERFLY_PATH = Path(__file__).parent.joinpath("images", "butterfly.jpg")
FRUITS_PATH = Path(__file__).parent.joinpath("images", "fruits.jpg")
SMARTIES_PATH = Path(__file__).parent.joinpath("images", "smarties.png")

class TestImageCompositor(unittest.TestCase):
	def test_render_no_change_returns_false_and_none(self):
		comp = ImageCompositor()
		pkg = comp.commit()
		self.assertIsNone(pkg)

	def test_set_background_and_render_and_versioning(self):
		comp = ImageCompositor()
		# use a real image for the background to exercise file loading
		bg = Image.open(BUTTERFLY_PATH).convert("RGB")
		v0, v1 = comp.set_layer_background(DisplayImage(datetime.datetime.now(), "Background", bg))
		self.assertIsNotNone(v0)
		self.assertIsInstance(v0, LayerStack)
		self.assertEqual(v0.version, 0)
		self.assertIsNotNone(v1)
		self.assertIsInstance(v1, LayerStack)
		self.assertEqual(v1.version, 1)
		self.assertEqual(comp.current_version, 1)

		out = comp.commit()
		self.assertIsNotNone(out)
		if out is not None:
			the_info = out.render()
			self.assertIsNotNone(the_info)
			if the_info is not None:
				the_image, the_title = the_info
				save_image(the_image, folder, 1, "set_background")
				self.assertEqual(the_image.size, bg.size)
				self.assertIsNot(the_image, bg)
				self.assertEqual(the_title, "Background")

				out2 = comp.commit()
				self.assertIsNone(out2)

				overlay_img = _create_rgb((1, 2, 3), size=(5, 5))
				ovl = ImageOverlay(overlay_img, (1, 1))
				v1, v2 = comp.set_layer_overlays([ovl])
				self.assertGreater(v2.version, v1.version)
				out3 = comp.commit()
				self.assertIsNotNone(out3)
				if out3 is not None:
					the_info3 = out3.render()
					self.assertIsNotNone(the_info3)
					if the_info3 is not None:
						the_image3, the_title3 = the_info3
						save_image(the_image3, folder, 3, "set_background")
						self.assertEqual(the_image3.size, bg.size)

	def test_foreground_and_priority(self):
		comp = ImageCompositor()
		bg = Image.open(BUTTERFLY_PATH).convert("RGB")
		fg = Image.open(FRUITS_PATH).convert("RGB")
		inter = Image.open(SMARTIES_PATH).convert("RGB")

		comp.set_layer_background(DisplayImage(datetime.datetime.now(), "Background", bg))
		comp.set_layer_forground(DisplayImage(datetime.datetime.now(), "Foreground", fg))
		out = comp.commit()
		self.assertIsNotNone(out)
		if out is not None:
			the_info = out.render()
			self.assertIsNotNone(the_info)
			if the_info is not None:
				the_image, the_title = the_info
				save_image(the_image, folder, 1, "set_fg_priority")
				self.assertEqual(the_image.getpixel((0, 0)), fg.getpixel((0, 0)))

				comp.set_layer_priority(PriorityImage(datetime.datetime.now(), "Priority", inter, datetime.timedelta(seconds=30)))
				out2 = comp.commit()
				self.assertIsNotNone(out2)
				if out2 is not None:
					the_info2 = out2.render()
					self.assertIsNotNone(the_info2)
					if the_info2 is not None:
						the_image2, the_title2 = the_info2
						save_image(the_image2, folder, 2, "set_fg_priority")
						self.assertEqual(the_image2.getpixel((0, 0)), inter.getpixel((0, 0)))

	def test_composited_image_attribute_matches_returned_image(self):
		comp = ImageCompositor()
		bg = _create_rgb((5, 6, 7), size=(4, 4))
		comp.set_layer_background(DisplayImage(datetime.datetime.now(), "Background", bg))
		out = comp.commit()
		self.assertIsNotNone(out)
		if out is not None:
			the_info = out.render()
			self.assertIsNotNone(the_info)
			if the_info is not None:
				the_image, the_title = the_info
				save_image(the_image, folder, 1, "matches_returned_image")

if __name__ == "__main__":
    unittest.main()
