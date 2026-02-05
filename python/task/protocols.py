from concurrent.futures import Future
from typing import Any, Callable, Protocol, runtime_checkable

from .messages import MessageSink
from .messages import BasicMessage
from datetime import timedelta

type CreateTimerResult = tuple[Future[BasicMessage|None], Callable[[], None]]

@runtime_checkable
class IProvideTimer(Protocol):
	def create_timer(self, deltatime: timedelta, sink: MessageSink|None, completed: BasicMessage) -> CreateTimerResult:
		"""
		Creates a timer that waits for deltatime and then sends the completed message to the sink.
		Returns a tuple of (future, cancel_function). The future completes with the completed message when the timer expires, or None if cancelled.
		"""
		...

@runtime_checkable
class IRequireShutdown(Protocol):
	def shutdown(self) -> None:
		"""Shuts down the component gracefully."""
		...

type FutureResult = tuple[Any|None, Exception|None]
type FutureContinuation = Callable[[bool, Any|None, Exception|None], BasicMessage|None]
type CancelToken = Callable[[], bool]
type FutureFunction = Callable[[CancelToken], Any]
type SubmitResult = Callable[[], bool]

@runtime_checkable
class SubmitFuture(Protocol):
	def submit_future(self, future: FutureFunction, continuation: FutureContinuation) -> SubmitResult:
		...

