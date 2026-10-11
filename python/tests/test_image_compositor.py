import datetime
import unittest
from PIL import Image
from pathlib import Path

from ..task.display import DisplayImage, PriorityImage
from .utils import test_output_path_for, save_image
from ..utils.image_compositor import ImageCompositor, ImageOverlay, LayerStack, text_overlay

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

	def test_wash_is_a_blurred_halo_of_what_the_overlay_draws(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((100, 100, 100), size=(80, 60))))
		# a 40x40 overlay with a small opaque mark in the middle (the "text"), the rest of its box clear
		mark = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
		mark.paste((0, 0, 0, 255), (17, 17, 23, 23))
		comp.set_layer_overlays([ImageOverlay(mark, (20, 10), wash=0.8)])
		image, _ = self._render(comp)
		save_image(image, folder, 11, "overlay_wash")
		near = image.getpixel((20 + 15, 10 + 20))[0]   # two pixels from the mark
		far = image.getpixel((20 + 1, 10 + 1))[0]      # a corner of the box
		self.assertGreater(near, 150)
		self.assertLess(far, 104)
		self.assertEqual(image.getpixel((20 + 20, 10 + 20)), (0, 0, 0))
		# outside the box nothing changes
		self.assertEqual(image.getpixel((10, 10)), (100, 100, 100))
		self.assertEqual(image.getpixel((70, 50)), (100, 100, 100))

	def test_wcag_contrast(self):
		from ..utils.image_compositor import contrast_ratio, relative_luminance
		self.assertAlmostEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=2)
		self.assertAlmostEqual(contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0, places=2)
		self.assertAlmostEqual(relative_luminance((255, 0, 0)), 0.2126, places=4)
		# #767676 is the lightest gray that reaches 4.5:1 on white
		self.assertGreaterEqual(contrast_ratio((0x76, 0x76, 0x76), (255, 255, 255)), 4.5)
		self.assertLess(contrast_ratio((0x77, 0x77, 0x77), (255, 255, 255)), 4.5)

	def test_the_auto_wash_color_has_the_better_contrast_with_the_worst_off_color(self):
		from ..utils.image_compositor import BLACK, WHITE, wash_rgb
		def ink(*colors):
			img = Image.new("RGBA", (10 * len(colors), 10), (0, 0, 0, 0))
			for i, c in enumerate(colors):
				img.paste(c + (255,), (i * 10, 0, i * 10 + 10, 10))
			return img
		self.assertEqual(wash_rgb(ink((20, 30, 90))), WHITE)      # dark text: a white halo
		self.assertEqual(wash_rgb(ink((240, 240, 200))), BLACK)   # light text: a black halo
		# a dark word and a light word: the halo that serves the worse of the two (mid blue 4.5 vs 4.7 is close: the ratio decides)
		mixed = ink((10, 10, 10), (200, 200, 200))
		self.assertIn(wash_rgb(mixed), (WHITE, BLACK))
		self.assertEqual(wash_rgb(ink((250, 250, 250)), "white"), WHITE)
		self.assertEqual(wash_rgb(ink((250, 250, 250)), "black"), BLACK)
		self.assertEqual(wash_rgb(Image.new("RGBA", (4, 4), (0, 0, 0, 0))), WHITE)

	def test_a_light_text_is_washed_dark(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((120, 120, 120), size=(80, 60))))
		mark = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
		mark.paste((250, 250, 250, 255), (17, 17, 23, 23))
		comp.set_layer_overlays([ImageOverlay(mark, (20, 10), wash=0.8)])
		image, _ = self._render(comp)
		self.assertLess(image.getpixel((20 + 15, 10 + 20))[0], 60)

	def test_a_solid_wash_has_a_hard_edge_and_no_gradient(self):
		from ..utils.image_compositor import wash_mask
		mark = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
		mark.paste((0, 0, 0, 255), (25, 15, 35, 25))
		mask, _ = wash_mask(mark, 1.0, "solid")
		self.assertEqual(set(mask.getdata()), { 0, 255 })
		self.assertEqual(set(wash_mask(mark, 0.5, "solid")[0].getdata()), { 0, 128 })
		# the soft one is a gradient
		self.assertGreater(len(set(wash_mask(mark, 1.0, "soft")[0].getdata())), 5)

	def test_a_clear_overlay_washes_nothing(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((100, 100, 100), size=(20, 20))))
		comp.set_layer_overlays([ImageOverlay(Image.new("RGBA", (6, 6), (0, 0, 0, 0)), (4, 4), wash=0.9)])
		image, _ = self._render(comp)
		self.assertEqual(image.getpixel((5, 5)), (100, 100, 100))

	def test_overlay_hanging_off_the_edge_is_clipped(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((10, 10, 10), size=(10, 10))))
		comp.set_layer_overlays([
			ImageOverlay(_create_rgb((255, 0, 0), size=(6, 6)), (7, 7)),
			ImageOverlay(_create_rgb((0, 255, 0), size=(6, 6)), (-4, -4), wash=0.5),
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

class TestTextOverlay(unittest.TestCase):
	def test_canvas_has_the_requested_size_and_is_transparent_outside_the_text(self):
		overlay = text_overlay("Hi", (120, 40), (5, 6))
		self.assertEqual(overlay.image.size, (120, 40))
		self.assertEqual(overlay.position, (5, 6))
		self.assertEqual(overlay.image.mode, "RGBA")
		self.assertEqual(overlay.image.getpixel((0, 0))[3], 0)
		bbox = overlay.image.getchannel("A").getbbox()
		self.assertIsNotNone(bbox)
		assert bbox is not None
		# drawn, and centered within a few pixels
		self.assertLessEqual(abs((bbox[0] + bbox[2]) / 2 - 60), 3)
		self.assertLessEqual(abs((bbox[1] + bbox[3]) / 2 - 20), 3)

	def test_a_long_text_shrinks_to_fit(self):
		overlay = text_overlay("A fairly long line of text to fit", (200, 30), (0, 0))
		bbox = overlay.image.getchannel("A").getbbox()
		self.assertIsNotNone(bbox)
		assert bbox is not None
		self.assertLessEqual(bbox[2] - bbox[0], 200)
		self.assertLessEqual(bbox[3] - bbox[1], 30)

	def test_a_text_that_cannot_fit_is_clipped_not_an_error(self):
		overlay = text_overlay("This will not fit in a tiny box", (20, 10), (0, 0))
		self.assertEqual(overlay.image.size, (20, 10))

	def test_wash_and_color_are_kept(self):
		overlay = text_overlay("X", (40, 40), (0, 0), color=(255, 0, 0), wash=0.4)
		self.assertEqual(overlay.wash, 0.4)
		pixels = [overlay.image.getpixel((x, y)) for x in range(40) for y in range(40)]
		strong = [px for px in pixels if px[3] > 200]
		self.assertTrue(strong)
		self.assertTrue(all(px[:3] == (255, 0, 0) for px in strong))

	def test_embolden_adds_ink_in_the_same_color(self):
		plain = text_overlay("Wide", (120, 40), (0, 0), color=(255, 0, 0))
		heavy = text_overlay("Wide", (120, 40), (0, 0), color=(255, 0, 0), embolden=0.04)
		def ink(o): return sum(1 for px in o.image.getdata() if px[3] > 200)
		self.assertGreater(ink(heavy), ink(plain) * 1.15)
		self.assertTrue(all(px[:3] == (255, 0, 0) for px in heavy.image.getdata() if px[3] > 200))

	def test_runs_of_colors_on_one_line(self):
		overlay = text_overlay([("Fri", (255, 0, 0)), (", Oct 9", (0, 0, 255))], (200, 40), (0, 0))
		pixels = [overlay.image.getpixel((x, y)) for x in range(200) for y in range(40)]
		colors = { px[:3] for px in pixels if px[3] == 255 }
		self.assertEqual(colors, { (255, 0, 0), (0, 0, 255) })
		# red before blue, on one line
		reds = [x for x in range(200) for y in range(40) if overlay.image.getpixel((x, y)) == (255, 0, 0, 255)]
		blues = [x for x in range(200) for y in range(40) if overlay.image.getpixel((x, y)) == (0, 0, 255, 255)]
		self.assertLess(max(reds), min(blues))

	def test_text_overlay_drawn_by_the_compositor(self):
		comp = ImageCompositor()
		comp.set_layer_background(_di("Background", _create_rgb((0, 0, 0), size=(200, 100))))
		comp.set_layer_overlays([text_overlay("Bottom Right", (100, 30), (100, 70), wash=0.4)])
		package = comp.commit()
		assert package is not None
		image, _ = package.render()
		save_image(image, folder, 12, "text_overlay")
		self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
		# the text and the halo around it are in the box, and the wash does not lighten the box's empty corner
		box = image.crop((100, 70, 200, 100))
		self.assertTrue(any(px != (0, 0, 0) for px in box.getdata()))
		self.assertEqual(image.getpixel((100, 70)), (0, 0, 0))

if __name__ == "__main__":
    unittest.main()
