import unittest
from ..task.basic_task import DispatcherTask
from ..task.messages import BasicMessage, MessageWithContent, QuitMessage

class RecordingTask(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.received = []

	def _execute_message(self, msg: BasicMessage):
		self.received.append(msg.content)

class TestDispatcherTask(unittest.TestCase):
	def test_message_with_content(self):
		task = RecordingTask()
		task.start()
		task.accept(MessageWithContent("Hello"))
		task.accept(QuitMessage())
		task.join()
		self.assertFalse(task.is_alive())
		self.assertEqual(len(task.received), 1, 'Should have received 1 messages')
		self.assertEqual(task.received[0], "Hello", 'Message content mismatch')

	def test_quit_message_stops_thread(self):
		task = RecordingTask()
		task.start()
		task.accept(QuitMessage())
		task.join(timeout=1)
		self.assertFalse(task.is_alive())
		self.assertEqual(task.received, [])

if __name__ == "__main__":
	unittest.main()