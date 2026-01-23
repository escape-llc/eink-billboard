from datetime import datetime
import unittest
import logging
from ..task.basic_task import DispatcherTask
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
		task.accept(MessageWithContent('payload', datetime.now()))
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
		task.accept(MessageWithContent('payload', datetime.now()))
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
		task.accept(MessageWithContent('payload2', datetime.now()))
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
	
if __name__ == '__main__':
	unittest.main()
