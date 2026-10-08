import logging
import queue
import threading
import tkinter as tk
from typing import Any, Callable
from PIL import Image, ImageTk
from .display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager

class TkinterWindow(DisplayBase):
	"""
	Debug display in a Tk window.

	Tk is not thread safe: the root, every widget, the mainloop and the final destroy all live on ONE thread (the Tk thread).
	`render()` and `shutdown()` run on other threads and only post a callable to a queue, which the Tk thread drains from the mainloop.
	"""
	POLL_MS = 50
	START_TIMEOUT_SECONDS = 10.0
	JOIN_TIMEOUT_SECONDS = 5.0

	def __init__(self, name: str):
		super().__init__(name)
		self.display_settings: dict[str, Any] | None = None
		self.image_counter = 0
		self.root: tk.Tk | None = None
		self.tkthread: threading.Thread | None = None
		self._calls: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
		self._ready = threading.Event()
		self._init_error: BaseException | None = None
		self._closing = False
		self.logger = logging.getLogger(__name__)

	def initialize(self, cm: ConfigurationManager):
		self.logger.info(f"'{self.name}' initialize")
		settings = cm.settings_manager()
		display_cob = settings.open("display")
		_, self.display_settings = display_cob.get()
		if self.display_settings is None:
			raise ValueError("display settings not found in configuration")
		resolution = self.display_settings.get("mock.resolution", [800,480])
		self._ready.clear()
		self._init_error = None
		self._closing = False
		self.tkthread = threading.Thread(target=self._tk_main, args=(resolution,), name="TkThread", daemon=True)
		self.tkthread.start()
		if not self._ready.wait(self.START_TIMEOUT_SECONDS):
			raise RuntimeError(f"The Tk window did not start within {self.START_TIMEOUT_SECONDS:g}s")
		if self._init_error is not None:
			raise RuntimeError(f"The Tk window could not be created: {self._init_error}") from self._init_error
		return resolution

	def _tk_main(self, resolution):
		"""Body of the Tk thread: creates the window, then runs the mainloop until the window is destroyed."""
		try:
			self.root = tk.Tk()
			self.root.title("Image Display")
			self.frame = tk.Frame(self.root, width=resolution[0], height=resolution[1])
			self.frame.pack(padx=8, pady=8)
			self.image_label = tk.Label(self.frame, text="e-Ink Billboard Display", compound=tk.TOP)
			self.image_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
		except Exception as e:
			self._init_error = e
			self.root = None
			self._ready.set()
			return
		self._ready.set()
		try:
			self.root.after(self.POLL_MS, self._poll)
			self.logger.debug("start mainloop")
			self.root.mainloop()
			self.logger.debug("end mainloop")
		except Exception as e:
			self.logger.error(f"mainloop {str(e)}")

	def _poll(self):
		self._drain()
		if not self._closing and self.root is not None:
			self.root.after(self.POLL_MS, self._poll)

	def _drain(self):
		"""Runs the posted calls; only ever called on the Tk thread."""
		while True:
			try:
				call = self._calls.get_nowait()
			except queue.Empty:
				return
			try:
				call()
			except Exception as e:
				self.logger.error(f"tk call failed: {str(e)}")

	def shutdown(self):
		root, thread = self.root, self.tkthread
		if root is not None and thread is not None and thread.is_alive():
			def destroy():
				self._closing = True
				root.destroy()
			self._calls.put(destroy)
		if thread is not None and thread.is_alive():
			thread.join(timeout=self.JOIN_TIMEOUT_SECONDS)
			if thread.is_alive():
				self.logger.warning("The Tk thread did not stop")
		self.root = None

	def render(self, img: Image.Image, id:int, title: str|None = None):
		self.logger.info(f"'{self.name}' render id={id} title='{title}' img={img.width}x{img.height}")
		if self.display_settings is None:
			self.logger.error("No display_settings loaded")
			return
		if self.root is None:
			self.logger.warning(f"No TK window was created")
			return
		frame = img.copy()	# the caller may reuse the image while the Tk thread has not drawn it yet
		def draw():
			tk_image = ImageTk.PhotoImage(frame)
			self.image_label.config(image=tk_image, text=title if title else "E-Ink Billboard Display", compound=tk.TOP)
			# important keep a reference to avoid garbage collection
			self.tk_image = tk_image
		self._calls.put(draw)
