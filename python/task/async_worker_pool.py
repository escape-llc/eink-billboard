import asyncio
import threading
import logging
import inspect
from concurrent.futures import Future
from collections.abc import Coroutine
from typing import Any, Callable

from ..task.protocols import IRequireShutdown

class AsyncWorkerPool(IRequireShutdown):
	# a loop blocked in a synchronous call never sees the stop request: do not wait for it forever
	SHUTDOWN_JOIN_TIMEOUT = 5.0
	def __init__(self):
		self.loop = asyncio.new_event_loop()
		self._loop_ready = threading.Event()
		# set when shutdown() has been called
		self._shutdown = False
		self.logger = logging.getLogger(__name__)
		self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AsyncWorkerPoolThread")

	def _run_loop(self):
		asyncio.set_event_loop(self.loop)
		self.loop.call_soon(self._loop_ready.set)
		self.loop.run_forever()

	def start(self):
		self.thread.start()
		self._loop_ready.wait()
		self.logger.info("Started.")

	def submit(self, coro: Coroutine[Any, Any, Any], callback: Callable[[Future[Any]], object]|None = None) -> Future:
		"""
		Submits work. If callback is provided, it is attached to the future.
		The callback receives the 'future' object as its only argument.
		"""
		# refuse new submissions after shutdown or if loop/thread not available
		if self._shutdown or self.loop.is_closed() or not self.thread.is_alive():
			# If caller passed a coroutine object, close it to avoid 'coroutine was never awaited' warnings
			if inspect.iscoroutine(coro):
				try:
					coro.close()
				except Exception:
					pass
			raise RuntimeError("AsyncWorkerPool has been shutdown")

		fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
		if callback:
			fut.add_done_callback(callback)
		return fut

	def shutdown(self):
		self.logger.info("[Shutdown] Start.")
		# mark shutdown to refuse further submissions
		self._shutdown = True
		if not self.thread.is_alive():
			# never started, or already stopped
			if not self.loop.is_running():
				self.loop.close()
			return
		self.loop.call_soon_threadsafe(self.loop.stop)
		self.thread.join(timeout=self.SHUTDOWN_JOIN_TIMEOUT)
		if self.thread.is_alive():
			self.logger.error(f"[Shutdown] The pool thread did not stop within {self.SHUTDOWN_JOIN_TIMEOUT:g}s; abandoning it.")
			return

		pending = asyncio.all_tasks(self.loop)
		if pending:
			for task in pending:
				task.cancel()
			self.loop.run_until_complete(
				asyncio.gather(*pending, return_exceptions=True)
			)

		self.loop.close()
		self.logger.info("[Shutdown] Complete.")
