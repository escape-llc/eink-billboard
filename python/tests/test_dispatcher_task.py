from datetime import datetime
import unittest
from ..task.basic_task import DispatcherTask, handler_claims, handles
from ..task.messages import BasicMessage, MessageWithContent, QuitMessage, Telemetry


class RecordingDispatcher(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received = []

	@handles(BasicMessage)
	def _execute(self, msg: BasicMessage):
		# Record generic execute messages (fallback path)
		# only a MessageWithContent has content; any other type records None
		content = msg.content if isinstance(msg, MessageWithContent) else None
		self.received.append((type(msg).__name__, content))

def run(task: DispatcherTask, *messages: BasicMessage) -> None:
	task.start()
	for msg in messages:
		task.accept(msg)
	task.accept(QuitMessage(datetime.now()))
	task.join()


class TestDispatcherTask(unittest.TestCase):
	def test_handler_called_for_exact_class(self):
		class RegisteredDispatcher(RecordingDispatcher):
			@handles(MessageWithContent)
			def _handler(self, msg: MessageWithContent):
				self.received.append(('handler', msg.content))

		task = RegisteredDispatcher()
		run(task, MessageWithContent(datetime.now(), 'payload'))

		self.assertFalse(task.is_alive())
		self.assertIn(('handler', 'payload'), task.received)
		self.assertTrue(task.stopped.is_set())

	def test_baseclass_handler_with_message_subclass(self):
		task = RecordingDispatcher()
		# a MessageWithContent has no handler of its own: the BasicMessage one records it
		run(task, MessageWithContent(datetime.now(), 'payload'))
		self.assertIn(('MessageWithContent', 'payload'), task.received)
		self.assertTrue(task.stopped.is_set())

	def test_a_subclass_handler_for_a_type_replaces_its_bases(self):
		class SubHandlerDispatcher(RecordingDispatcher):
			# called instead of the base class's BasicMessage handler
			@handles(BasicMessage)
			def _handler(self, msg: BasicMessage):
				content = msg.content if isinstance(msg, MessageWithContent) else None
				self.received.append(('superhandler', content))

		task = SubHandlerDispatcher()
		run(task, MessageWithContent(datetime.now(), 'payload2'))
		self.assertEqual(task.received, [('superhandler', 'payload2')])

	def test_an_override_of_a_marked_method_keeps_the_mark(self):
		class Override(RecordingDispatcher):
			def _execute(self, msg: BasicMessage):
				self.received.append(('override', None))

		task = Override()
		run(task, BasicMessage(datetime.now()))
		self.assertEqual(task.received, [('override', None)])

	def test_override_quitMsg_is_called(self):
		class QuitOverrideDispatcher(RecordingDispatcher):
			def quitMsg(self, msg: QuitMessage):
				self.received.append(('quit_called', None))
				super().quitMsg(msg)

		task = QuitOverrideDispatcher()
		run(task)
		self.assertIn(('quit_called', None), task.received)
		self.assertTrue(task.stopped.is_set())


class TestHandlesMarks(unittest.TestCase):
	"""Only a method marked @handles is a handler (#579): a helper that takes a message once replaced a real handler without a word."""
	def test_an_unmarked_method_that_takes_a_message_is_not_a_handler(self):
		class Helper(RecordingDispatcher):
			def describe(self, msg: MessageWithContent) -> str:
				return msg.content

		task = Helper()
		self.assertEqual(set(task.handlers), { BasicMessage })
		run(task, MessageWithContent(datetime.now(), 'payload'))
		self.assertEqual(task.received, [('MessageWithContent', 'payload')])

	def test_one_method_may_handle_several_types(self):
		class Both(DispatcherTask):
			@handles(MessageWithContent, Telemetry)
			def _either(self, msg: BasicMessage):
				pass

		self.assertEqual(handler_claims(Both), { MessageWithContent: "_either", Telemetry: "_either" })

	def test_two_methods_of_a_class_for_one_type_are_refused_when_the_task_is_made(self):
		class Twice(DispatcherTask):
			@handles(MessageWithContent)
			def _first(self, msg: MessageWithContent):
				pass

			@handles(MessageWithContent)
			def _second(self, msg: MessageWithContent):
				pass

		with self.assertRaisesRegex(TypeError, "_first and _second both handle MessageWithContent"):
			Twice()

	def test_a_mark_that_disagrees_with_the_parameter_is_refused(self):
		class Wrong(DispatcherTask):
			@handles(Telemetry)
			def _content(self, msg: MessageWithContent):
				pass

		with self.assertRaisesRegex(TypeError, "_content handles Telemetry, but its parameter is a MessageWithContent"):
			Wrong()

	def test_only_message_classes_other_than_quit(self):
		with self.assertRaisesRegex(TypeError, "at least one"):
			handles()
		with self.assertRaisesRegex(TypeError, "message classes"):
			handles(int)  # type: ignore[arg-type]
		with self.assertRaisesRegex(TypeError, "quitMsg"):
			handles(QuitMessage)

	def test_a_handler_takes_one_message(self):
		class TwoParameters(DispatcherTask):
			@handles(MessageWithContent)
			def _content(self, msg: MessageWithContent, extra: int):
				pass

		with self.assertRaisesRegex(TypeError, "takes one message"):
			TwoParameters()


class TestPostponedAnnotations(unittest.TestCase):
	"""With `from __future__ import annotations` every annotation is a string: the check of a handler's parameter resolves it (#456)."""
	def test_a_task_in_such_a_module_dispatches_its_messages(self):
		from .postponed_annotations_task import PostponedTask
		task = PostponedTask()
		self.assertIn(MessageWithContent, task.handlers)
		run(task, MessageWithContent(datetime.now(), 'payload'))
		self.assertEqual(task.received, ['payload'])

	def test_a_parameter_that_cannot_be_resolved_leaves_the_mark_to_decide(self):
		from .postponed_annotations_task import UnresolvableTask
		self.assertEqual(handler_claims(UnresolvableTask), { MessageWithContent: "on_content" })

if __name__ == '__main__':
	unittest.main()
