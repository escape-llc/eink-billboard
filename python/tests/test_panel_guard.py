import threading
import unittest

from ..display.panel_guard import PanelGuard

class TestPanelGuard(unittest.TestCase):
	def test_a_result_and_a_failure_come_back_to_the_caller(self):
		guard = PanelGuard()
		self.assertEqual(guard.run(lambda: 7, 1.0), 7)
		def broken():
			raise OSError("spi")
		with self.assertRaisesRegex(OSError, "spi"):
			guard.run(broken, 1.0)
		self.assertFalse(guard.busy())

	def test_a_call_that_does_not_come_back_is_a_timeout_and_blocks_the_next_until_it_does(self):
		release = threading.Event()
		self.addCleanup(release.set)
		guard = PanelGuard()
		with self.assertRaises(TimeoutError):
			guard.run(lambda: release.wait(5), 0.1)
		self.assertTrue(guard.busy())
		with self.assertRaisesRegex(RuntimeError, "has not finished"):
			guard.run(lambda: 1, 1.0)
		release.set()
		guard._worker.join(1)  # type: ignore[union-attr]
		self.assertEqual(guard.run(lambda: 1, 1.0), 1)

if __name__ == "__main__":
	unittest.main()
