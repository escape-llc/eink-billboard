import threading
import unittest
import tempfile
from datetime import datetime
from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent, FileMovedEvent

from .utils import ConstantTimeOfDay
from ..model.configuration_watcher import MessageSinkHandler, ConfigurationWatcher

class _RecordingSink:
	def __init__(self):
		self.messages = []
		self.signal = threading.Event()
		self.signal.clear()
	def reset(self):
		self.messages = []
		self.signal.clear()
	def accept(self, msg):
		self.messages.append(msg)
		self.signal.set()

class TestConfigurationWatcher(unittest.TestCase):
	def test_message_sink_handler_sends_events(self):
		now = datetime(2020, 1, 2, 3, 4, 5)
		tod = ConstantTimeOfDay(now)
		sink = _RecordingSink()

		handler = MessageSinkHandler(tod, sink, 0.1)

		# simulate created event
		ev = FileCreatedEvent(src_path='a/b/c.txt')
		handler.on_created(ev)
		sig = sink.signal.wait(timeout=0.2)
		self.assertTrue(sig, 'created: Event was not received within timeout')
		self.assertEqual(len(sink.messages), 1)
		mx = sink.messages[0]
		self.assertEqual(mx.type, 'created')
		self.assertEqual(mx.path, 'a/b/c.txt')
		self.assertEqual(mx.timestamp, now)

		# simulate modified event
		sink.reset()
		ev2 = FileModifiedEvent(src_path='d/e/f.txt')
		handler.on_modified(ev2)
		sig = sink.signal.wait(timeout=0.2)
		self.assertTrue(sig, 'modified: Event was not received within timeout')
		self.assertEqual(len(sink.messages), 1)
		mx = sink.messages[0]
		self.assertEqual(mx.type, 'modified')
		self.assertEqual(mx.path, 'd/e/f.txt')

		# simulate deleted event
		sink.reset()
		ev3 = FileDeletedEvent(src_path='z.txt')
		handler.on_deleted(ev3)
		sig = sink.signal.wait(timeout=0.2)
		self.assertTrue(sig, 'deleted: Event was not received within timeout')
		self.assertEqual(len(sink.messages), 1)
		mx = sink.messages[0]
		self.assertEqual(mx.type, 'deleted')
		self.assertEqual(mx.path, 'z.txt')

		# simulate moved event (dest_path present but handler uses src_path)
		sink.reset()
		ev4 = FileMovedEvent(src_path='old.txt', dest_path='new.txt')
		handler.on_moved(ev4)
		sig = sink.signal.wait(timeout=0.2)
		self.assertTrue(sig, 'moved: Event was not received within timeout')
		self.assertEqual(len(sink.messages), 1)
		mx = sink.messages[0]
		self.assertEqual(mx.type, 'moved')
		self.assertEqual(mx.path, 'old.txt')

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
