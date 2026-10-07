import os
import re
import tempfile
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

DEFAULT_OUTPUT_FOLDER = "eink-billboard-mock"
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")

def resolve_output_folder(configured: str|None) -> str:
	"""
	Where the mock display writes (it exists to capture images for tests and for a person to look at): an absolute setting as is,
	a relative or empty one inside the system temp directory (never the server's working directory).
	A Windows drive path (c:\\Temp\\mock, the old factory default) is not a path on other systems, where it would become
	a folder with that literal name, so it falls back to the default there.
	"""
	value = (configured or "").strip()
	if os.name != "nt" and _WINDOWS_DRIVE_PATH.match(value):
		value = ""
	if not value:
		value = DEFAULT_OUTPUT_FOLDER
	return os.path.normpath(os.path.join(tempfile.gettempdir(), value))

class MockDisplay(DisplayBase):
	def __init__(self, name: str):
		super().__init__(name)
		self.display_settings = None
		self.output_folder: str|None = None
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		self.logger.info(f"'{self.name}' initialize")
		settings = cm.settings_manager()
		display_cob = settings.open("display")
		_, self.display_settings = display_cob.get()
		if self.display_settings is None:
			raise ValueError("display settings not found in configuration")
		self.output_folder = resolve_output_folder(self.display_settings.get("mock.outputFolder", None))
		self.logger.info(f"mock output folder: {self.output_folder}")
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
		output_dir = self.output_folder
		if not output_dir:
			self.logger.error("The mock display was not initialized")
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
