import unittest
import logging
from ..task.basic_task import DispatcherTask
from ..task.messages import ExecuteMessage, ExecuteMessageWithContent, QuitMessage

class RecordingTask(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received = []
		self._register_handler(ExecuteMessage, self._execute_message)

	def _execute_message(self, msg: ExecuteMessage):
		self.received.append(msg.content)

class TestDispatcherTask(unittest.TestCase):
	def test_execute_message(self):
		task = RecordingTask()
		task.start()
		task.send(ExecuteMessageWithContent("Hello"))
		task.send(QuitMessage())
		task.join()
		self.assertFalse(task.is_alive())
		self.assertEqual(len(task.received), 1, 'Should have received 1 messages')
		self.assertEqual(task.received[0], "Hello", 'Message content mismatch')

	def test_quit_message_stops_thread(self):
		task = RecordingTask()
		task.start()
		task.send(QuitMessage())
		task.join(timeout=1)
		self.assertFalse(task.is_alive())
		self.assertEqual(task.received, [])

if __name__ == "__main__":
	unittest.main()