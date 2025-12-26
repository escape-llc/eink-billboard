import os
from pathvalidate import sanitize_filename
import logging
from PIL import Image
from .display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager

class MockDisplay(DisplayBase):
	def __init__(self, name: str):
		super().__init__(name)
		self.display_settings = None
		self.image_counter = 0
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager):
		self.logger.info(f"'{self.name}' initialize")
		settings = cm.settings_manager()
		self.display_settings = settings.load_settings("display")
		resolution = self.display_settings.get("mock.resolution", [800,480])
		return resolution

	def shutdown(self):
		pass

	def render(self, img: Image, title: str = None):
		self.logger.info(f"'{self.name}' render")
		if self.display_settings is None:
			self.logger.error("No display_settings loaded")
			return
		output_dir = self.display_settings.get("mock.outputFolder", None)
		if output_dir is None:
			self.logger.error("output_dir is not defined")
		if not os.path.exists(output_dir):
			try:
				os.makedirs(output_dir)
				self.logger.debug(f"output_dir Created: {output_dir}")
			except Exception as e:
				self.logger.error(f"output_dir {output_dir}: {e}")
#		else:
#			self.logger.debug(f"output_dir exists: {output_dir}")

#		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#		filepath = os.path.join(output_dir, f"display_{timestamp}.png")
		self.image_counter += 1
		fn = sanitize_filename(title) if title else "untitled"
		filepath = os.path.join(output_dir, f"display_{self.image_counter}_{fn}.png")
		self.logger.info(f"save {filepath}")
		img.save(filepath, "PNG")

		# Also save as latest.png for convenience
#		img.save(os.path.join(self.output_dir, 'latest.png'), "PNG")
