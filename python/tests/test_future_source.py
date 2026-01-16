import unittest
import time
from concurrent.futures import ThreadPoolExecutor

from ..task.future_source import FutureSource
from ..task.messages import BasicMessage
from .utils import FakePort

class TestMsg(BasicMessage):
	def __init__(self, text):
		super().__init__()
		self.text = text

class FutureSourceTests(unittest.TestCase):
	def test_future_success_triggers_continuation(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=2) as ex:
			fs = FutureSource("test", port, ex)

			def future_fn(is_cancelled):
				# simple computation
				return 42

			def continuation(cancelled, result, exception):
				self.assertFalse(cancelled)
				self.assertIsNone(exception)
				self.assertEqual(result, 42)
				return TestMsg('ok')

			cancel = fs.submit_future(future_fn, continuation)

			# wait for message to be sent
			got = port.wait_for_message(2.0)
			self.assertTrue(got, msg="Continuation message not received")
			self.assertEqual(len(port.messages), 1)
			self.assertIsInstance(port.messages[0], TestMsg)
			self.assertEqual(port.messages[0].text, 'ok')

	def test_future_exception_passed_to_continuation(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=2) as ex:
			fs = FutureSource("test", port, ex)

			def future_fn(is_cancelled):
				raise RuntimeError("boom")

			def continuation(cancelled, result, exception):
				self.assertFalse(cancelled)
				self.assertIsNone(result)
				self.assertIsNotNone(exception)
				self.assertIsInstance(exception, RuntimeError)
				return TestMsg('err-handled')

			fs.submit_future(future_fn, continuation)

			got = port.wait_for_message(2.0)
			self.assertTrue(got)
			self.assertEqual(len(port.messages), 1)
			self.assertIsInstance(port.messages[0], TestMsg)
			self.assertEqual(port.messages[0].text, 'err-handled')

	def test_cancel_before_completion_marks_cancelled(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=2) as ex:
			fs = FutureSource("test", port, ex)

			def future_fn(is_cancelled):
				# spin until cancelled
				start = time.time()
				while not is_cancelled():
					if time.time() - start > 5.0:
						break
					time.sleep(0.01)
				return 'done'

			def continuation(cancelled, result, exception):
				# we expect cancelled True when cancel request is made
				self.assertTrue(cancelled)
				return TestMsg('cancelled')

			cancel = fs.submit_future(future_fn, continuation)
			# request cancellation shortly after submit
			time.sleep(0.05)
			cancel()

			got = port.wait_for_message(2.0)
			self.assertTrue(got)
			self.assertEqual(len(port.messages), 1)
			self.assertIsInstance(port.messages[0], TestMsg)
			self.assertEqual(port.messages[0].text, 'cancelled')

	def test_shutdown_stops_executor(self):
		port = FakePort()
		ex = ThreadPoolExecutor(max_workers=1)
		fs = FutureSource("test", port, ex)
		fs.shutdown()
		# subsequent shutdown is harmless
		fs.shutdown()

	def test_ctor_invalid_owner(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=1) as ex:
			with self.assertRaises(ValueError):
				FutureSource(None, port, ex)

	def test_ctor_invalid_completion_port(self):
		with ThreadPoolExecutor(max_workers=1) as ex:
			with self.assertRaises(ValueError):
				FutureSource("owner", None, ex)

	def test_ctor_invalid_executor(self):
		port = FakePort()
		with self.assertRaises(ValueError):
			FutureSource("owner", port, None)

	def test_submit_future_invalid_future(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=1) as ex:
			fs = FutureSource("test", port, ex)
			with self.assertRaises(ValueError):
				fs.submit_future(None, lambda cancelled, result, exception: None)

	def test_submit_future_invalid_continuation(self):
		port = FakePort()
		with ThreadPoolExecutor(max_workers=1) as ex:
			fs = FutureSource("test", port, ex)
			with self.assertRaises(ValueError):
				fs.submit_future(lambda is_cancelled: None, None)


if __name__ == '__main__':
	unittest.main()
