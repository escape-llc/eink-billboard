from types import SimpleNamespace
import unittest
import tempfile
from datetime import datetime

from python.tests.utils import ConstantTimeOfDay

from ..model.configuration_watcher import MessageSinkHandler, ConfigurationWatcher

class _RecordingSink:
	def __init__(self):
		self.messages = []
	def accept(self, msg):
		self.messages.append(msg)

class TestConfigurationWatcher(unittest.TestCase):
	def test_message_sink_handler_sends_events(self):
		now = datetime(2020, 1, 2, 3, 4, 5)
		tod = ConstantTimeOfDay(now)
		sink = _RecordingSink()

		handler = MessageSinkHandler(tod, sink)

		# simulate created event
		ev = SimpleNamespace(is_directory=False, src_path='a/b/c.txt')
		handler.on_created(ev)
		self.assertEqual(len(sink.messages), 1)
		m = sink.messages[-1]
		self.assertEqual(m.type, 'created')
		self.assertEqual(m.path, 'a/b/c.txt')
		self.assertEqual(m.timestamp, now)

		# simulate modified event
		ev2 = SimpleNamespace(is_directory=False, src_path='d/e/f.txt')
		handler.on_modified(ev2)
		self.assertEqual(sink.messages[-1].type, 'modified')
		self.assertEqual(sink.messages[-1].path, 'd/e/f.txt')

		# simulate deleted event
		ev3 = SimpleNamespace(is_directory=False, src_path='z.txt')
		handler.on_deleted(ev3)
		self.assertEqual(sink.messages[-1].type, 'deleted')
		self.assertEqual(sink.messages[-1].path, 'z.txt')

		# simulate moved event (dest_path present but handler uses src_path)
		ev4 = SimpleNamespace(is_directory=False, src_path='old.txt', dest_path='new.txt')
		handler.on_moved(ev4)
		self.assertEqual(sink.messages[-1].type, 'moved')
		self.assertEqual(sink.messages[-1].path, 'old.txt')

	def test_configuration_watcher_start_stop_and_double_start(self):
		now = datetime(2020, 1, 2, 3, 4, 5)
		tod = ConstantTimeOfDay(now)
		sink = _RecordingSink()
		# use a temporary directory as root path
		with tempfile.TemporaryDirectory() as td:
			watcher = ConfigurationWatcher(tod, sink, root_path=td)
			# start should create and start an Observer thread
			watcher.start()
			# starting again should raise
			with self.assertRaises(RuntimeError):
				watcher.start()
			# stop should cleanly stop the observer
			watcher.stop()

if __name__ == '__main__':
	unittest.main()
