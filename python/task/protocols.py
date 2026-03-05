from concurrent.futures import Future
from typing import Any, Callable, Protocol, runtime_checkable
from datetime import timedelta

from .messages import BasicMessage, TimerExpired

type CreateTimerResult[T] = tuple[Future[TimerExpired[T]|None], Callable[[], None]]

@runtime_checkable
class MessageSink(Protocol):
	"""Ability to accept messages."""
	def accept(self, msg: BasicMessage):
		...

@runtime_checkable
class IProvideTimer(Protocol):
	def create_timer[T](self, deltatime: timedelta, sink: MessageSink|None, token: str, state: T) -> CreateTimerResult[T]:
		"""
		Creates a timer that waits for deltatime and then sends the completed message to the sink.
		Returns a tuple of (future, cancel_function). The future completes with the completed message when the timer expires, or None if cancelled.
		"""
		...
	async def sleep(self, deltatime: timedelta) -> None:
		"""
		Asynchronously sleeps for the specified deltatime.
		"""
		...
	def delta_for(self, deltatime: timedelta) -> timedelta:
		"""Converts a deltatime to the actual time to wait, applying any scaling or adjustments as needed."""
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

