"""
The driver stage's guard against a panel that never says it is done.

The vendor drivers (Waveshare's, and six of the Inky models: `e640`, `e673`, `el133uf1`, `jd79661`, `jd79668`, `ssd2683`) wait for the panel's busy line in a loop with no end of its own.
A panel that is absent, miswired or hung would hold the Display task's thread for good, silently. So whatever talks to the panel runs here, on a thread of its own, for a time; the
display (the driver stage) turns the outcome into a message, and the Display task never waits longer than that. A thread cannot be killed: one that has not come back is left to finish
(a daemon, so it does not hold the process), and **nothing else is sent to the bus until it has**.
"""
import threading
from typing import Any, Callable

class PanelGuard:
	def __init__(self, name: str = "panel"):
		self._name = name
		self._worker: threading.Thread|None = None

	def busy(self) -> bool:
		"""A call that timed out is still running."""
		return self._worker is not None and self._worker.is_alive()

	def run(self, work: Callable[[], Any], seconds: float) -> Any:
		"""Run `work` on a thread for at most `seconds`: its result, its own failure raised here, a `TimeoutError` when it has not come back, or a `RuntimeError` when an earlier call still has not."""
		if self.busy():
			raise RuntimeError("The panel has not finished the last refresh (its busy line may be stuck): not sending another.")
		outcome: list[Any] = []
		failure: list[BaseException] = []
		def run() -> None:
			try:
				outcome.append(work())
			except BaseException as e:
				failure.append(e)
		worker = threading.Thread(target=run, name=f"{self._name}-panel", daemon=True)
		self._worker = worker
		worker.start()
		worker.join(seconds)
		if worker.is_alive():
			raise TimeoutError(f"The panel did not answer in {seconds:g} seconds.")
		if failure:
			raise failure[0]
		return outcome[0] if outcome else None
