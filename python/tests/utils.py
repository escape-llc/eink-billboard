import os
from pathlib import Path
import threading
import logging
from typing import Callable
from pathvalidate import sanitize_filename
from ..task.messages import BasicMessage, MessageSink
from ..task.display import DisplayImage
from ..tests.test_timer_tick import RecordingTask
from ..model.configuration_manager import ConfigurationManager
from PIL import Image

class MessageTriggerSink(MessageSink):
	"""
	Set the stopped event when a message matching the trigger is received.
	"""
	def __init__(self, trigger: Callable[[BasicMessage], bool]):
		self.trigger = trigger
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)
	def send(self, msg: BasicMessage):
		self.logger.info(f"MessageTriggerSink received message: {msg}")
		if self.trigger(msg):
			self.stopped.set()

def test_output_path_for(folder: str) -> str:
	"""
	The calculated path is relative to the location of this file.
	Folder is created if it does not exist.

	:param folder: The folder
	:type folder: str
	:return: Full path to the test output folder.
	:rtype: str
	"""
	test_file_path = os.path.abspath(__file__)
	opath = Path(os.path.dirname(test_file_path)).parent.parent.joinpath(".test-output", folder)
	folder = str(opath.resolve())
	if not os.path.exists(folder):
		os.makedirs(folder)
	return folder

def save_image(image:Image.Image, folder:str, ix:int, title:str) -> None:
	"""
	Save an image in the output folder indicated.
	
	:param image: Source image
	:type image: Image.Image
	:param folder: The output folder
	:type folder: str
	:param ix: Image index. Used in file name.
	:type ix: int
	:param title: Used in file name
	:type title: str
	"""
	image_path = os.path.join(folder, sanitize_filename(f"im_{ix:03d}_{image.width}x{image.height}_{title}.png"))
	image.save(image_path)

def save_images(display:RecordingTask, folder:str) -> None:
	folder = test_output_path_for(folder)
	for ix, msg in enumerate(display.msgs):
		if isinstance(msg, DisplayImage):
			image = msg.img
			save_image(image, folder, ix, msg.title)

def storage_path() -> str:
	test_file_path = os.path.abspath(__file__)
	test_directory = os.path.dirname(test_file_path)
	storage = os.path.join(test_directory, ".storage")
	return storage

def create_configuration_manager() -> ConfigurationManager:
	storage = storage_path()
	cm = ConfigurationManager(storage_path=storage)
	return cm
