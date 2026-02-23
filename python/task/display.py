from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import queue
from typing import cast
from PIL import Image

from ..display.mock_display import MockDisplay
from ..display.tkinter_window import TkinterWindow
from ..display.display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager, ConfigurationObject
from ..task.basic_task import DispatcherTask
from ..task.timer_tick import TickMessage
from ..task.messages import BasicMessage, ConfigureEvent, QuitMessage
from ..task.protocols import CreateTimerResult, IProvideTimer
from ..task.timer import TimerService
from .message_router import MessageRouter
from ..utils.image_compositor import ImageCompositor
from ..utils.image_utils import apply_image_enhancement, change_orientation, resize_image

@dataclass(frozen=True, slots=True)
class DisplayImage(BasicMessage):
	title: str
	img: Image.Image

@dataclass(frozen=True, slots=True)
class PriorityImage(BasicMessage):
	title:str
	img: Image.Image
	duration: timedelta

@dataclass(frozen=True, slots=True)
class CommitTimerExpired(BasicMessage):
	title: str

@dataclass(frozen=True, slots=True)
class RefreshBlackoutTimerExpired(BasicMessage):
	pass

@dataclass(frozen=True, slots=True)
class PriorityImageTimerExpired(BasicMessage):
	title: str

@dataclass(frozen=True, slots=True)
class DisplaySettings(BasicMessage):
	"""
	Notify tasks of the current display settings.
	"""
	name: str
	width: int
	height: int

class Display(DispatcherTask):
	def __init__(self, name, router:MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager|None = None
		self.display:DisplayBase|None = None
		self.timer: IProvideTimer|None = None
		self.commit_timer: CreateTimerResult|None = None
		self.priority_timer: CreateTimerResult|None = None
		self.compsitor = ImageCompositor()
		self.priority_backlog = queue.Queue()
		self.resolution = [800,480]
		self.displayImageCount = 0
		self.logger = logging.getLogger(__name__)

	def quitMsg(self, msg: QuitMessage):
		try:
			if self.commit_timer is not None:
				self.commit_timer[1]()
				self.commit_timer = None
			if self.priority_timer is not None:
				self.priority_timer[1]()
				self.priority_timer = None
			if self.display is not None:
				self.display.shutdown()
		except Exception as e:
			self.logger.error(f"shutdown.unhandled {str(e)}")
		finally:
			self.display = None
			super().quitMsg(msg)
		pass
	def _configure_event(self, msg: ConfigureEvent):
		try:
			self.cm = msg.content.cm
			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			if display_settings is None:
				raise ValueError("display settings not found in configuration")
			display_type = cast(str, display_settings.get("display_type", None))
			if display_type == "mock":
				self.display = MockDisplay("mock")
			elif display_type == "tk":
				self.display = TkinterWindow("tk")
			else:
				raise ValueError(f"Unrecognized display type: '{display_type}'")
			ts = msg.content.isp.get_service(IProvideTimer)
			self.timer = ts if ts is not None else TimerService(ThreadPoolExecutor())
			self.resolution = self.display.initialize(self.cm)
			self.logger.info(f"Loading display {display_type} {self.resolution[0]}x{self.resolution[1]}")
			msg.notify()
			self.router.send("display-settings", DisplaySettings(msg.timestamp, display_type, self.resolution[0], self.resolution[1]))
		except Exception as e:
			self.logger.error(f"configure.unhandled: {str(e)}")
			msg.notify(True, e)
	def _commit_timer_expired(self, msg: CommitTimerExpired):
		try:
			self.logger.info(f"Commit {self.compsitor._version} '{msg.title}'")
			self.commit_timer = None
			if self.cm is None:
				self.logger.error("No configuration manager available")
				return
			if self.display is None:
				self.logger.error("No driver is loaded")
				return

			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()

			updated, composited_image = self.compsitor.render()
			if updated == False:
				self.logger.debug(f"Image compositing no changes detected")
				return
			if composited_image is None:
				self.logger.debug(f"Composited image failed")
				return

			if display_settings is not None:
				if display_settings.get("rotate180", False): composited_image = composited_image.rotate(180)
				composited_image = apply_image_enhancement(composited_image, display_settings)

			self.display.render(composited_image, self.displayImageCount, msg.title)
		except Exception as e:
			self.logger.error(f"commit_timer_expired.unhandled: {str(e)}")
		pass
	def _priority_image_timer_expired(self, msg: PriorityImageTimerExpired):
		self.logger.info(f"Priority timer expired for image '{msg.title}'")
		self.priority_timer = None
		if not self.priority_backlog.empty():
			self.logger.info(f"Processing next priority image from backlog")
			next_msg = self.priority_backlog.get_nowait()
			self._priority_image(next_msg)
		pass
	def _priority_image(self, msg: PriorityImage):
		try:
			if self.cm is None:
				self.logger.error("No configuration manager available")
				return
			if self.display is None:
				self.logger.error("No driver is loaded")
				return
			if self.timer is None:
				self.logger.error("No timer service available")
				return
			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			self.displayImageCount += 1
			self.logger.info(f"Display {self.displayImageCount} '{msg.title}'")

			# check for queued PriorityImages and add to queue if one is currently active
			if self.priority_timer is not None:
				self.logger.info(f"Priority image already active, adding '{msg.title}' to backlog")
				self.priority_backlog.put(msg)
				return

			if display_settings is not None:
			# Resize and adjust orientation
				image = change_orientation(msg.img, display_settings.get("orientation", "landscape"))
				image = resize_image(image, self.resolution)
				self.compsitor.set_layer_interstitial(image)
			else:
				self.compsitor.set_layer_interstitial(msg.img)

			self._do_priority_timer(self.timer, PriorityImageTimerExpired(msg.timestamp, msg.title))
		except Exception as e:
			self.logger.error("displayimage.unhandled", e)
			pass
	def _do_commit_timer(self, timer: IProvideTimer, cte: CommitTimerExpired) -> None:
		if timer is None:
			self.logger.error("No timer service available")
			return
		if self.commit_timer is not None:
			self.commit_timer[1]()
			self.commit_timer = None
			self.logger.debug("Existing commit timer cancelled")
		self.commit_timer = timer.create_timer(timedelta(seconds=2), self, cte)
	def _do_priority_timer(self, timer: IProvideTimer, pite: PriorityImageTimerExpired) -> None:
		if timer is None:
			self.logger.error("No timer service available")
			return
		if self.priority_timer is not None:
			self.priority_timer[1]()
			self.priority_timer = None
			self.logger.debug("Existing priority timer cancelled")
		self.priority_timer = timer.create_timer(timedelta(seconds=2), self, pite)
	def _display_image(self, msg: DisplayImage):
		try:
			if self.cm is None:
				self.logger.error("No configuration manager available")
				return
			if self.display is None:
				self.logger.error("No driver is loaded")
				return
			if self.timer is None:
				self.logger.error("No timer service available")
				return
			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			self.displayImageCount += 1
			self.logger.info(f"Display {self.displayImageCount} '{msg.title}'")

			if display_settings is not None:
			# Resize and adjust orientation
				image = change_orientation(msg.img, display_settings.get("orientation", "landscape"))
				image = resize_image(image, self.resolution)
				self.compsitor.set_layer_background(image)
			else:
				self.compsitor.set_layer_background(msg.img)

			self._do_commit_timer(self.timer, CommitTimerExpired(msg.timestamp, msg.title))
		except Exception as e:
			self.logger.error("displayimage.unhandled", e)
			pass
