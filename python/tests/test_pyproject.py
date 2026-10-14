import ast
import os
import re
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# what only a Raspberry Pi (Linux) has: the panel's driver and what it needs, and the systemd journal
DEVICE_ONLY = ("inky", "cysystemd", "spidev", "smbus2", "smbus", "gpiod", "gpiodevice", "rpi.gpio", "rpi-lgpio", "lgpio", "gpiozero")

def name_of(requirement: str) -> str:
	return re.split(r"[\s\[<>=!~;]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")

def toplevel_imports(path: str) -> set[str]:
	"""The modules a file imports at its top level (not inside a function or a `try`: those are the dynamic ones)."""
	with open(path, encoding="utf-8") as f:
		tree = ast.parse(f.read())
	found = set()
	for node in tree.body:
		if isinstance(node, ast.Import):
			found |= { a.name.split(".")[0].lower() for a in node.names }
		elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
			found.add(node.module.split(".")[0].lower())
	return found

class TestPyproject(unittest.TestCase):
	def setUp(self):
		with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
			self.project = tomllib.load(f)

	def test_a_package_only_the_device_has_is_never_a_dependency_of_everyone(self):
		names = { name_of(r) for r in self.project["project"]["dependencies"] } | { name_of(r) for r in self.project["dependency-groups"].get("dev", []) }
		self.assertEqual(names & set(DEVICE_ONLY), set(), "install it in the `device` group, with a Linux marker")

	def test_the_device_group_is_linux_only_and_not_installed_by_default(self):
		group = self.project["dependency-groups"]["device"]
		self.assertTrue(group)
		for requirement in group:
			self.assertRegex(requirement, r";\s*sys_platform\s*==\s*'linux'", f"{requirement}: no Linux marker, so a Windows install would try it")
		self.assertNotIn("device", (self.project.get("tool", {}).get("uv", {}) or {}).get("default-groups", []))

	def test_nothing_imports_a_device_package_at_the_top_of_a_module(self):
		"""The driver is imported when the display is made (`import` inside the function that needs it), so a machine without it still starts."""
		offenders = []
		for folder, _, names in os.walk(os.path.join(ROOT, "python")):
			if os.sep + "tests" in folder:
				continue
			for name in names:
				if name.endswith(".py"):
					path = os.path.join(folder, name)
					offenders += [f"{os.path.relpath(path, ROOT)}: {m}" for m in sorted(toplevel_imports(path) & set(DEVICE_ONLY))]
		self.assertEqual(offenders, [])

if __name__ == "__main__":
	unittest.main()
