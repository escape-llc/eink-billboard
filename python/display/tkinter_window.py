import logging
import threading
import tkinter as tk
from PIL import Image, ImageTk
from .display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager


class TkThread(threading.Thread):
	def __init__(self, root: tk.Tk):
		super().__init__()
		self.root = root
		self.logger = logging.getLogger(__name__)

	def run(self):
		try:
			self.logger.error("start mainloop")
			self.root.mainloop()
			self.logger.error("end mainloop")
		except Exception as e:
			self.logger.error(f"mainloop {str(e)}")

class TkinterWindow(DisplayBase):
	def __init__(self, name: str):
		super().__init__(name)
		self.display_settings = None
		self.image_counter = 0
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager):
		self.logger.info(f"'{self.name}' initialize")
		settings = cm.settings_manager()
		self.root = tk.Tk()
		self.root.title("Image Display")
		self.image_label = tk.Label(self.root)
		self.image_label.pack()
		self.display_settings = settings.load_settings("display")
		resolution = self.display_settings.get("mock.resolution", [800,480])
		self.root.geometry(f"{resolution[0]}x{resolution[1]}")
		self.tkthread = TkThread(self.root)
		self.tkthread.start()
		return resolution

	def shutdown(self):
		self.root.destroy()
		if self.tkthread:
			self.tkthread.join(timeout=5)

	def render(self, img: Image, title: str = None):
		self.logger.info(f"'{self.name}' render")
		if self.display_settings is None:
			self.logger.error("No display_settings loaded")
			return
		if self.root:
			try:
				tk_image = ImageTk.PhotoImage(img)
				self.image_label.config(image=tk_image)
				self.root.update()
			except Exception as e:
				self.logger.error(f"render.unhandled: {str(e)}")
				pass
		else:
			self.logger.warning(f"No TK window was created")