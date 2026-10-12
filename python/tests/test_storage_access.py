import ast
import os
import tempfile
import unittest

from ..model.configuration_manager import ConfigurationManager

PYTHON = os.path.join(os.path.dirname(__file__), "..")
# the only modules that touch the storage's files; everything else goes through the ConfigurationManager and its sub-managers
STORAGE = { "model/storage_files.py", "model/configuration_manager.py", "model/schedule_manager.py" }
# file calls that are not about the storage: render scratch files (temp), the system's zone file, the logging configuration, the mock display's output (system temp)
OTHER = { "utils/image_utils.py", "model/time_of_day.py", "eink-billboard.py", "display/mock_display.py" }
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
			dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".storage", "static", "storage")]
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
