"""
Tasks in a module with postponed annotations (PEP 563), for test_dispatcher_task: every annotation here is a string, which the check of a handler's parameter
must resolve (#456), or leave alone when it cannot (#579).
Not a test module itself: `from __future__ import annotations` applies to the whole module, so these tasks live apart from the tests that use them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..task.basic_task import DispatcherTask, handles
from ..task.messages import MessageWithContent

if TYPE_CHECKING:
	from ..task.messages import Telemetry

class PostponedTask(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received: list[str] = []

	@handles(MessageWithContent)
	def on_content(self, msg: MessageWithContent) -> None:
		self.received.append(msg.content)

class UnresolvableTask(DispatcherTask):
	# Telemetry is imported only for type checking, so the parameter's annotation cannot be resolved at run time: the mark decides, and is not checked against it
	@handles(MessageWithContent)
	def on_content(self, msg: Telemetry) -> None:
		pass
