"""
Build a fresh storage folder for the browser (e2e) tests.

    python -m scripts.e2e_storage <folder>

The folder is recreated from the factory defaults (the same reset the application does on its first start),
then the synthetic fixtures in app/e2e/fixtures/storage (schedules, a fake API key) are copied over it.
Nothing here is real data: the real test storage stays out of the repository.
"""
import json
import os
import shutil
import sys

from python.model.configuration_manager import ConfigurationManager

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FIXTURES = os.path.join(ROOT, "app", "e2e", "fixtures", "storage")
# the playlist fixture plays the repository's own test images, so no track fails (a failing track is retried without delay)
PLACEHOLDERS = { "__E2E_IMAGES__": os.path.join(ROOT, "python", "tests", "images") }

# the only place a storage may be built: the folder is deleted first, so it must not be able to name anything else
SCRATCH = os.path.join(ROOT, ".e2e-storage")

def _add_visibility_fields(target: str) -> None:
	"""Two synthetic properties on the display schema, so the browser tests can see `visibleIf` work on a real settings page."""
	schema_file = os.path.join(target, "schemas", "display.json")
	with open(schema_file, "r", encoding="utf-8") as f:
		schema = json.load(f)
	schema["schema"]["properties"] += [
		{ "name": "e2eAdvanced", "type": "boolean", "title": "E2E Advanced", "required": False },
		{ "name": "e2eDetail", "type": "string", "title": "E2E Detail", "required": True, "visibleIf": { "field": "e2eAdvanced", "const": True } },
	]
	with open(schema_file, "w", encoding="utf-8", newline="\n") as f:
		json.dump(schema, f, indent=2)

def build(target: str) -> str:
	target = os.path.realpath(target)
	if not target.startswith(os.path.realpath(SCRATCH) + os.sep):
		sys.exit(f"Refusing to build a storage outside {SCRATCH}: {target}")
	shutil.rmtree(target, ignore_errors=True)
	os.makedirs(target)
	ConfigurationManager(storage_path=target).hard_reset()
	shutil.copytree(FIXTURES, target, dirs_exist_ok=True)
	for folder, _, names in os.walk(target):
		for name in names:
			if not name.endswith(".json"):
				continue
			path = os.path.join(folder, name)
			with open(path, "r", encoding="utf-8") as f:
				text = f.read()
			for placeholder, value in PLACEHOLDERS.items():
				# json.dumps gives the escaping a JSON string needs (backslashes on Windows)
				text = text.replace(placeholder, json.dumps(value)[1:-1])
			with open(path, "w", encoding="utf-8", newline="\n") as f:
				f.write(text)
	_add_visibility_fields(target)
	return target

if __name__ == "__main__":
	if len(sys.argv) != 2:
		sys.exit(__doc__)
	print(build(sys.argv[1]))
