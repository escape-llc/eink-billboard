import logging
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .time_of_day import TimeOfDay
from ..task.messages import ConfigurationWatcherEvent
from ..task.protocols import MessageSink

logger = logging.getLogger(__name__)

TEMP_PREFIX = ".tmp-"

class MessageSinkHandler(FileSystemEventHandler):
	def __init__(self, tod: TimeOfDay, ms: MessageSink, debounce: float = 1.0):
		super().__init__()
		if ms is None:
			raise ValueError("MessageSink cannot be None")
		if tod is None:
			raise ValueError("TimeOfDay cannot be None")
		if debounce is None:
			raise ValueError("Debounce value cannot be None")
		self._sink = ms
		self._tod = tod
		self.timers: dict[bytes|str, threading.Timer] = {}
		self._lock = threading.Lock()
		self.delay = debounce

	def _start_timer(self, path:bytes|str, event_type:str):
		def __send_event():
			with self._lock:
				# only forget the slot if a newer timer has not replaced this one
				if self.timers.get(path) is timer:
					del self.timers[path]
			logger.debug(f"Sent event for {os.fsdecode(path)} after delay")
			self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), event_type, path))
		timer = threading.Timer(self.delay, __send_event)
		timer.daemon = True
		with self._lock:
			old = self.timers.get(path)
			if old is not None:
				old.cancel()
			self.timers[path] = timer
		timer.start()

	def cancel_all(self):
		"""Cancel every pending timer (no further events are sent)."""
		with self._lock:
			pending = list(self.timers.values())
			self.timers.clear()
		for t in pending:
			t.cancel()

	@staticmethod
	def _is_temp(path) -> bool:
		"""The temp files our atomic save writes (see `_internal_save`); they are renamed away, so events for them are noise."""
		name = os.path.basename(os.fsdecode(path))
		return name.startswith(TEMP_PREFIX)

	def on_created(self, event):
		if event.is_directory or self._is_temp(event.src_path):
			return
		logger.debug(f"File created: {event.src_path}")
		self._start_timer(event.src_path, "created")
#		self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), "created", event.src_path))

	def on_modified(self, event):
		if event.is_directory or self._is_temp(event.src_path):
			return
		logger.debug(f"File modified: {event.src_path}")
		self._start_timer(event.src_path, "modified")
#		self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), "modified", event.src_path))

	def on_deleted(self, event):
		if event.is_directory:
			return
		logger.debug(f"File deleted: {event.src_path}")
		self._start_timer(event.src_path, "deleted")
#		self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), "deleted", event.src_path))

	def on_moved(self, event):
		if event.is_directory:
			return
		logger.debug(f"File moved from {event.src_path} to {event.dest_path}")
		if not self._is_temp(event.src_path):
			self._start_timer(event.src_path, "moved")
		# atomic saves (write temp file, rename over target) show up as a move onto the real file
		dest = getattr(event, "dest_path", None)
		if dest and not self._is_temp(dest):
			self._start_timer(dest, "modified")
#		self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), "moved", event.src_path))

class ConfigurationWatcher:
	"""
	Watch the configuration root path for changes and send events to the provided MessageSink.
	"""
	def __init__(self, tod: TimeOfDay, ms: MessageSink, root_path: str = ".", debounce: float = 1.0):
		self.root_path = root_path
		self.event_handler = MessageSinkHandler(tod, ms, debounce)
		self.observer = None
	def start(self):
		if self.observer is not None:
			raise RuntimeError("Observer already started")
		self.observer = Observer()
		self.observer.schedule(self.event_handler, path=self.root_path, recursive=True)
		self.observer.start()
	def stop(self):
		if self.observer is not None:
			self.observer.stop()
			self.observer.join()
		self.event_handler.cancel_all()
