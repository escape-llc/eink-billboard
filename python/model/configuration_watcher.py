import logging
import threading
from collections import defaultdict
from typing import cast
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .time_of_day import TimeOfDay
from ..task.messages import ConfigurationWatcherEvent
from ..task.protocols import MessageSink

logger = logging.getLogger(__name__)

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
		self.timers: defaultdict[bytes|str,threading.Timer|None] = defaultdict(lambda: None)
		self.delay = debounce

	def _start_timer(self, path:bytes|str, event_type:str):
		if self.timers[path] is not None:
			cast(threading.Timer, self.timers[path]).cancel()
			self.timers[path] = None
		def __send_event(path, event_type:str):
			logger.debug(f"Sent event for {path} after delay")
			self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), event_type, path))
			self.timers[path] = None
		self.timers[path] = threading.Timer(self.delay, __send_event, args=(path, event_type))
		cast(threading.Timer, self.timers[path]).start()

	def on_created(self, event):
		if event.is_directory:
			return
		logger.debug(f"File created: {event.src_path}")
		self._start_timer(event.src_path, "created")
#		self._sink.accept(ConfigurationWatcherEvent(self._tod.current_time(), "created", event.src_path))

	def on_modified(self, event):
		if event.is_directory:
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
		self._start_timer(event.src_path, "moved")
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
