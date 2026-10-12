"""A task that swallows a failure to keep running says so on the telemetry route (and not in raw words): the dispatcher, the router, the display."""
import unittest
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

from PIL import Image

from ..task.basic_task import DispatcherTask
from ..task.display import Display
from ..task.display_messages import DisplayImage
from ..task.message_router import MessageRouter, Route
from ..task.messages import BasicMessage, Telemetry
from ..task.telemetry_hub import TelemetryHub

NOW = datetime(2026, 10, 12, 12, 0).astimezone()
SECRET = "https://example.com/feed?key=hunter2"

@dataclass(frozen=True, slots=True)
class Ping(BasicMessage):
	pass

class Boomer(DispatcherTask):
	def _ping(self, msg: Ping):
		raise RuntimeError(f"cannot read {SECRET}")

class TestFailureTelemetry(unittest.TestCase):
	def test_a_handler_that_raises_is_reported_with_a_safe_reason(self):
		sent: list[Telemetry] = []
		task = Boomer("boomer")
		task.failure_sink = sent.append
		task._dispatch(Ping(NOW))
		self.assertEqual(len(sent), 1)
		values = sent[0].values
		self.assertEqual((sent[0].name, values["kind"]), ("boomer", "error"))
		self.assertIn("The handler of Ping failed", values["message"])
		self.assertNotIn("hunter2", values["message"])
		self.assertIn("hunter2", values["detail"], "the full text is for a viewer on the device")

	def test_the_same_failure_is_reported_once_in_a_minute(self):
		sent: list[Telemetry] = []
		task = Boomer("boomer")
		task.failure_sink = sent.append
		for _ in range(5):
			task._dispatch(Ping(NOW))
		self.assertEqual(len(sent), 1)

	def test_a_message_nobody_handles_is_reported(self):
		@dataclass(frozen=True, slots=True)
		class Unknown(BasicMessage):
			pass
		sent: list[Telemetry] = []
		task = Boomer("boomer")
		task.failure_sink = sent.append
		task._dispatch(Unknown(NOW))
		self.assertIn("No handler for message type Unknown", sent[0].values["message"])

	def test_a_failing_sink_never_breaks_the_task(self):
		task = Boomer("boomer")
		task.failure_sink = MagicMock(side_effect=RuntimeError("hub down"))
		task._dispatch(Ping(NOW))

	def test_a_receiver_that_raises_is_reported_by_the_router(self):
		hub = TelemetryHub()
		router = MessageRouter()
		router.failure_sink = hub.accept
		bad = MagicMock()
		bad.accept.side_effect = RuntimeError("queue broke")
		router.addRoute(Route("display", [bad]))
		router.send("display", Ping(NOW))
		events = hub.since(0)
		self.assertEqual([(e["source"], e["kind"]) for e in events], [("router", "error")])
		self.assertIn("'display'", events[0]["message"])

	def test_a_page_the_display_cannot_show_is_reported(self):
		sent: list[Telemetry] = []
		display = Display("Display", MessageRouter())
		display.failure_sink = sent.append
		display.cm = MagicMock()
		display.display = MagicMock()
		display.task_pool = MagicMock()
		display.task_pool.submit.side_effect = RuntimeError("pool is gone")
		display.commitq = MagicMock()
		display._display_image(DisplayImage(NOW, "page", Image.new("RGB", (8, 6))))
		self.assertEqual(len(sent), 1)
		self.assertIn("A page could not be shown", sent[0].values["message"])
