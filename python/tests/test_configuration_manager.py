import threading
import unittest
import os
import tempfile
from pathlib import Path

from ..model.configuration_manager import ConfigurationManager
from ..model.configuration_manager import ConfigurationObject

class TestConfigurationManager(unittest.TestCase):
	def test_os_path_windows(self):
		ppath = "C:\\path\\to\\some\\folder"
		plugins = os.path.join(ppath, "plugins")
		self.assertEqual(plugins, "C:\\path\\to\\some\\folder\\plugins")
		pobj = Path(ppath)
		storage = os.path.join(pobj.parent, ".storage")
		self.assertEqual(storage, "C:\\path\\to\\some\\.storage")

	def test_enum_plugins(self):
		cm = ConfigurationManager()
		list = cm.enum_plugins()
		self.assertIsNotNone(list)
		self.assertEqual(len(list), 3)  # Adjust based on expected number of plugins
		info0 = list[0].get('info', None)
		self.assertIsNotNone(info0, 'info0 failed')
		self.assertEqual(info0['id'], 'debug', 'info0.id failed')
		self.assertEqual(info0['class'], 'DebugPlugin', 'info0.class failed')
		info1 = list[1].get('info', None)
		self.assertIsNotNone(info1, 'info1 failed')
		self.assertEqual(info1['id'], 'interstitial', 'info1.id failed')
		self.assertEqual(info1['class'], 'Interstitial', 'info1.class failed')

	def test_enum_datasources(self):
		cm = ConfigurationManager()
		list = cm.enum_datasources()
		self.assertIsNotNone(list)
		self.assertEqual(len(list), 8)  # Adjust based on expected number of datasources
		info0 = list[0].get('info', None)
		self.assertIsNotNone(info0, 'info0 failed')
		self.assertEqual(info0['id'], 'clock')
		self.assertEqual(info0['class'], 'Clock')
		info1 = list[1].get('info', None)
		self.assertIsNotNone(info1, 'info1 failed')
		self.assertEqual(info1['id'], 'comic')
		self.assertEqual(info1['class'], 'ComicFeed')

	def test_load_plugins(self):
		cm = ConfigurationManager()
		infos = cm.enum_plugins()
		plugins = cm.load_plugins(infos)
		self.assertIsNotNone(plugins)
		self.assertEqual(len(plugins), 3)  # Adjust based on expected number of loaded plugins
		plugin = plugins.get('debug', None)
		self.assertIsNotNone(plugin, 'plugin debug failed')
		self.assertEqual(plugin.id, 'debug')
		self.assertEqual(plugin.name, 'Debug Plugin')

	def test_load_datasources(self):
		cm = ConfigurationManager()
		infos = cm.enum_datasources()
		datasources = cm.load_datasources(infos)
		self.assertIsNotNone(datasources)
		self.assertEqual(len(datasources), 8)  # Adjust based on expected number of loaded datasources
		datasource = datasources.get('comic', None)
		self.assertIsNotNone(datasource, 'datasource comic failed')
		self.assertEqual(datasource.name, 'Comic Plugin')

	def test_load_save_plugin_state(self):
		with tempfile.TemporaryDirectory() as tempdir:
			# Use a temporary directory for storage to avoid side effects
			cm = ConfigurationManager(storage_path=tempdir)
			cm.ensure_folders()
			pcm = cm.plugin_manager('debug')
			self.assertIsNotNone(pcm)
			pcm.ensure_folders()
			state = pcm.load_state()
			self.assertIsNone(state)

			test_state = {'key': 'value'}
			pcm.save_state(test_state)

			loaded_state = pcm.load_state()
			self.assertIsNotNone(loaded_state)
			self.assertEqual(loaded_state, test_state, 'Loaded state should match saved state')

