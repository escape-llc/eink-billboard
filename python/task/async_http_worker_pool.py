import asyncio
from contextvars import ContextVar
import threading
from typing import Any, Callable
import httpx
import logging
from concurrent.futures import Future

from ..task.protocols import IRequireShutdown

# 1. Define a ContextVar to hold the resource
# Think of this as a global variable that is unique to each "Task chain"
client_var: ContextVar[httpx.AsyncClient] = ContextVar("http_client")
# use one context var for each resource

class AsyncHttpWorkerPool(IRequireShutdown):
	def __init__(self):
		self.loop = asyncio.new_event_loop()
		self._loop_ready = threading.Event()
		self._is_active = False # Tracks if we are accepting work
		self.thread = threading.Thread(target=self._run_loop, daemon=True)
		self.client = None
		self.logger = logging.getLogger(__name__)

	def _run_loop(self):
		asyncio.set_event_loop(self.loop)
		self.client = httpx.AsyncClient(max_redirects=5)
		self.loop.call_soon(self._loop_ready.set)
		self.loop.run_forever()

	def start(self):
		"""Initializes the background loop."""
		self.thread.start()
		self._loop_ready.wait()
		self._is_active = True # Now safe to submit
		self.logger.info("[Pool] Ready.")

	def submit(self, coro_func, *args, callback: Callable[[Future[Any]], object]|None = None) -> Future:
		"""Submit from the main thread; fails if shutdown has been called."""
		if not self._is_active:
			raise RuntimeError("Pool is not active or has been shut down.")

		# 2. Wrapper to inject the context variable into the Task
		async def task_wrapper():
			if self.client is None:
				raise RuntimeError("HTTP client is not initialized.")
			# This 'sets' the client for this specific Task and its children
			token = client_var.set(self.client)
			try:
				return await coro_func(*args)
			finally:
				# reset tokens in reverse order
				client_var.reset(token)

		fut = asyncio.run_coroutine_threadsafe(task_wrapper(), self.loop)
		if callback:
			fut.add_done_callback(callback)
		return fut

	def shutdown(self):
		"""Stops the pool. No Lock needed if called from the same thread as submit."""
		if not self._is_active:
			self.logger.warning("[Shutdown] Pool already shut(ting) down or never started.")
			return
		self._is_active = False # Immediately block further submits
		self.logger.info("[Shutdown] Closing pool...")
		# 1. Close client and stop loop via the loop's own thread
		async def cleanup():
			if self.client:
				await self.client.aclose()
			self.loop.stop()
		asyncio.run_coroutine_threadsafe(cleanup(), self.loop)
		# 2. Join the background thread
		self.thread.join()
		# 3. Handle remaining tasks
		pending = asyncio.all_tasks(self.loop)
		if pending:
			for task in pending:
				task.cancel()
			self.loop.run_until_complete(
				asyncio.gather(*pending, return_exceptions=True)
			)
		self.loop.close()
		self.logger.info("[Shutdown] Complete.")

# --- ROBUST WORKER ---
async def fetch_worker(url):
	"""
	Handles internal exceptions so they don't propagate 
	unpredictably to the event loop.
	"""
	try:
		print(f"Task: Fetching {url}...")
		client = client_var.get()
		# httpx.get can raise ConnectError, TimeoutException, etc.
		response = await client.get(url, timeout=5.0)
		# This raises an exception for 4xx/5xx responses
		response.raise_for_status() 
		return response.status_code
	except httpx.HTTPStatusError as e:
		print(f"Task Error: Server returned {e.response.status_code} for {url}")
		raise  # Re-raise so the Future captures it
	except httpx.RequestError as e:
		print(f"Task Error: Network connection failed for {url}: {e}")
		raise
	except asyncio.CancelledError:
		print(f"Task Cleanup: {url} fetch was cancelled during shutdown")
		raise # Always re-raise CancelledError to allow orderly shutdown
	except Exception as e:
		print(f"Task Error: An unexpected error occurred: {e}")
		raise

"""
# --- WORKER ---
async def fetch_worker(url):
	client = client_var.get()
	resp = await client.get(url)
	return resp.status_code
# --- USAGE ---
if __name__ == "__main__":
	pool = AsyncHttpWorkerPool()
	pool.start()

	# Working submission
	f = pool.submit(fetch, "https://httpbin.org")
	print(f"Result: {f.result()}")

	pool.shutdown()

	# This will now fail immediately in the same thread
	try:
		pool.submit(fetch, "https://httpbin.org")
	except RuntimeError as e:
		print(f"Caught: {e}")
"""