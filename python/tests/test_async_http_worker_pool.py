import unittest

from ..task.async_http_worker_pool import AsyncHttpWorkerPool

class TestHttpPoolTimeout(unittest.TestCase):
	def test_client_waits_longer_than_httpxs_default(self):
		# httpx's default is 5 s for connecting and for each read: a comic on a slow link timed out
		pool = AsyncHttpWorkerPool()
		pool.start()
		try:
			assert pool.client is not None
			timeout = pool.client.timeout
			self.assertGreaterEqual(timeout.connect or 0, 10.0)
			self.assertGreaterEqual(timeout.read or 0, 30.0)
		finally:
			pool.shutdown()
