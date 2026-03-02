import unittest
import threading
import asyncio

from ..task.async_worker_pool import AsyncWorkerPool

async def async_unit_of_work(task_id, duration):
	await asyncio.sleep(duration)
	return f"Data from {task_id}"

class TestAsyncWorkerPool(unittest.TestCase):
    def setUp(self):
        self.pool = AsyncWorkerPool()
        self.pool.start()

    def tearDown(self):
        try:
            self.pool.shutdown()
        except Exception:
            pass

    def test_submit_and_result(self):
        fut = self.pool.submit(async_unit_of_work("T1", 0.01))
        result = fut.result(timeout=1)
        self.assertEqual(result, "Data from T1")

    def test_callback_called_on_success(self):
        ev = threading.Event()
        result_container = {}

        def cb(fut):
            try:
                result_container['value'] = fut.result()
            except Exception as e:
                result_container['exc'] = e
            ev.set()

        self.pool.submit(async_unit_of_work("T2", 0.01), callback=cb)
        self.assertTrue(ev.wait(1), "Callback was not called in time")
        self.assertEqual(result_container.get('value'), "Data from T2")

    def test_exception_propagates_and_callback_receives_exc(self):
        ev = threading.Event()
        exc_container = {}

        async def bad():
            raise RuntimeError("boom")

        def cb(fut):
            try:
                fut.result()
            except Exception as e:
                exc_container['e'] = e
            ev.set()

        fut = self.pool.submit(bad(), callback=cb)
        with self.assertRaises(RuntimeError):
            fut.result(timeout=1)

        self.assertTrue(ev.wait(1))
        self.assertIsInstance(exc_container.get('e'), RuntimeError)

    def test_submit_after_shutdown_raises(self):
        self.pool.shutdown()

        async def quick():
            return "x"

        with self.assertRaises(RuntimeError):
            self.pool.submit(quick())


if __name__ == '__main__':
    unittest.main()