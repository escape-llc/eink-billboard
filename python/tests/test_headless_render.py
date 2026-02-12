import os
from pathlib import Path
import unittest
import logging

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathvalidate import sanitize_filename

from ..utils.image_utils import render_html_arglist

logger = logging.getLogger(__name__)

class TestHeadlessRender(unittest.TestCase):
	def save_image(self, image, title):
		test_file_path = os.path.abspath(__file__)
		opath = Path(os.path.dirname(test_file_path)).parent.parent.joinpath(".test-output", "headless")
		folder = str(opath.resolve())
		if not os.path.exists(folder):
			os.makedirs(folder)
		image_path = os.path.join(folder, sanitize_filename(f"im_{image.width}x{image.height}_{title}"))
		logger.info(f"{image_path} {image.width}x{image.height}")
		image.save(image_path)
	def create_env(self):
		px = Path(os.path.dirname(__file__))
		loader = FileSystemLoader([str(px)])
		env = Environment(
			loader=loader,
			autoescape=select_autoescape(['html', 'xml'])
		)
		return env
	def run_test(self, dimensions, template_file, title, arglist = []):
		env = self.create_env()
		template = env.get_template(template_file)
		template_params = {
			"title": title,
			"width": dimensions[0],
			"height": dimensions[1],
		}
		rendered_html = template.render(template_params)
		image = render_html_arglist(rendered_html, arglist)
		self.save_image(image, f"{title}.png")
	def test_800x480_ws_off_si_off(self):
		# dimensions have no effect without any screen-info or window-size
		dimensions = (800,480)
		self.run_test(dimensions, "input/headless.html", "800x480 WS-off SI-off")
	def test_800x480_ws_on_si_off(self):
		dimensions = (800,480)
		arglist = ["--window-size=800,480", "--timeout=1000"]
		self.run_test(dimensions, "input/headless.html", "800x480 WS-on SI-off", arglist)
	def test_800x480_ws_on_si_on(self):
		dimensions = (800,480)
		arglist = ["--window-size=800,480", "--screen-info={0,0 800x480}", "--timeout=1000"]
		self.run_test(dimensions, "input/headless.html", "800x480 WS-on SI-on", arglist)
	def test_800x480_ws_off_si_on(self):
		dimensions = (800,480)
		arglist = ["--screen-info={0,0 800x480}", "--timeout=1000"]
		self.run_test(dimensions, "input/headless.html", "800x480 WS-off SI-on", arglist)
	def test_800x480_ws_off_si_on_oversize(self):
		dimensions = (800,480)
		arglist = ["--screen-info={0,0 836x595}", "--timeout=1000"]
		self.run_test(dimensions, "input/headless.html", "800x480 WS-off SI-on oversize", arglist)

if __name__ == "__main__":
	unittest.main()