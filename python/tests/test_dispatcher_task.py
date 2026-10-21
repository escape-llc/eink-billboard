from datetime import datetime
import inspect
import unittest
from ..task.basic_task import DispatcherTask, exclude_from_dispatch, is_excluded
from ..task.messages import BasicMessage, MessageWithContent, QuitMessage


class RecordingDispatcher(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received = []

	def _execute(self, msg: BasicMessage):
		# Record generic execute messages (fallback path)
		try:
			content = getattr(msg, 'content')
		except Exception:
			content = None
		self.received.append((type(msg).__name__, content))


class TestDispatcherTask(unittest.TestCase):
	def test_handler_called_for_exact_class(self):
		class RegisteredDispatcher(RecordingDispatcher):
			def __init__(self):
				super().__init__()

			def _handler(self, msg: MessageWithContent):
				self.received.append(('handler', msg.content))

		task = RegisteredDispatcher()
		task.start()
		task.accept(MessageWithContent(datetime.now(), 'payload'))
		task.accept(QuitMessage(datetime.now()))
		task.join()

		self.assertFalse(task.is_alive())
		# handler should have been called once
		self.assertIn(('handler', 'payload'), task.received)
		self.assertTrue(task.stopped.is_set())

	def test_baseclass_handler_with_message_subclass(self):
		task = RecordingDispatcher()
		task.start()
		# Send a MessageWithContext which has no exact-class handler
		task.accept(MessageWithContent(datetime.now(), 'payload'))
		task.accept(QuitMessage(datetime.now()))
		task.join()

		# Handler exists for BasicMessage should record it
		self.assertIn(('MessageWithContent', 'payload'), task.received)
		self.assertTrue(task.stopped.is_set())

	def test_sub_emessage_handler_before_super_message_handler(self):
		class SubHandlerDispatcher(RecordingDispatcher):
			def __init__(self):
				super().__init__()
			# called instead of the BasicMessage handler
			def _handler(self, msg: BasicMessage):
				content = getattr(msg, 'content', None)
				self.received.append(('superhandler', content))

		task = SubHandlerDispatcher()
		task.start()
		task.accept(MessageWithContent(datetime.now(), 'payload2'))
		task.accept(QuitMessage(datetime.now()))
		task.join()

		self.assertIn(('superhandler', 'payload2'), task.received)
		self.assertTrue(task.stopped.is_set())

	def test_override_quitMsg_is_called(self):
		class QuitOverrideDispatcher(RecordingDispatcher):
			def __init__(self):
				super().__init__()

			def quitMsg(self, msg: QuitMessage):
				self.received.append(('quit_called', None))
				super().quitMsg(msg)

		task = QuitOverrideDispatcher()
		task.start()
		task.accept(QuitMessage(datetime.now()))
		task.join()

		self.assertIn(('quit_called', None), task.received)
		self.assertTrue(task.stopped.is_set())

class TestDispatcherExclude(unittest.TestCase):
	def setUp(self):
		def regular_fn():
				return "regular"

		@exclude_from_dispatch
		def helper_fn():
				return "helper"

		self.regular_fn = regular_fn
		self.helper_fn = helper_fn

	def _collect_dispatchable(self, objs):
		return [o for o in objs if inspect.isfunction(o) and not is_excluded(o)]

	def test_exclude_decorator(self):
		items = [self.regular_fn, self.helper_fn]
		dispatchable = self._collect_dispatchable(items)
		self.assertIn(self.regular_fn, dispatchable)
		self.assertNotIn(self.helper_fn, dispatchable)
		self.assertTrue(is_excluded(self.helper_fn))
		self.assertFalse(is_excluded(self.regular_fn))

class TestPostponedAnnotations(unittest.TestCase):
	"""With `from __future__ import annotations` every annotation is a string: handlers are still found (#456)."""
	def test_a_task_in_such_a_module_dispatches_its_messages(self):
		from .postponed_annotations_task import PostponedTask
		task = PostponedTask()
		self.assertIn(MessageWithContent, task.handlers)
		task.start()
		task.accept(MessageWithContent(datetime.now(), 'payload'))
		task.accept(QuitMessage(datetime.now()))
		task.join()
		self.assertEqual(task.received, ['payload'])

	def test_a_message_type_that_cannot_be_resolved_is_said_at_once(self):
		from .postponed_annotations_task import UnresolvableTask
		with self.assertLogs("python.task.basic_task", level="WARNING") as logs:
			task = UnresolvableTask()
		self.assertEqual(task.handlers, {})
		self.assertIn("on_telemetry", "\n".join(logs.output))
		self.assertIn("cannot be resolved", "\n".join(logs.output))

	def test_a_string_annotation_that_is_not_a_message_says_nothing(self):
		class Helper(DispatcherTask):
			# a name that does not exist, on purpose: an annotation that cannot be resolved and is not a message's
			def plain(self, value: "NotAThing") -> None:  # type: ignore[name-defined]  # noqa: F821
				pass
		with self.assertNoLogs("python.task.basic_task", level="WARNING"):
			task = Helper()
		self.assertEqual(task.handlers, {})

if __name__ == '__main__':
	unittest.main()
