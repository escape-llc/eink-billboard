import unittest
from PIL import Image
from pathlib import Path

from .utils import test_output_path_for, save_image
from ..utils.image_compositor import ImageCompositor, ImageOverlay

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
        changed, img = comp.render()
        self.assertFalse(changed)
        self.assertIsNone(img)

    def test_set_background_and_render_and_versioning(self):
        comp = ImageCompositor()
        # use a real image for the background to exercise file loading
        bg = Image.open(BUTTERFLY_PATH).convert("RGB")
        v1 = comp.set_layer_background(bg)
        self.assertIsInstance(v1, int)
        self.assertGreater(v1, 0)

        changed, out = comp.render()
        save_image(out, folder, 1, "set_background")
        self.assertTrue(changed)
        self.assertIsNotNone(out)
        self.assertEqual(out.size, bg.size)
        self.assertIsNot(out, bg)
        self.assertEqual(out.getpixel((0, 0)), bg.getpixel((0, 0)))

        changed2, out2 = comp.render()
        save_image(out2, folder, 2, "set_background")
        self.assertFalse(changed2)
        self.assertIs(out2, out)

        overlay_img = _create_rgb((1, 2, 3), size=(5, 5))
        ovl = ImageOverlay(overlay_img, (1, 1))
        v2 = comp.set_layer_overlays([ovl])
        self.assertGreater(v2, v1)
        changed3, out3 = comp.render()
        save_image(out3, folder, 3, "set_background")
        self.assertTrue(changed3)
        self.assertEqual(out3.size, bg.size)

    def test_foreground_and_interstitial_priority(self):
        comp = ImageCompositor()
        bg = Image.open(BUTTERFLY_PATH).convert("RGB")
        fg = Image.open(FRUITS_PATH).convert("RGB")
        inter = Image.open(SMARTIES_PATH).convert("RGB")

        comp.set_layer_background(bg)
        comp.set_layer_forground(fg)
        changed, out = comp.render()
        save_image(out, folder, 1, "set_fg_interstitial")
        self.assertTrue(changed)
        self.assertEqual(out.getpixel((0, 0)), fg.getpixel((0, 0)))

        comp.set_layer_interstitial(inter)
        changed2, out2 = comp.render()
        save_image(out2, folder, 2, "set_fg_interstitial")
        self.assertTrue(changed2)
        self.assertEqual(out2.getpixel((0, 0)), inter.getpixel((0, 0)))

    def test_composited_image_attribute_matches_returned_image(self):
        comp = ImageCompositor()
        bg = _create_rgb((5, 6, 7), size=(4, 4))
        comp.set_layer_background(bg)
        changed, out = comp.render()
#        save_image(out, folder, 1, "matches_returned_image")
        self.assertTrue(changed)
        self.assertIs(comp.composited_image, out)


if __name__ == "__main__":
    unittest.main()
