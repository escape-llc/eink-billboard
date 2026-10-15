import json
import sys
import threading
import time
import types
from typing import Any
import unittest
from unittest import mock
import os
import tempfile
from pathlib import Path

from ..model.configuration_manager import ConfigurationManager, FileConfiguration, _internal_save
from ..model.configuration_manager import ConfigurationObject

class TestFreshStorage(unittest.TestCase):
	def test_a_new_device_has_a_schedules_folder_so_the_layers_can_start(self):
		"""Git keeps no empty folder: the factory tree had none, and the playlist and timer layers failed on every new install (found on a Pi)."""
		with tempfile.TemporaryDirectory() as folder:
			cm = ConfigurationManager(storage_path=folder)
			cm.hard_reset()
			self.assertTrue(os.path.isdir(os.path.join(folder, "schedules")))
			cm.schedule_manager()  # does not raise

	def test_a_storage_seeded_without_one_gets_it_at_the_next_start(self):
		"""A device (or a volume) seeded before the fix: the seeding does not run again, the start must put the folder back."""
		import shutil
		with tempfile.TemporaryDirectory() as folder:
			cm = ConfigurationManager(storage_path=folder)
			cm.hard_reset()
			shutil.rmtree(os.path.join(folder, "schedules"))
			ConfigurationManager(storage_path=folder).ensure_folders()
			self.assertTrue(os.path.isdir(os.path.join(folder, "schedules")))

