import unittest

from ..model.service_container import ServiceContainer

class TestServiceContainer(unittest.TestCase):
	def test_get_service_from_parent(self):
		parent = ServiceContainer()
		class ServiceA: pass
		service_obj = ServiceA()
		parent.add_service(ServiceA, service_obj)

		child = ServiceContainer(parent=parent)
		result = child.get_service(ServiceA)

		self.assertIs(result, service_obj)

	def test_child_overrides_parent_service(self):
		parent = ServiceContainer()
		class ServiceA: pass
		parent_obj = ServiceA()
		parent.add_service(ServiceA, parent_obj)

		child = ServiceContainer(parent=parent)
		child_obj = ServiceA()
		child.add_service(ServiceA, child_obj)

		# Child should return its own service
		self.assertIs(child.get_service(ServiceA), child_obj)
		# Parent remains unchanged
		self.assertIs(parent.get_service(ServiceA), parent_obj)

	def test_get_missing_service_returns_none(self):
		parent = ServiceContainer()
		child = ServiceContainer(parent=parent)

		class MissingService: pass
		self.assertIsNone(child.get_service(MissingService))

	def test_required_returns_instance(self):
		container = ServiceContainer()
		class ServiceX: pass
		obj = ServiceX()
		container.add_service(ServiceX, obj)
		# required() should return the registered instance
		self.assertIs(container.required(ServiceX), obj)

	def test_required_raises_when_missing(self):
		container = ServiceContainer()
		class MissingService: pass
		with self.assertRaises(ValueError):
			container.required(MissingService)

	def test_concurrent_add_same_type_raises(self):
		parent = ServiceContainer()
		child = ServiceContainer(parent=parent)

		class ServiceA: pass

		results = { 'success': [], 'error': [] }

		def worker(idx):
			try:
				child.add_service(ServiceA, ServiceA())
				results['success'].append(idx)
			except Exception as e:
				results['error'].append((idx, e))

		threads = [__import__('threading').Thread(target=worker, args=(i,)) for i in range(2)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()

		# Exactly one should succeed and one should error due to duplicate registration
		self.assertEqual(len(results['success']), 1)
		self.assertEqual(len(results['error']), 1)

	def test_concurrent_add_different_types(self):
		container = ServiceContainer()

		num = 5
		classes = []
		for i in range(num):
			cls = type(f'Svc{i}', (), {})
			classes.append(cls)

		def add_worker(idx, cls):
			container.add_service(cls, cls())

		threads = []
		for i, cls in enumerate(classes):
			t = __import__('threading').Thread(target=add_worker, args=(i, cls))
			threads.append(t)
			t.start()

		for t in threads:
			t.join()

		# Verify all services registered
		for cls in classes:
			self.assertIsNotNone(container.get_service(cls))

	def test_get_while_adding(self):
		container = ServiceContainer()

		class ServiceB: pass

		import threading, time

		got = []

		def reader():
			# keep trying until we find the service or timeout
			end = time.time() + 2.0
			while time.time() < end:
				inst = container.get_service(ServiceB)
				if inst is not None:
					got.append(inst)
					return
				time.sleep(0.01)

		r = threading.Thread(target=reader)
		r.start()

		# wait a bit then add service
		time.sleep(0.1)
		container.add_service(ServiceB, ServiceB())

		r.join()
		self.assertTrue(len(got) == 1)


if __name__ == '__main__':
	unittest.main()

