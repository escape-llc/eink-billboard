import os
import re
import logging
from datetime import datetime
from typing import cast
from pathvalidate import sanitize_filename
from PIL import Image
from .display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager
from pathlib import Path

# the file names this display writes: NNNN_YYYYMMDD_HHMMSS_title.png; only such files are ever cleaned up
OWN_FILE_PATTERN = re.compile(r"^\d{4,}_\d{8}_\d{6}_.*\.png$", re.DOTALL)
# keep the whole name (id, timestamp, title, extension) well under the 255 byte limit of common file systems
MAX_TITLE_BYTES = 120

def truncate_utf8(text: str, max_bytes: int) -> str:
	"""Cuts text to at most max_bytes of UTF-8 without splitting a character."""
	return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")

class MockDisplay(DisplayBase):
	def __init__(self, name: str):
		super().__init__(name)
		self.display_settings = None
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		self.logger.info(f"'{self.name}' initialize")
		settings = cm.settings_manager()
		display_cob = settings.open("display")
		_, self.display_settings = display_cob.get()
		if self.display_settings is None:
			raise ValueError("display settings not found in configuration")
		if not self.display_settings.get("mock.outputFolder", None):
			raise ValueError("the mock display needs a 'mock.outputFolder' setting")
		resolution = cast(tuple[int, int], self.display_settings.get("mock.resolution", [800,480]))
		return resolution

	def shutdown(self):
		pass

	def clear_folder(self, folder: str):
		"""Deletes the images this display wrote earlier; never subfolders, links, or any other file."""
		self.logger.debug(f"clean folder: {folder}")
		for item in Path(folder).iterdir():
			if item.is_file() and not item.is_symlink() and OWN_FILE_PATTERN.match(item.name):
				item.unlink()

	def render(self, img: Image.Image, id: int, title: str|None = None):
		self.logger.info(f"'{self.name}' render id={id} title='{title}' img={img.width}x{img.height}")
		if self.display_settings is None:
			self.logger.error("No display_settings loaded")
			return
		clean_folder = cast(bool,self.display_settings.get("mock.cleanOutputFolder", False))
		output_dir = cast(str|None,self.display_settings.get("mock.outputFolder", None))
		if not output_dir:
			self.logger.error("mock.outputFolder is not defined")
			return
		if not os.path.exists(output_dir):
			try:
				os.makedirs(output_dir)
				self.logger.debug(f"output_dir Created: {output_dir}")
			except Exception as e:
				self.logger.error(f"output_dir {output_dir}: {e}")
				return
		elif id == 1 and clean_folder:
			self.clear_folder(output_dir)

		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		fn = truncate_utf8(sanitize_filename(title), MAX_TITLE_BYTES) if title else "untitled"
		filepath = os.path.join(output_dir, f"{id:04d}_{timestamp}_{fn}.png")
		self.logger.info(f"save {filepath}")
		img.save(filepath, "PNG")
