import asyncio
import threading
import logging
import inspect
from concurrent.futures import Future
from types import CoroutineType
from typing import Any, Callable

class AsyncWorkerPool:
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

	def submit(self, coro: CoroutineType[Any,Any,Any], callback: Callable[[Future[Any]], object]|None = None) -> Future:
		"""
		Submits work. If callback is provided, it is attached to the future.
		The callback receives the 'future' object as its only argument.
		"""
		# refuse new submissions after shutdown or if loop/thread not available
		if getattr(self, '_shutdown', False) or self.loop.is_closed() or not self.thread.is_alive():
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
		self.loop.call_soon_threadsafe(self.loop.stop)
		self.thread.join()

		pending = asyncio.all_tasks(self.loop)
		if pending:
			for task in pending:
				task.cancel()
			self.loop.run_until_complete(
				asyncio.gather(*pending, return_exceptions=True)
			)

		self.loop.close()
		self.logger.info("[Shutdown] Complete.")

"""
# --- EXAMPLE WORK ---
async def async_unit_of_work(task_id, duration):
	await asyncio.sleep(duration)
	return f"Data from {task_id}"

# --- CALLBACK FUNCTION ---
def my_sync_callback(fut):
	try:
		result = fut.result()
		print(f"Callback Notification: Task finished with result: {result}")
	except Exception as e:
		print(f"Callback Notification: Task failed with error: {e}")

# --- MAIN ---
if __name__ == "__main__":
	pool = AsyncWorkerPool()
	pool.start()

	# 1. Submit with a callback
	# We don't need to 'join' this manually; the callback handles the result
	pool.submit(async_unit_of_work("Task-A", 2), callback=my_sync_callback)

	print("Main context: Task-A is running, I'm doing other things...")
	
	# Wait long enough to see the callback trigger
	time.sleep(3)

	print("Main context: Closing down.")
	pool.shutdown()
"""