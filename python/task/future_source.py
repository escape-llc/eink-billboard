
from concurrent.futures import Executor, Future
import logging
import threading
from typing import Any, Callable, Protocol, runtime_checkable

from .messages import BasicMessage, MessageSink

type FutureResult = tuple[Any|None, Exception|None]
type FutureContinuation = Callable[[bool, Any|None, Exception|None], BasicMessage|None]
type CancelToken = Callable[[], bool]
type FutureFunction = Callable[[CancelToken], Any]
type SubmitResult = Callable[[], bool]

@runtime_checkable
class SubmitFuture(Protocol):
	def submit_future(self, future: FutureFunction, continuation: FutureContinuation) -> SubmitResult:
		...

class FutureSource(SubmitFuture):
	def __init__(self, completion_port:MessageSink, executor:Executor) -> None:
		if completion_port is None:
			raise ValueError("completion_port is None")
		if executor is None:
			raise ValueError("executor is None")
		self._port = completion_port
		self._executor:Executor = executor
		self.logger = logging.getLogger(__name__)
	def shutdown(self) -> None:
		if self._executor is not None:
			self.logger.debug("Shutting down FutureSource executor.")
			self._executor.shutdown(cancel_futures=True)
			self._executor = None
	def submit_future(self, future: FutureFunction, continuation: FutureContinuation) -> SubmitResult:
		if future is None:
			raise ValueError("future is None")
		if continuation is None:
			raise ValueError("continuation is None")
		cancel = threading.Event()
		def _the_future() -> FutureResult:
			def _check_cancelled() -> bool:
				return cancel.is_set()
			result = None
			exception = None
			try:
				self.logger.debug("Starting future execution.")
				result = future(_check_cancelled)
			except Exception as ex:
				exception = ex
			return (result, exception)
		def _future_completed(fx: Future[FutureResult], continuation: FutureContinuation) -> None:
			result, exception = fx.result()
			cancelled = cancel.is_set()
			self.logger.debug(f"Future completed c:{cancelled} r:{result} e:{exception}, send continuation message.")
			try:
				msg = continuation(cancelled, result, exception)
				if msg is not None:
					try:
						self._port.send(msg)
					except Exception as ex:
	#					self.logger.error(f"Error sending message: {ex}")
						pass
			except Exception as ex2:
				self.logger.error(f"Continuation.unhandled: {ex2}")
				pass
		p_future = self._executor.submit(_the_future)
		def cancelrequest() -> bool:
			"""
			Signal to cancel the future.
			Futures should consult the is_cancelled callback to cooperatively handle cancellation.
			:return: True if the cancel request was successfully made, False otherwise
			:rtype: bool
			"""
			if p_future.done():
				return False
			if not cancel.is_set():
				cancel.set()
				return True
			return False
		p_future.add_done_callback(lambda fx: _future_completed(fx, continuation))
		return cancelrequest
	pass