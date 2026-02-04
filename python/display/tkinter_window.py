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
		display_cob = settings.open("display")
		_, self.display_settings = display_cob.get()
		resolution = self.display_settings.get("mock.resolution", [800,480])
		self.root = tk.Tk()
		self.root.title("Image Display")
		self.frame = tk.Frame(self.root, width=resolution[0], height=resolution[1])
		self.frame.pack(padx=8, pady=8)
		self.image_label = tk.Label(self.frame, image=None, text="e-Ink Billboard Display", compound=tk.TOP)
		self.image_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
		#self.root.geometry(f"{resolution[0]}x{resolution[1]}")
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
				self.image_label.config(image=tk_image, text=title if title else "E-Ink Billboard Display", compound=tk.TOP)
				# important keep a reference to avoid garbage collection
				self.tk_image = tk_image
				self.image_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
				self.root.update()
			except Exception as e:
				self.logger.error(f"render.unhandled: {str(e)}")
				pass
		else:
			self.logger.warning(f"No TK window was created")