class TestConfigurationManager(unittest.TestCase):
	@unittest.skipUnless(sys.platform == "win32", "This test is for Windows only")
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
		by_id = { px['info']['id']: px['info'] for px in list }
		self.assertEqual(set(by_id), { 'interstitial', 'overlay', 'slide-show' })
		self.assertEqual(by_id['interstitial']['class'], 'PriorityUpdateAsync')
		self.assertEqual(by_id['overlay']['class'], 'OverlayAsync')
		self.assertEqual(by_id['slide-show']['class'], 'SlideShowAsync')

	def test_enum_datasources(self):
		cm = ConfigurationManager()
		list = cm.enum_datasources()
		self.assertIsNotNone(list)
		by_id = { px['info']['id']: px['info'] for px in list }
		self.assertEqual(set(by_id), { 'ai-image', 'calendar', 'clock', 'comic', 'countdown', 'image-folder', 'newspaper', 'openai', 'openai-image', 'openai-text', 'openweathermap', 'rss', 'today', 'weather', 'weather-overlay', 'reminder-overlay', 'apod', 'wpotd', 'year_progress' })
		self.assertEqual(by_id['clock']['class'], 'ClockAsync')
		self.assertEqual(by_id['comic']['class'], 'ComicFeedAsync')
		self.assertEqual(by_id['today']['class'], 'TodayAsync')

	def test_load_plugins(self):
		cm = ConfigurationManager()
		infos = cm.enum_plugins()
		plugins = cm.load_plugins(infos)
		self.assertIsNotNone(plugins)
		self.assertEqual(len(plugins), 3)  # priority update (id interstitial), overlay, slide-show
		plugin = plugins.get('interstitial', None)
		self.assertIsNotNone(plugin, 'plugin interstitial failed')
		if plugin is not None:
			self.assertEqual(plugin.id, 'interstitial')
			self.assertEqual(plugin.name, 'Priority Update')

	def test_load_datasources(self):
		cm = ConfigurationManager()
		infos = cm.enum_datasources()
		datasources = cm.load_datasources(infos)
		self.assertIsNotNone(datasources)
		self.assertEqual(len(datasources), 19)
		datasource = datasources.get('comic', None)
		self.assertIsNotNone(datasource, 'datasource comic failed')
		if datasource is not None:
			self.assertEqual(datasource.id, 'comic')
			self.assertEqual(datasource.name, 'Comic')

	def test_stale_schemas_are_refreshed_and_nothing_else_is_touched(self):
		with tempfile.TemporaryDirectory() as tempdir:
			cm = ConfigurationManager(storage_path=tempdir)
			cm.hard_reset()
			schema = os.path.join(tempdir, "schemas", "theme.json")
			settings = os.path.join(tempdir, "settings", "theme-settings.json")
			with open(schema, "w") as f:
				f.write('{"old": true}')
			with open(settings, "w") as f:
				f.write('{"hue": 5}')
			self.assertEqual(cm.refresh_schemas(), ["theme.json"])
			with open(schema, "rb") as f, open(os.path.join(cm.NVE_PATH, "schemas", "theme.json"), "rb") as g:
				self.assertEqual(f.read(), g.read())
			with open(settings) as f:
				self.assertEqual(f.read(), '{"hue": 5}')
			# up to date: nothing to do
			self.assertEqual(cm.refresh_schemas(), [])
			self.assertEqual([n for n in os.listdir(os.path.join(tempdir, "schemas")) if n.startswith(".tmp")], [])

	def test_settings_gain_the_fields_added_since_they_were_stored(self):
		with tempfile.TemporaryDirectory() as tempdir:
			cm = ConfigurationManager(storage_path=tempdir)
			cm.hard_reset()
			theme = os.path.join(tempdir, "settings", "theme-settings.json")
			rss = os.path.join(tempdir, "datasources", "rss", "settings.json")
			with open(theme, "w") as f:
				json.dump({ "theme": "tetradic", "hue": 5, "saturation": 50, "lightness": 40 }, f)
			with open(rss, "w") as f:
				json.dump({}, f)
			changed = cm.upgrade_settings()
			self.assertIn("theme-settings.json", changed)
			self.assertIn("datasources/rss", changed)
			with open(theme) as f:
				doc = json.load(f)
			# what the user chose is kept, what is new has its default (a null too, so the field is there)
			self.assertEqual((doc["theme"], doc["hue"], doc["lightness"]), ("tetradic", 5, 40))
			self.assertEqual((doc["fontBody"], doc["fontScale"]), ("Jost", 1))
			self.assertIn("fontHeading", doc)
			with open(rss) as f:
				self.assertEqual(json.load(f), { "feeds": [] })
			# nothing more to add, and the cached documents read the new ones
			self.assertEqual(cm.upgrade_settings(), [])
			_, read = cm.settings_manager().open("theme").get()
			assert read is not None
			self.assertEqual(read["fontBody"], "Jost")

	def test_settings_that_moved_to_another_data_source_go_there_once(self):
		with tempfile.TemporaryDirectory() as tempdir:
			cm = ConfigurationManager(storage_path=tempdir)
			cm.hard_reset()
			weather = os.path.join(tempdir, "datasources", "weather", "settings.json")
			os.makedirs(os.path.dirname(weather), exist_ok=True)
			with open(weather, "w") as f:
				json.dump({ "apiKey": "owm-secret", "units": "imperial", "currentCacheHours": 1, "forecastCacheHours": 3, "staleDays": 9, "other": True }, f)
			with self.assertLogs("python.model.configuration_manager", level="INFO") as logged:
				changed = cm.upgrade_settings()
			self.assertIn("datasources/openweathermap", changed)
			self.assertNotIn("owm-secret", "\n".join(logged.output), "the names only, never a value")
			_, moved = cm.datasource_manager("openweathermap").open().get()
			assert moved is not None
			self.assertEqual({ k: moved[k] for k in ("apiKey", "units", "currentCacheHours", "forecastCacheHours", "staleDays") },
				{ "apiKey": "owm-secret", "units": "imperial", "currentCacheHours": 1, "forecastCacheHours": 3, "staleDays": 9 })
			# out of the old document (its schema no longer masks the key), what was not moved stays
			with open(weather) as f:
				self.assertEqual(json.load(f), { "other": True })
			# once: the old document holds nothing to move any more
			self.assertEqual(cm.upgrade_settings(), [])

	def test_a_missing_or_unreadable_settings_file_is_left_alone(self):
		with tempfile.TemporaryDirectory() as tempdir:
			cm = ConfigurationManager(storage_path=tempdir)
			cm.hard_reset()
			os.remove(os.path.join(tempdir, "settings", "theme-settings.json"))
			with open(os.path.join(tempdir, "settings", "system-settings.json"), "w") as f:
				f.write("not json")
			cm.upgrade_settings()
			self.assertFalse(os.path.exists(os.path.join(tempdir, "settings", "theme-settings.json")))
			with open(os.path.join(tempdir, "settings", "system-settings.json")) as f:
				self.assertEqual(f.read(), "not json")

	def test_load_save_plugin_state(self):
		with tempfile.TemporaryDirectory() as tempdir:
			# Use a temporary directory for storage to avoid side effects
			cm = ConfigurationManager(storage_path=tempdir)
			cm.ensure_folders()
			pcm = cm.plugin_manager('debug')
			self.assertIsNotNone(pcm)
			state_cob = pcm.open_state()
			# brand new state should be None
			hash, state = state_cob.get()
			self.assertIsNone(state)
			self.assertIsNone(hash)

			# save a new state
			test_state = {'key': 'value'}
			ok, new_hash = state_cob.save(hash, test_state)
			self.assertTrue(ok, 'Save should succeed')
			self.assertIsNotNone(new_hash, 'New hash should not be None')

			# load back the saved state
			loaded_hash, loaded_state = state_cob.get()
			self.assertIsNotNone(loaded_state)
			self.assertEqual(loaded_hash, new_hash, 'Loaded hash should match new hash')
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
		saved: list[Any] = [None]

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
			self.assertIsNotNone(content1)
			self.assertEqual(content1, {'a': 1})
			self.assertEqual(content1, saved[0])
			self.assertEqual(len(saved), 1)
			# verify we are modifying a copy and not the original
			if content1 is not None:
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
def _write_info(root: str, folder: str, name: str, text: str):
	path = os.path.join(root, folder, name)
	os.makedirs(path, exist_ok=True)
	with open(os.path.join(path, f"{folder[:-1]}-info.json"), "w") as f:
		f.write(text)

