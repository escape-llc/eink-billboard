import ast
import os
import tempfile
import unittest

from ..model.configuration_manager import ConfigurationManager

PYTHON = os.path.join(os.path.dirname(__file__), "..")
# the only modules that touch the storage's files; everything else goes through the ConfigurationManager and its sub-managers
STORAGE = { "model/storage_files.py", "model/configuration_manager.py", "model/schedule_manager.py" }
# (the vendored Waveshare drivers, python/display/waveshare_epd, are Waveshare's: they read the board's /proc, not the storage)
# file calls that are not about the storage: render scratch files (temp), the system's zone file, the logging configuration, the mock display's output (system temp), the machine's own `/proc` and `/sys` (the System page)
OTHER = { "utils/image_utils.py", "model/time_of_day.py", "eink-billboard.py", "display/mock_display.py", "web/system_info.py" }
FILE_CALLS = { "open", "makedirs", "mkdir", "remove", "replace", "rename", "rmtree", "copytree", "copyfile", "move", "unlink", "write_text", "write_bytes", "read_text", "read_bytes" }
PRIMITIVES = { "save_json", "load_json", "_internal_save", "_internal_load" }

def _problems(path: str) -> list[str]:
	with open(path, encoding="utf-8") as f:
		tree = ast.parse(f.read())
	found = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Call):
			fn = node.func
			name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
			owner = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
			bare = isinstance(fn, ast.Name) and name == "open"
			module = owner in ("os", "shutil") and name in FILE_CALLS
			path_method = isinstance(fn, ast.Attribute) and name in ("write_text", "write_bytes", "read_text", "read_bytes")
			if bare or module or path_method or name in PRIMITIVES:
				found.append(f"line {node.lineno}: {name}")
		elif isinstance(node, (ast.ImportFrom, ast.Import)):
			names = [a.name for a in node.names]
			if any(n in PRIMITIVES for n in names):
				found.append(f"line {node.lineno}: imports {names}")
	return found

class TestStorageAccess(unittest.TestCase):
	def test_only_the_configuration_manager_touches_the_storage_files(self):
		"""Every file access goes through the configuration manager subsystem (AGENTS.md: the chain of trust on paths)."""
		offenders = {}
		for folder, dirs, files in os.walk(PYTHON):
			dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".storage", "static", "storage", "waveshare_epd")]
			for file in files:
				if not file.endswith(".py"):
					continue
				full = os.path.join(folder, file)
				rel = os.path.relpath(full, PYTHON).replace(os.sep, "/")
				if rel in STORAGE or rel in OTHER:
					continue
				problems = _problems(full)
				if problems:
					offenders[rel] = problems
		self.maxDiff = None
		self.assertEqual(offenders, {}, "These modules touch files themselves: use the configuration manager (or add the file to OTHER if it is not the storage).")

	def test_a_text_file_is_opened_as_utf_8(self):
		"""
		A file opened as text names its encoding: the default is the platform's (cp1252 on Windows), so a schema's `°C` read back as `Â°C` there while a Pi,
		whose default is UTF-8, was fine. A binary open (`b` in the mode) has none.
		"""
		offenders = []
		for folder, dirs, files in os.walk(PYTHON):
			dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".storage", "static", "storage", "waveshare_epd")]
			for file in (f for f in files if f.endswith(".py")):
				full = os.path.join(folder, file)
				with open(full, encoding="utf-8") as f:
					tree = ast.parse(f.read())
				for node in ast.walk(tree):
					if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"):
						continue
					mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
					binary = isinstance(mode, ast.Constant) and "b" in str(mode.value)
					if not binary and not any(k.arg == "encoding" for k in node.keywords):
						offenders.append(f"{os.path.relpath(full, PYTHON)}:{node.lineno}")
		self.assertEqual(offenders, [], "open(..., encoding=\"utf-8\") for a text file")

class TestNames(unittest.TestCase):
	def test_a_name_is_never_a_path(self):
		with tempfile.TemporaryDirectory() as tmp:
			cm = ConfigurationManager(storage_path=tmp)
			cm.ensure_folders()
			dsm = cm.datasource_manager("calendar")
			for bad in ("../x", "..", "a/b", "a\b", "", "/etc/passwd", ".hidden", "x.json"):
				with self.subTest(bad), self.assertRaises(ValueError):
					dsm.file(bad)
			dsm.file("tokens")

class TestFoldersOnDemand(unittest.TestCase):
	"""A plugin's or data source's folder exists because something was written to it (#142)."""
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.cm = ConfigurationManager(storage_path=os.path.join(self.tmp.name, "storage"))
		self.cm.hard_reset()

	def folders(self, kind: str) -> list[str]:
		root = os.path.join(self.cm.STORAGE_PATH, kind)
		return sorted(os.listdir(root))

	def test_a_seeded_storage_has_folders_only_for_what_has_settings(self):
		with_settings = sorted(d["info"]["id"] for d in self.cm.enum_datasources() if (d["info"].get("settings") or {}).get("default") is not None)
		self.assertEqual(self.folders("datasources"), with_settings)
		with_plugin_settings = sorted(d["info"]["id"] for d in self.cm.enum_plugins() if (d["info"].get("settings") or {}).get("default") is not None)
		self.assertEqual(self.folders("plugins"), with_plugin_settings)
		self.assertEqual(with_plugin_settings, ["slide-show"], "only the slide show has settings today")
		self.assertTrue(len(with_settings) < len(self.cm.enum_datasources()))

	def test_a_lookup_and_a_read_create_nothing(self):
		dsm = self.cm.datasource_manager("clock")
		self.assertEqual(self.cm.plugin_manager("overlay").open().get(), (None, None))
		self.assertEqual(dsm.open().get(), (None, None))
		self.assertEqual(dsm.file("tokens").get(), (None, None))
		self.assertNotIn("clock", self.folders("datasources"))
		self.assertNotIn("overlay", self.folders("plugins"))

	def test_a_write_makes_its_folder(self):
		dsm = self.cm.datasource_manager("clock")
		committed, _ = dsm.file("tokens").save(None, { "a": 1 })
		self.assertTrue(committed)
		self.assertIn("clock", self.folders("datasources"))
		self.assertEqual(dsm.file("tokens").get()[1], { "a": 1 })
		pcm = self.cm.plugin_manager("overlay")
		pcm.save_state({ "n": 2 })
		self.assertEqual(pcm.open_state().get()[1], { "n": 2 })
		self.assertIn("overlay", self.folders("plugins"))

	def test_deleting_state_that_was_never_written_is_quiet(self):
		self.cm.plugin_manager("overlay").delete_state()
		self.assertNotIn("overlay", self.folders("plugins"))
