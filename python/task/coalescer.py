import threading
from typing import Callable

class Coalescer:
	"""Runs `fire` once, `delay` real seconds after the last `trigger()`: a burst of triggers is one call."""
	def __init__(self, delay: float, fire: Callable[[], None]):
		self._delay = delay
		self._fire = fire
		self._lock = threading.Lock()
		self._timer: threading.Timer|None = None
	def trigger(self) -> None:
		with self._lock:
			if self._timer is not None:
				self._timer.cancel()
			timer = threading.Timer(self._delay, self._fire)
			timer.daemon = True
			self._timer = timer
			timer.start()
	def cancel(self) -> None:
		with self._lock:
			if self._timer is not None:
				self._timer.cancel()
				self._timer = None
