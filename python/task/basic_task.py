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

def handles(*types: type[BasicMessage]) -> Callable[[Callable], Callable]:
	"""
	Mark a method of a DispatcherTask as the handler of these message types (#579): `@handles(ConfigureEvent)` above `def _configure_event(self, msg: ConfigureEvent)`.
	Only marked methods are handlers, so a helper that happens to take a message is never one (two helpers once silently replaced a real handler). A type must
	be a message class other than QuitMessage, which every task handles in `quitMsg`; anything else is refused here, when the module is imported.
	"""
	if not types:
		raise TypeError("@handles needs at least one message type")
	for t in types:
		if not (inspect.isclass(t) and issubclass(t, BasicMessage)):
			raise TypeError(f"@handles takes message classes, not {t!r}")
		if issubclass(t, QuitMessage):
			raise TypeError(f"@handles cannot take {t.__name__}: a quit is handled by quitMsg")
	def mark(fn: Callable) -> Callable:
		setattr(fn, "__handles__", tuple(types))  # noqa: B010 -- any function: the type checker knows no such attribute
		return fn
	return mark

def handler_claims(cls: type) -> dict[type[BasicMessage], str]:
	"""
	The message types a task class handles and the name of the method for each, from its `@handles` marks along its classes, base first: a subclass's handler for
	a type replaces its base's, and an override of a marked method keeps the mark. Two methods of one class for the same type, or a mark that disagrees with
	the method's parameter (`@handles(A)` on `def f(self, msg: B)` where A is not a B), are a TypeError, so the mistake shows when the task is made, not when
	a message goes to the wrong method.
	"""
	claims: dict[type[BasicMessage], str] = {}
	for klass in reversed(cls.__mro__):
		own: dict[type[BasicMessage], str] = {}
		for name, fn in vars(klass).items():
			types = getattr(fn, "__handles__", None)
			if types is None:
				continue
			hint = _parameter_hint(fn)
			for t in types:
				if t in own:
					raise TypeError(f"{klass.__name__}: {own[t]} and {name} both handle {t.__name__}")
				if inspect.isclass(hint) and not issubclass(t, hint):
					raise TypeError(f"{klass.__name__}.{name} handles {t.__name__}, but its parameter is a {hint.__name__}")
				own[t] = name
		claims.update(own)
	return claims

def _parameter_hint(fn: Callable) -> Any:
	"""The class a handler's message parameter is annotated with, or None when it has none or it cannot be resolved (a name imported for type checking only)."""
	params = list(inspect.signature(fn).parameters.values())[1:]
	if len(params) != 1:
		raise TypeError(f"{fn.__qualname__}: a handler takes one message")
	try:
		return typing.get_type_hints(fn).get(params[0].name)
	except Exception:
		return None

type HandlerFunc = Callable[[BasicMessage], None]
class DispatcherTask(CoreTask):
	"""Task that dispatches messages to the methods marked `@handles(...)` (see `handles`).

	Handlers are keyed by the exact message class, then its base classes.

	`QuitMessage` (or a subclass) cannot be handled: quit messages are handled identically to `CoreTask`, by `quitMsg`.
	"""
	def __init__(self, name=None):
		super().__init__(name=name)
		self.handlers: dict[Type[BasicMessage], HandlerFunc] = { t: getattr(self, name) for t, name in handler_claims(type(self)).items() }

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
