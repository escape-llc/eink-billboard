"""
Tasks in a module with postponed annotations (PEP 563), for test_dispatcher_task: every annotation here is a string, which the handler scan must resolve (#456).
Not a test module itself: `from __future__ import annotations` applies to the whole module, so these tasks live apart from the tests that use them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..task.basic_task import DispatcherTask
from ..task.messages import MessageWithContent

if TYPE_CHECKING:
	from ..task.messages import Telemetry

class PostponedTask(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received: list[str] = []

	def on_content(self, msg: MessageWithContent) -> None:
		self.received.append(msg.content)

class UnresolvableTask(DispatcherTask):
	# Telemetry is imported only for type checking: the annotation names a message type and cannot be resolved at run time
	def on_telemetry(self, msg: Telemetry) -> None:
		pass
