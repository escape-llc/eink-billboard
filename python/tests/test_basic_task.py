from datetime import datetime
import unittest
from ..task.basic_task import DispatcherTask
from ..task.messages import BasicMessage, MessageWithContent, QuitMessage

class RecordContentTask(DispatcherTask):
	def __init__(self):
		super().__init__()
		self.msgs = []

	def _execute_message(self, msg: BasicMessage):
		self.msgs.append(msg.content)

class TestDispatcherTask(unittest.TestCase):
	def test_message_with_content(self):
		task = RecordContentTask()
		task.start()
		task.accept(MessageWithContent("Hello", datetime.now()))
		task.accept(QuitMessage(datetime.now()))
		task.join()
		self.assertFalse(task.is_alive())
		self.assertEqual(len(task.msgs), 1, 'Should have received 1 messages')
		self.assertEqual(task.msgs[0], "Hello", 'Message content mismatch')

	def test_quit_message_stops_thread(self):
		task = RecordContentTask()
		task.start()
		task.accept(QuitMessage(datetime.now()))
		task.join(timeout=1)
		self.assertFalse(task.is_alive())
		self.assertEqual(task.msgs, [])

if __name__ == "__main__":
	unittest.main()