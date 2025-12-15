import threading
import queue
import logging
from typing import Callable, Dict, Type

from .messages import MessageSink, BasicMessage, ExecuteMessage, QuitMessage


class CoreTask(threading.Thread, MessageSink):
	"""Core threading and message-queue logic shared by task implementations.

	Subclasses must implement `_dispatch(msg)` to handle messages pulled from
	the internal queue. `CoreTask` provides `run()`, `send()` and a default
	`quitMsg()` implementation used by tasks to stop gracefully.
	"""

	def __init__(self, name=None):
		super().__init__()
		self.msg_queue = queue.Queue()
		self.name = name or self.__class__.__name__
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)

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
				self.logger.error(f"'{self.name} unhandled", e)
		self.logger.info(f"'{self.name}' end {self.msg_queue.qsize()}.")

	def quitMsg(self, msg: QuitMessage):
		"""Default QuitMessage handling: mark stopped and log."""
		self.stopped.set()
		self.logger.info(f"'{self.name}' Quit.")

	def send(self, msg: BasicMessage):
		if self.msg_queue.is_shutdown:
			raise ValueError("Cannot send message to stopped task.")
		self.msg_queue.put(msg)
		if isinstance(msg, QuitMessage):
			self.msg_queue.shutdown()


class BasicTask(CoreTask):
	"""Task that runs in its own thread and processes messages."""
	def __init__(self, name=None):
		super().__init__(name=name)

	def _dispatch(self, msg):
		if isinstance(msg, QuitMessage):
			try:
				self.quitMsg(msg)
			except Exception as e:
				self.logger.error(f"quit.unhandled '{self.name}': {e}", exc_info=True)
		elif isinstance(msg, ExecuteMessage):
			try:
				self.execute(msg)
			except Exception as e:
				self.logger.error(f"execute.unhandled '{self.name}': {e}", exc_info=True)
		# Optionally handle other message types
		else:
			self.logger.warning(f"'{self.name}' received unknown message type: {msg}")

	def execute(self, msg: ExecuteMessage):
		"""Abstract method to execute a message."""
		pass

type HandlerFunc = Callable[[BasicMessage], None]
class DispatcherTask(CoreTask):
	"""Task that dispatches messages to handlers registered by message class.

	Subclasses MUST register handlers during construction using the protected
	`_register_handler(msg_cls, handler)` API.

	Handlers are keyed by the exact message class, then subclasses.

	Registering a handler for `QuitMessage` (or any subclass thereof) is not allowed —
	quit messages are handled identically to `CoreTask`.
	"""
	def __init__(self, name=None):
		super().__init__(name=name)
		self.handlers: Dict[Type[BasicMessage], HandlerFunc] = {}

	def _register_handler(self, msg_cls: Type[BasicMessage], handler: HandlerFunc):
		"""Protected API to register a handler callable for a specific message class.

		Intended for use by the class implementation (e.g., subclasses during
		construction). The handler will be invoked with the message instance
		when a message of the exact class is received.
		If exact class match fails, message superclasses are checked for a handler.
		If no handler is found, an error is logged.
		Registering handlers for `QuitMessage` (or subclasses) is forbidden.
		"""
		if handler is None:
			raise ValueError("Handler cannot be None")
		if not isinstance(msg_cls, type):
			raise TypeError("msg_cls must be a class type")
		if issubclass(msg_cls, QuitMessage):
			raise ValueError("Cannot register handler for QuitMessage")
		self.handlers[msg_cls] = handler

	# DispatcherTask intentionally does not provide an `execute()` implementation
	# — ExecuteMessage handling must be done via registered handlers.

	def _dispatch(self, msg):
		# Keep QuitMessage handling identical to BasicTask
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