class TestConfigurationObject(unittest.TestCase):
	def test_get_concurrent_loader_called_once(self):
		calls = {'count': 0}

		def loader(moniker: str):
			calls['count'] += 1
			return {'value': 42}

		def saver(moniker: str, value: dict):
			# no-op
			pass

		obj = ConfigurationObject('test', loader, saver)

		results = []

		def target():
			h, c = obj.get()
			results.append(c)

		threads = [threading.Thread(target=target) for _ in range(10)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()

		# Loader should be called exactly once and all threads get same result
		self.assertEqual(calls['count'], 1)
		self.assertEqual(len(results), 10)
		for r in results:
			self.assertEqual(r, {'value': 42})

	def test_save_with_matching_hash_persists_and_evicts(self):
		loader_calls = {'count': 0}
		saved = []

		def loader(moniker: str):
			loader_calls['count'] += 1
			return {'n': 0}

		def saver(moniker: str, value: dict):
			saved.append(value.copy())

		obj = ConfigurationObject('t1', loader, saver)

		# initial load
		hash0, content0 = obj.get()
		self.assertEqual(loader_calls['count'], 1)

		# save with matching hash
		new_content = {'n': 1}
		ok, new_hash = obj.save(hash0, new_content)
		self.assertTrue(ok)
		self.assertEqual(len(saved), 1)
		self.assertEqual(saved[0], new_content)

		# after save the in-memory cache is evicted, next get() should call loader again
		hash1, content1 = obj.get()
		self.assertEqual(loader_calls['count'], 2)

	def test_save_with_mismatched_hash_returns_false_and_does_not_save(self):
		loader_calls = {'count': 0}
		saved = []

		def loader(moniker: str):
			loader_calls['count'] += 1
			return {'x': 1}

		def saver(moniker: str, value: dict):
			saved.append(value.copy())

		obj = ConfigurationObject('t_bad', loader, saver)

		# initial load
		hash0, content0 = obj.get()
		self.assertEqual(loader_calls['count'], 1)

		# attempt to save with wrong hash
		ok, new_hash = obj.save('bad-hash', {'x': 2})
		self.assertFalse(ok)
		self.assertEqual(len(saved), 0)

		# ensure loader was not called again by the failed save
		self.assertEqual(loader_calls['count'], 1)

	def test_load_evict_save_returns_false(self):
		loader_calls = {'count': 0}
		saved = [{'a': 1}]

		def loader(moniker: str):
			loader_calls['count'] += 1
			return saved[-1]

		def saver(moniker: str, value: dict):
			saved.append(value.copy())

		obj = ConfigurationObject('t_evict', loader, saver)

		# initial load
		hash0, content0 = obj.get()
		self.assertEqual(loader_calls['count'], 1)
		# evict the in-memory cache
		obj.evict()
		# simulate an external change to the content
		saved.append({ 'modified': True })  # to track saves
		# attempt to save with old hash (should fail due to eviction)
		ok, new_hash = obj.save(hash0, {'a': 2})
		self.assertFalse(ok)
		self.assertIsNone(new_hash)
		self.assertEqual(len(saved), 2)
		# loader should have been called again due to eviction
		self.assertEqual(loader_calls['count'], 2)

	def test_load_empty_state(self):
		loader_calls = {'count': 0}

		def loader(moniker: str):
			loader_calls['count'] += 1
			return None  # Simulate empty state

		def saver(moniker: str, value: dict):
			# no-op
			pass

		obj = ConfigurationObject('empty', loader, saver)

		hash, content = obj.get()
		self.assertEqual(loader_calls['count'], 1)
		self.assertIsNone(content)
		self.assertIsNone(hash)

		# Subsequent get DOES call loader again (cached None)
		hash2, content2 = obj.get()
		self.assertEqual(loader_calls['count'], 2)
		self.assertIsNone(content2)
		self.assertIsNone(hash2)

	def test_load_empty_save_object(self):
		loader_calls = {'count': 0}
		saved = [None]

		def loader(moniker: str):
			loader_calls['count'] += 1
			return saved[-1]

		def saver(moniker: str, value: dict):
			saved.append(value.copy())

		obj = ConfigurationObject('empty_save', loader, saver)

		hash, content = obj.get()
		self.assertEqual(loader_calls['count'], 1)
		self.assertIsNone(content)
		self.assertIsNone(hash)

		# Save a new object
		new_content = {'new': 'data'}
		ok, new_hash = obj.save(hash, new_content)
		self.assertTrue(ok)
		self.assertEqual(len(saved), 2)
		self.assertEqual(saved[1], new_content)
		self.assertIsNotNone(new_hash)
		self.assertEqual(loader_calls['count'], 2)

	def test_context_manager_reentrant_allows_get_and_save(self):
		loader_calls = {'count': 0}
		saved = [{'a': 1}]

		def loader(moniker: str):
			loader_calls['count'] += 1
			return saved[-1].copy()

		def saver(moniker: str, value: dict):
			saved.append(value.copy())

		obj = ConfigurationObject('ctx', loader, saver)

		with obj as o:
			hash1, content1 = o.get()
			self.assertEqual(content1, {'a': 1})
			self.assertEqual(content1, saved[0])
			self.assertEqual(len(saved), 1)
			# verify we are modifying a copy and not the original
			content1["a"] = 2
			self.assertNotEqual(content1, saved[0])
			# save should re-acquire the same lock (RLock) and succeed
			ok, new_hash = o.save(hash1, content1)
			self.assertTrue(ok)
			self.assertEqual(len(saved), 2)

		# after context and save, cache evicted -> next get reloads
		hash2, content2 = obj.get()
		self.assertEqual(loader_calls['count'], 2)
		self.assertEqual(content2, {'a': 2})
		self.assertEqual(hash2, new_hash)

if __name__ == "__main__":
    unittest.main()