from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .time_of_day import TimeOfDay
from ..task.messages import ConfigurationWatcherEvent, MessageSink

class MessageSinkHandler(FileSystemEventHandler):
	def __init__(self, tod: TimeOfDay, ms: MessageSink):
		super().__init__()
		if ms is None:
			raise ValueError("MessageSink cannot be None")
		if tod is None:
			raise ValueError("TimeOfDay cannot be None")
		self._sink = ms
		self._tod = tod
	def on_created(self, event):
		if not event.is_directory:
			print(f"File created: {event.src_path}")
			self._sink.accept(ConfigurationWatcherEvent("created", event.src_path, self._tod.current_time()))

	def on_modified(self, event):
		if not event.is_directory:
			print(f"File modified: {event.src_path}")
			self._sink.accept(ConfigurationWatcherEvent("modified", event.src_path, self._tod.current_time()))

	def on_deleted(self, event):
		if not event.is_directory:
			print(f"File deleted: {event.src_path}")
			self._sink.accept(ConfigurationWatcherEvent("deleted", event.src_path, self._tod.current_time()))

	def on_moved(self, event):
		if not event.is_directory:
			print(f"File moved from {event.src_path} to {event.dest_path}")
			self._sink.accept(ConfigurationWatcherEvent("moved", event.src_path, self._tod.current_time()))

class ConfigurationWatcher:
	"""
	Watch the configuration root path for changes and send events to the provided MessageSink.
	"""
	def __init__(self, tod: TimeOfDay, ms: MessageSink, root_path: str = "."):
		self.root_path = root_path
		self.event_handler = MessageSinkHandler(tod, ms)
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
