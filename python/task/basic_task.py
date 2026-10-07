import inspect
import threading
import queue
import logging
from typing import Any, Callable, Type
from .messages import BasicMessage, QuitMessage
from .protocols import MessageSink

class TaskStoppedError(ValueError):
	"""A message was sent to a task that has already stopped (a ValueError, as `accept` always raised)."""

class CoreTask(threading.Thread, MessageSink):
	"""
	Core threading and message-queue logic shared by task implementations.

	Subclasses must implement `_dispatch(msg)` to handle messages pulled from the internal queue.

	`CoreTask` provides `run()`, `send()` and a default `quitMsg()` implementation used by tasks to stop gracefully.
	"""

	def __init__(self, name=None):
		super().__init__(daemon=True)
		self.msg_queue = queue.Queue()
		self.name = name or self.__class__.__name__
		# stopped: QuitMessage processed
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)

	def _dispatch(self, msg: BasicMessage):
		"""Subclasses must implement this to handle messages pulled from the internal queue."""
		raise NotImplementedError("Subclasses must implement _dispatch()")

	def run(self):
		self.logger.info(f"'{self.name}' start.")
		running = True
		while running:
			try:
				msg = self.msg_queue.get()
				self._dispatch(msg)
				self.msg_queue.task_done()
			except queue.ShutDown:
				self.logger.debug(f"Queue shut down")
				running = False
				self.stopped.set()
			except Exception as e:
				self.msg_queue.task_done()
				self.logger.error(f"'{self.name}' unhandled: {e}", exc_info=True)
		self.logger.info(f"'{self.name}' end {self.msg_queue.qsize()}.")

	def quitMsg(self, msg: QuitMessage):
		"""Default QuitMessage handling: mark stopped and log."""
		self.stopped.set()
		self.logger.info(f"'{self.name}' Quit.")

	def is_stopped(self):
		return self.msg_queue.is_shutdown == True or self.stopped.is_set()

	def accept(self, msg: BasicMessage):
		if self.msg_queue.is_shutdown:
			raise TaskStoppedError("Cannot send message to stopped task.")
		self.msg_queue.put(msg)
		if isinstance(msg, QuitMessage):
			self.msg_queue.shutdown()

def exclude_from_dispatch(obj):
	"""Mark a function or callable so the DispatcherTasks registration will skip it."""
	setattr(obj, "__exclude_from_dispatch__", True)
	return obj

def is_excluded(obj: Any) -> bool:
    """Return True if the object is marked to be excluded from dispatch."""
    return bool(getattr(obj, "__exclude_from_dispatch__", False))

type HandlerFunc = Callable[[BasicMessage], None]
class DispatcherTask(CoreTask):
	"""Task that dispatches messages to handlers registered by message class.

	Methods are auto-scanned in the ctor based on type hints of the first argument.
	Handlers are keyed by the exact message class, then subclasses.

	Registering a handler for `QuitMessage` (or any subclass thereof) is not allowed —
	quit messages are handled identically to `CoreTask`.
	"""
	def __init__(self, name=None):
		super().__init__(name=name)
		self.handlers: dict[Type[BasicMessage], HandlerFunc] = {}
		self._populate_registry()

	def _populate_registry(self):
		# 1. Inspect all bound methods
		for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
			if name.startswith("__"):
				continue
			if getattr(method, "__exclude_from_dispatch__", False):
				continue
			if name == "quitMsg" or name == "_dispatch" or name == "accept":
				continue
			# 2. Get signature (excludes 'self' for bound methods)
			sig = inspect.signature(method)
			params = list(sig.parameters.values())
			if params and len(params) == 1:
				# 3. Extract the type hint of the first argument
				param_type = params[0].annotation
				# 4. Filter and store if it matches your base type
				if inspect.isclass(param_type) and issubclass(param_type, BasicMessage) and not issubclass(param_type, QuitMessage):
					self.handlers[param_type] = method

	def _dispatch(self, msg: BasicMessage):
		if isinstance(msg, QuitMessage):
			try:
				self.quitMsg(msg)
			except Exception as e:
				self.logger.error(f"quit.unhandled '{self.name}': {e}", exc_info=True)
			return

		# Handler lookup: attempt exact class, then search superclasses up to BasicMessage
		handler = None
		matched_cls = None
		for cls in type(msg).mro():
			# stop looking once we reach BasicMessage's base classes
			if cls is object:
				break
			# only consider subclasses of BasicMessage
			try:
				issub = issubclass(cls, BasicMessage)
			except TypeError:
				issub = False
			if not issub:
				continue
			# check for a registered handler for this class
			hx = self.handlers.get(cls)
			if hx is not None:
				handler = hx
				matched_cls = cls
				break

		if handler is not None:
			try:
				handler(msg)
			except Exception as e:
				self.logger.error(f"handler.unhandled '{self.name}': {e}", exc_info=True)
		else:
			# Treat missing handler as an error
			self.logger.error(f"'{self.name}' no handler for message type: {type(msg)}")
