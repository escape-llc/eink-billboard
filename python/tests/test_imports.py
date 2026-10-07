import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = ["python/model", "python/task", "python/web", "python/web/routers"]

def _modules() -> list[str]:
	found = []
	for package in PACKAGES:
		for name in sorted(os.listdir(os.path.join(ROOT, package))):
			if name.endswith(".py") and name != "__init__.py":
				found.append(f"{package.replace('/', '.')}.{name[:-3]}")
	return found

class TestImports(unittest.TestCase):
	"""
	Each module must import by itself, in a fresh interpreter. A circular import only fails for the module
	that happens to be imported first, so a test run that imports everything in a lucky order never notices it.
	"""
	def test_every_module_imports_alone(self):
		modules = _modules()
		self.assertGreater(len(modules), 20)
		for module in modules:
			with self.subTest(module):
				done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=ROOT, capture_output=True, text=True, timeout=60)
				self.assertEqual(done.returncode, 0, done.stderr[-800:])

if __name__ == "__main__":
	unittest.main()
