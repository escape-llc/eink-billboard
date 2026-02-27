from concurrent.futures import Executor, Future, ThreadPoolExecutor
import os
from pathlib import Path
import threading
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from pathvalidate import sanitize_filename

from ..model.time_of_day import TimeOfDay
from ..task.basic_task import DispatcherTask
from ..task.messages import BasicMessage, MessageSink
from ..task.display import DisplayImage
from ..task.timer import TimerThreadService
from ..model.configuration_manager import ConfigurationManager
from PIL import Image

class RecordingTask(DispatcherTask):
	"""A task that records messages it receives for later inspection."""
	def __init__(self, name):
		super().__init__(name)
		self.msgs = []
		self.logger = logging.getLogger(__name__)

	def _basic_message(self, msg: BasicMessage):
		self.logger.debug(f"{self.name}: {msg}")
		self.msgs.append(msg)

class ConstantTimeOfDay(TimeOfDay):
	def __init__(self, now_value):
		if now_value is None:
			raise ValueError("now_value cannot be None")
		super().__init__()
		self._now = now_value
	def current_time(self) -> datetime:
		return self._now
	def current_time_utc(self) -> datetime:
		return self._now.astimezone(timezone.utc)

class ScaledTimeOfDay(TimeOfDay):
	def __init__(self, start_time:datetime, scale:float):
		super().__init__()
		if start_time.tzinfo is None:
			raise ValueError("start_time must be timezone-aware (have tzinfo)")
		if scale <= 0:
			raise ValueError("scale must be greater than zero")
		self._start_time = start_time
		self._scale = scale
	def current_time(self) -> datetime:
		# Use current local time matching start_time tzinfo
		now = datetime.now(self._start_time.tzinfo)
		interval = now - self._start_time
		scaled_interval = interval.total_seconds() * self._scale
		return self._start_time + timedelta(seconds=scaled_interval)
	def current_time_utc(self) -> datetime:
		# start_time is timezone-aware; convert to UTC then compare to current UTC
		start_utc = self._start_time.astimezone(timezone.utc)
		now_utc = datetime.now(timezone.utc)
		interval = now_utc - start_utc
		scaled_interval = interval.total_seconds() * self._scale
		return start_utc + timedelta(seconds=scaled_interval)
	pass

class ScaledTimerThreadService(TimerThreadService):
	def __init__(self, timebase: TimeOfDay, scale: float):
		if scale <= 0:
			raise ValueError("scale must be greater than zero")
		super().__init__(timebase, duration=lambda dt: dt.total_seconds() / scale)

class MessageCollectSink(MessageSink):
	"""
	Set an event when a message is sent.
	Saves messages to a list for inspection.
	"""
	def __init__(self):
		self.messages = []
		self._event = threading.Event()

	def accept(self, msg: BasicMessage):
		self.messages.append(msg)
		self._event.set()

	def wait_for_message(self, timeout=2.0):
		"""Wait for a message to be received, with an optional timeout."""
		return self._event.wait(timeout)

class MessageTriggerSink(MessageSink):
	"""
	Set the stopped event when a message matching the trigger is received.
	"""
	def __init__(self, trigger: Callable[[BasicMessage], bool]):
		if trigger is None:
			raise ValueError("trigger cannot be None")
		self.trigger = trigger
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)
	def accept(self, msg: BasicMessage):
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