class _Fine:
	def __init__(self, ident, name):
		pass

class _Exploding:
	def __init__(self, ident, name):
		raise ValueError("ctor failed")

class TestCollectInfoRobustness(unittest.TestCase):
	"""A bad descriptor must cost only that plugin/datasource, never every route and the start-up."""
	GOOD = '{"id": "good", "name": "Good", "class": "G", "file": "g.py", "module": "m.good", "settings": {"schema": {"properties": []}}}'

	def _cm(self, root: str) -> ConfigurationManager:
		return ConfigurationManager(source_path=root, storage_path=os.path.join(root, ".storage"))

	def test_malformed_descriptors_are_skipped_and_logged(self):
		with tempfile.TemporaryDirectory() as root:
			_write_info(root, "plugins", "a-bad-json", "{ not json")
			_write_info(root, "plugins", "b-not-an-object", "[1, 2]")
			_write_info(root, "plugins", "c-good", self.GOOD)
			cm = self._cm(root)
			with self.assertLogs("python.model.configuration_manager", level="ERROR") as logs:
				found = cm.enum_plugins()
			self.assertEqual([x["info"]["id"] for x in found], ["good"])
			text = "\n".join(logs.output)
			self.assertIn("a-bad-json", text)
			self.assertIn("b-not-an-object", text)

	def test_a_null_settings_entry_is_tolerated_by_the_api(self):
		from ..web.routers.settings import _settings_properties
		with tempfile.TemporaryDirectory() as root:
			_write_info(root, "datasources", "n", '{"id": "n", "settings": null}')
			_write_info(root, "datasources", "m", '{"id": "m", "settings": {"schema": null}}')
			cm = self._cm(root)
			found = cm.enum_datasources()
			self.assertEqual(len(found), 2)
			for item in found:
				self.assertEqual(_settings_properties(item), [])

	def test_a_plugin_that_fails_to_load_does_not_stop_the_others(self):
		import importlib
		real = importlib.import_module
		def fake(name, *a, **k):
			if name == "m.bad":
				raise RuntimeError("boom")
			if name == "m.ctor":
				return types.SimpleNamespace(C=_Exploding)
			if name == "m.good":
				return types.SimpleNamespace(G=_Fine)
			return real(name, *a, **k)
		with tempfile.TemporaryDirectory() as root:
			infos = []
			for ident in ("bad", "ctor", "good"):
				folder = os.path.join(root, "plugins", ident)
				os.makedirs(folder)
				open(os.path.join(folder, "p.py"), "w").close()
				cls = {"bad": "X", "ctor": "C", "good": "G"}[ident]
				infos.append({ "info": { "id": ident, "name": ident, "class": cls, "file": "p.py", "module": f"m.{ident}" }, "path": folder })
			cm = self._cm(root)
			with mock.patch.object(importlib, "import_module", fake):
				with self.assertLogs("python.model.configuration_manager", level="ERROR") as logs:
					plugins = cm.load_plugins(infos)
					sources = cm.load_datasources(infos)
			self.assertEqual(list(plugins), ["good"])
			self.assertEqual(list(sources), ["good"])
			text = "\n".join(logs.output)
			self.assertIn("bad", text)
			self.assertIn("ctor", text)

