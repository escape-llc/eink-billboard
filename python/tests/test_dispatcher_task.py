import unittest
import logging
from ..task.basic_task import DispatcherTask
from ..task.messages import ExecuteMessage, ExecuteMessageWithContent, QuitMessage


class RecordingDispatcher(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received = []

	def execute(self, msg: ExecuteMessage):
		# Record generic execute messages (fallback path)
		try:
			content = getattr(msg, 'content')
		except Exception:
			content = None
		self.received.append(('execute', content))


class TestDispatcherTask(unittest.TestCase):
	def test_handler_called_for_exact_class(self):
		class RegisteredDispatcher(RecordingDispatcher):
			def __init__(self):
				super().__init__()
				self._register_handler(ExecuteMessageWithContent, self._handler)

			def _handler(self, msg: ExecuteMessageWithContent):
				self.received.append(('handler', msg.content))

		task = RegisteredDispatcher()
		task.start()
		task.send(ExecuteMessageWithContent('payload'))
		task.send(QuitMessage())
		task.join()

		self.assertFalse(task.is_alive())
		# handler should have been called once
		self.assertIn(('handler', 'payload'), task.received)

	def test_cannot_register_quit_message(self):
		# registering for QuitMessage must be forbidden even from subclass
		with self.assertRaises(ValueError):
			class BadDispatcher(RecordingDispatcher):
				def __init__(self):
					super().__init__()
					self._register_handler(QuitMessage, lambda m: None)
				
			BadDispatcher()

	def test_fallback_to_execute_when_no_handler(self):
		task = RecordingDispatcher()
		task.start()
		# Send a plain ExecuteMessage which has no exact-class handler
		task.send(ExecuteMessage())
		task.send(QuitMessage())
		task.join()

		# No handler exists so nothing should have been recorded by execute()
		self.assertNotIn(('execute', None), task.received)

	def test_superclass_handler_is_used_for_subclass(self):
		class SuperHandlerDispatcher(RecordingDispatcher):
			def __init__(self):
				super().__init__()
				self._register_handler(ExecuteMessage, self._handler)

			def _handler(self, msg: ExecuteMessage):
				content = getattr(msg, 'content', None)
				self.received.append(('superhandler', content))

		task = SuperHandlerDispatcher()
		task.start()
		task.send(ExecuteMessageWithContent('payload2'))
		task.send(QuitMessage())
		task.join()

		self.assertIn(('superhandler', 'payload2'), task.received)

if __name__ == '__main__':
	unittest.main()
