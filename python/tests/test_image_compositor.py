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

def _di(title, img):
	return DisplayImage(datetime.datetime.now(), title, img)

class TestOverlays(unittest.TestCase):
	def _render(self, comp):
		package = comp.commit()
		self.assertIsNotNone(package)
		assert package is not None
		return package.render()

	def test_overlay_is_drawn_at_its_position_only(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((10, 20, 30), size=(20, 20))))
		comp.set_layer_overlays([ImageOverlay(_create_rgb((200, 0, 0), size=(5, 4)), (3, 6))])
		image, title = self._render(comp)
		save_image(image, folder, 10, "overlay_position")
		self.assertEqual(image.size, (20, 20))
		self.assertEqual(image.mode, "RGB")
		self.assertEqual(title, "Background")
		self.assertEqual(image.getpixel((3, 6)), (200, 0, 0))
		self.assertEqual(image.getpixel((7, 9)), (200, 0, 0))
		self.assertEqual(image.getpixel((2, 6)), (10, 20, 30))
		self.assertEqual(image.getpixel((8, 9)), (10, 20, 30))
		self.assertEqual(image.getpixel((3, 10)), (10, 20, 30))

	def test_transparent_overlay_pixels_show_the_background(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((10, 20, 30), size=(10, 10))))
		box = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
		box.putpixel((1, 1), (255, 255, 255, 255))
		comp.set_layer_overlays([ImageOverlay(box, (2, 2))])
		image, _ = self._render(comp)
		self.assertEqual(image.getpixel((3, 3)), (255, 255, 255))
		self.assertEqual(image.getpixel((2, 2)), (10, 20, 30))

	def test_overlay_hanging_off_the_edge_is_clipped(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((10, 10, 10), size=(10, 10))))
		comp.set_layer_overlays([
			ImageOverlay(_create_rgb((255, 0, 0), size=(6, 6)), (7, 7)),
			ImageOverlay(_create_rgb((0, 255, 0), size=(6, 6)), (-4, -4)),
			ImageOverlay(_create_rgb((0, 0, 255), size=(3, 3)), (50, 50)),
		])
		image, _ = self._render(comp)
		self.assertEqual(image.size, (10, 10))
		self.assertEqual(image.getpixel((9, 9)), (255, 0, 0))
		self.assertEqual(image.getpixel((0, 0)), (0, 255, 0))
		self.assertEqual(image.getpixel((5, 5)), (10, 10, 10))

	def test_overlays_are_drawn_in_order(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((0, 0, 0), size=(10, 10))))
		comp.set_layer_overlays([ImageOverlay(_create_rgb((255, 0, 0), size=(5, 5)), (0, 0)), ImageOverlay(_create_rgb((0, 0, 255), size=(3, 3)), (1, 1))])
		image, _ = self._render(comp)
		self.assertEqual(image.getpixel((2, 2)), (0, 0, 255))
		self.assertEqual(image.getpixel((4, 4)), (255, 0, 0))

	def test_foreground_and_priority_hide_overlays(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((0, 0, 0), size=(6, 6))))
		comp.set_layer_overlays([ImageOverlay(_create_rgb((255, 0, 0), size=(6, 6)), (0, 0))])
		comp.set_layer_forground(_di("Foreground", _create_rgb((0, 255, 0), size=(6, 6))))
		image, title = self._render(comp)
		self.assertEqual((image.getpixel((0, 0)), title), ((0, 255, 0), "Foreground"))
		comp.set_layer_priority(PriorityImage(datetime.datetime.now(), "Priority", _create_rgb((0, 0, 255), size=(6, 6)), datetime.timedelta(seconds=30)))
		image, title = self._render(comp)
		self.assertEqual((image.getpixel((0, 0)), title), ((0, 0, 255), "Priority"))

	def test_overlays_without_a_background_render_nothing(self):
		comp = ImageCompositor()
		comp.set_layer_overlays([ImageOverlay(_create_rgb((255, 0, 0), size=(2, 2)), (0, 0))])
		self.assertIsNone(comp.commit())

	def test_changing_overlays_versions_and_redraws(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((0, 0, 0), size=(6, 6))))
		comp.set_layer_overlays([ImageOverlay(_create_rgb((255, 0, 0), size=(2, 2)), (0, 0))])
		first, _ = self._render(comp)
		self.assertIsNone(comp.commit())
		before, after = comp.set_layer_overlays([ImageOverlay(_create_rgb((0, 255, 0), size=(2, 2)), (0, 0))])
		self.assertGreater(after.version, before.version)
		second, _ = self._render(comp)
		self.assertEqual((first.getpixel((0, 0)), second.getpixel((0, 0))), ((255, 0, 0), (0, 255, 0)))
		comp.set_layer_overlays([])
		third, _ = self._render(comp)
		self.assertEqual(third.getpixel((0, 0)), (0, 0, 0))

	def test_background_with_alpha_keeps_its_mode(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", Image.new("RGBA", (6, 6), (0, 0, 0, 255))))
		comp.set_layer_overlays([ImageOverlay(Image.new("RGBA", (2, 2), (255, 255, 255, 255)), (1, 1))])
		image, _ = self._render(comp)
		self.assertEqual(image.mode, "RGBA")
		self.assertEqual(image.getpixel((1, 1)), (255, 255, 255, 255))

if __name__ == "__main__":
    unittest.main()
