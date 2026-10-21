import inspect
import threading
import time
import queue
import logging
import typing
from datetime import datetime
from typing import Any, Callable, Type
from .messages import BasicMessage, QuitMessage, Telemetry
from .protocols import MessageSink

def _message_class_names() -> set[str]:
	"""The names of every message class (BasicMessage and its subclasses, at any depth): what an unresolved string annotation is compared with."""
	found: set[str] = set()
	todo: list[type] = [BasicMessage]
	while todo:
		cls = todo.pop()
		if cls.__name__ not in found:
			found.add(cls.__name__)
			todo.extend(cls.__subclasses__())
	return found

class TaskStoppedError(ValueError):
	"""A message was sent to a task that has already stopped (a ValueError, as `accept` always raised)."""

REPORT_EVERY_SECONDS = 60.0

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
		# where `report_failure` sends its telemetry (the `telemetry` route's send); the application sets it
		self.failure_sink: Callable[[Telemetry], None]|None = None
		# the same failure is reported once a minute, so a loop that fails again and again cannot flood the telemetry
		self._reported: dict[str, float] = {}

	def report_failure(self, what: str, error: BaseException|None = None) -> None:
		"""
		A failure this task swallowed to keep running: the full exception goes to the log, and the telemetry gets our sentence and only a safe reason
		(`safe_reason`), the exception in full as `detail` (shown to a viewer on the device only). Never raises: reporting must not become a second failure.
		"""
		try:
			self.logger.error(f"'{self.name}' {what}" + (f": {error}" if error is not None else ""), exc_info=error is not None)
			if self.failure_sink is None:
				return
			key = f"{what}|{type(error).__name__}"
			now = time.monotonic()
			if now - self._reported.get(key, -REPORT_EVERY_SECONDS) < REPORT_EVERY_SECONDS:
				return
			self._reported[key] = now
			from ..utils.error_image import error_detail, safe_reason
			values: dict[str, Any] = { "kind": "error", "message": f"{what}: {safe_reason(error)}" if error is not None else what }
			if error is not None:
				values["detail"] = error_detail(error)
			self.failure_sink(Telemetry(datetime.now().astimezone(), self.name, values))
		except Exception:
			self.logger.debug("the failure could not be reported", exc_info=True)

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
				self.logger.debug("Queue shut down")
				running = False
				self.stopped.set()
			except Exception as e:
				self.msg_queue.task_done()
				self.report_failure("A message could not be processed", e)
		self.logger.info(f"'{self.name}' end {self.msg_queue.qsize()}.")

	def quitMsg(self, msg: QuitMessage):
		"""Default QuitMessage handling: mark stopped and log."""
		self.stopped.set()
		self.logger.info(f"'{self.name}' Quit.")

	def is_stopped(self):
		return self.msg_queue.is_shutdown or self.stopped.is_set()

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
				param_type = self._parameter_type(name, method, params[0])
				# 4. Filter and store if it matches your base type
				if inspect.isclass(param_type) and issubclass(param_type, BasicMessage) and not issubclass(param_type, QuitMessage):
					self.handlers[param_type] = method

	def _parameter_type(self, name: str, method: Callable, param: inspect.Parameter) -> Any:
		"""
		The class a one-parameter method is annotated with. In a module with `from __future__ import annotations` every annotation is a string: it is resolved
		(`typing.get_type_hints`), or no handler would be registered and the first message of its type would find "no handler" at run time (#456). One that names a
		message type and cannot be resolved (a name imported only for type checking) is said at once, by the task's and method's names.
		"""
		annotation = param.annotation
		if not isinstance(annotation, str):
			return annotation
		try:
			return typing.get_type_hints(method).get(param.name, annotation)
		except Exception:
			if annotation.rsplit(".", 1)[-1] in _message_class_names():
				self.logger.warning(f"'{self.name}': the parameter of '{name}' is annotated '{annotation}', which cannot be resolved, so it handles no message.")
			return annotation

	def _dispatch(self, msg: BasicMessage):
		if isinstance(msg, QuitMessage):
			try:
				self.quitMsg(msg)
			except Exception as e:
				self.logger.error(f"quit.unhandled '{self.name}': {e}", exc_info=True)
			return

		# Handler lookup: attempt exact class, then search superclasses up to BasicMessage
		handler = None
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
				break

		if handler is not None:
			try:
				handler(msg)
			except Exception as e:
				self.report_failure(f"The handler of {type(msg).__name__} failed", e)
		else:
			# Treat missing handler as an error
			self.report_failure(f"No handler for message type {type(msg).__name__}")
