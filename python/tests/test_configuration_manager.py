from pathlib import Path
import unittest
import os
import tempfile

from ..model.configuration_manager import ConfigurationManager

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
		self.assertEqual(len(list), 5)  # Adjust based on expected number of plugins
		info0 = list[0].get('info', None)
		self.assertIsNotNone(info0, 'info0 failed')
		self.assertEqual(info0['id'], 'countdown', 'info0.id failed')
		self.assertEqual(info0['class'], 'Countdown', 'info0.class failed')
		info1 = list[1].get('info', None)
		self.assertIsNotNone(info1, 'info1 failed')
		self.assertEqual(info1['id'], 'debug', 'info1.id failed')
		self.assertEqual(info1['class'], 'DebugPlugin', 'info1.class failed')

	def test_enum_datasources(self):
		cm = ConfigurationManager()
		list = cm.enum_datasources()
		self.assertIsNotNone(list)
		self.assertEqual(len(list), 6)  # Adjust based on expected number of datasources
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
		self.assertEqual(len(plugins), 5)  # Adjust based on expected number of loaded plugins
		plugin = plugins.get('debug', None)
		self.assertIsNotNone(plugin, 'plugin debug failed')
		self.assertEqual(plugin.id, 'debug')
		self.assertEqual(plugin.name, 'Debug Plugin')

	def test_load_datasources(self):
		cm = ConfigurationManager()
		infos = cm.enum_datasources()
		datasources = cm.load_datasources(infos)
		self.assertIsNotNone(datasources)
		self.assertEqual(len(datasources), 6)  # Adjust based on expected number of loaded datasources
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

if __name__ == "__main__":
    unittest.main()