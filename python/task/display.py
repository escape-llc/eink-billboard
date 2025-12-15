import logging
from PIL import Image

from ..utils.image_utils import apply_image_enhancement, change_orientation, resize_image
from ..display.mock_display import MockDisplay
from ..display.tkinter_window import TkinterWindow
from ..display.display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager
from ..task.basic_task import BasicTask, DispatcherTask
from ..task.timer_tick import TickMessage
from ..task.messages import ConfigureEvent, ExecuteMessage, QuitMessage
from .message_router import MessageRouter

class DisplayImage(ExecuteMessage):
	def __init__(self, title:str, img: Image):
		super().__init__()
		self.title = title
		self.img = img
	def __repr__(self):
		return f" title='{self.title}' img={self.img.width}x{self.img.height}"


class DisplaySettings(ExecuteMessage):
	"""
	Notify tasks of the current display settings.
	"""
	def __init__(self, name:str, width: int, height: int):
		super().__init__()
		self.name = name
		self.width = width
		self.height = height
	def __repr__(self):
		return f" name='{self.name}' width={self.width} height={self.height}"

class Display(DispatcherTask):
	def __init__(self, name, router:MessageRouter):
		super().__init__(name)
		self._register_handler(ConfigureEvent, self._configure_event)
		self._register_handler(TickMessage, self._tick_message)
		self._register_handler(DisplayImage, self._display_message)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm:ConfigurationManager = None
		self.display:DisplayBase = None
		self.resolution = [800,480]
		self.lastTickSeen:TickMessage = None
		self.displayImageCount = 0
		self.logger = logging.getLogger(__name__)

	def quitMsg(self, msg: QuitMessage):
		try:
			if self.display is not None:
				self.display.shutdown()
		except Exception as e:
			self.logger(f"shutdown.unhandled {str(e)}")
		finally:
			self.display = None
			super().quitMsg(msg)
		pass
	def _configure_event(self, msg: ConfigureEvent):
		try:
			self.cm = msg.content.cm
			settings = self.cm.settings_manager()
			self.display_settings = settings.load_settings("display")
			display_type = self.display_settings.get("display_type", None)
			if display_type == "mock":
				self.display = MockDisplay("mock")
			elif display_type == "tk":
				self.display = TkinterWindow("tk")
			else:
				raise ValueError(f"Unrecognized display type: '{display_type}'")
			self.resolution = self.display.initialize(self.cm)
			self.logger.info(f"Loading display {display_type} {self.resolution[0]}x{self.resolution[1]}")
			msg.notify()
			self.router.send("display-settings", DisplaySettings(display_type, self.resolution[0], self.resolution[1]))
		except Exception as e:
			self.logger.error(f"configure.unhandled: {str(e)}")
			msg.notify(True, e)
	def _tick_message(self, msg: TickMessage):
		self.lastTickSeen = msg
	def _display_message(self, msg: DisplayImage):
		try:
			self.displayImageCount += 1
			self.logger.info(f"Display {self.displayImageCount} '{msg.title}'")
			if self.display is None:
				self.logger.error("No driver is loaded")
				return
			# Resize and adjust orientation
			image = msg.img
			if self.display_settings is not None:
				image = change_orientation(image, self.display_settings.get("orientation", "landscape"))
				image = resize_image(image, self.resolution)
				if self.display_settings.get("rotate180", False): image = image.rotate(180)
				image = apply_image_enhancement(image, self.display_settings)

			self.display.render(image, msg.title)
		except Exception as e:
			self.logger.error("displayimage.unhandled", e)
			pass