class TestConfigurationObjectOnDisk(unittest.TestCase):
	def test_an_outside_edit_is_never_overwritten_by_a_stale_cache(self):
		with tempfile.TemporaryDirectory() as root:
			path = os.path.join(root, "s.json")
			_internal_save(path, { "a": 1 })
			cob = FileConfiguration(path)
			old_hash, _ = cob.get()
			# an outside edit, before the watcher's debounce could evict the cache
			with open(path, "w") as f:
				json.dump({ "a": 2, "outside": True }, f)
			ok, _ = cob.save(old_hash, { "a": 3 })
			self.assertFalse(ok)
			with open(path) as f:
				self.assertEqual(json.load(f), { "a": 2, "outside": True })
			# the next get() sees the outside edit, and a save with its hash commits
			new_hash, content = cob.get()
			self.assertEqual(content, { "a": 2, "outside": True })
			self.assertTrue(cob.save(new_hash, { "a": 4 })[0])

	def test_hard_reset_clears_the_object_cache(self):
		with tempfile.TemporaryDirectory() as root:
			cm = ConfigurationManager(storage_path=os.path.join(root, ".storage"))
			cm.hard_reset()
			cob = cm.settings_manager().open("system")
			_, before = cob.get()
			self.assertIsNotNone(before)
			# the cache holds content; a reset must not leave it behind
			cob._content = { "stale": True }
			cob._hash = "stale"
			cm.hard_reset()
			_, after = cm.settings_manager().open("system").get()
			self.assertNotIn("stale", after or {})

	def test_save_state_and_delete_state_keep_the_cached_object_consistent(self):
		with tempfile.TemporaryDirectory() as root:
			cm = ConfigurationManager(storage_path=root)
			cm.ensure_folders()
			pcm = cm.plugin_manager("p")
			cob = pcm.open_state()
			self.assertEqual(cob.get(), (None, None))
			pcm.save_state({ "k": 1 })
			self.assertEqual(cob.get()[1], { "k": 1 })
			pcm.save_state({ "k": 2 })
			self.assertEqual(cob.get()[1], { "k": 2 })
			pcm.delete_state()
			self.assertEqual(cob.get(), (None, None))

class TestWatchLocking(unittest.TestCase):
	def test_evicting_a_busy_object_does_not_block_obtaining_others(self):
		with tempfile.TemporaryDirectory() as root:
			cm = ConfigurationManager(storage_path=root)
			busy_path = os.path.join(root, "busy.json")
			busy = cm.obtain(busy_path, FileConfiguration)[1]
			held = threading.Event()
			release = threading.Event()
			def holder():
				with busy:
					held.set()
					release.wait(10)
			t1 = threading.Thread(target=holder, daemon=True)
			t1.start()
			self.assertTrue(held.wait(5))
			t2 = threading.Thread(target=cm.watch, args=("modified", busy_path), daemon=True)
			t2.start()
			time.sleep(0.2)  # let the watcher thread reach the busy object
			result = []
			t3 = threading.Thread(target=lambda: result.append(cm.obtain(os.path.join(root, "other.json"), FileConfiguration)), daemon=True)
			t3.start()
			t3.join(2)
			try:
				self.assertFalse(t3.is_alive(), "obtain() of another moniker was blocked by an eviction")
			finally:
				release.set()
				t1.join(5)
				t2.join(5)

class TestNeedsSeeding(unittest.TestCase):
	"""A container's storage is a mounted volume, which exists (empty) on the first start: that must be seeded, anything else never."""
	def test_missing_and_empty_folders_are_seeded_and_anything_else_is_not(self):
		with tempfile.TemporaryDirectory() as tmp:
			self.assertTrue(ConfigurationManager.needs_seeding(os.path.join(tmp, "missing")))
			self.assertTrue(ConfigurationManager.needs_seeding(tmp), "an empty folder (a new volume)")
			with open(os.path.join(tmp, "settings.json"), "w") as f:
				f.write("{}")
			self.assertFalse(ConfigurationManager.needs_seeding(tmp), "somebody's storage")
			self.assertFalse(ConfigurationManager.needs_seeding(os.path.join(tmp, "settings.json")), "a file is not ours to replace")
