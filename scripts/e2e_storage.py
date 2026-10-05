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

def build(target: str) -> str:
	target = os.path.abspath(target)
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
	# the factory default is a Windows path (c:\Temp\mock), which on Linux becomes a folder with that literal name in the working directory
	display_file = os.path.join(target, "settings", "display-settings.json")
	with open(display_file, "r", encoding="utf-8") as f:
		display = json.load(f)
	display["mock.outputFolder"] = os.path.join(target, "mock-output")
	with open(display_file, "w", encoding="utf-8", newline="\n") as f:
		json.dump(display, f, indent=2)
	return target

if __name__ == "__main__":
	if len(sys.argv) != 2:
		sys.exit(__doc__)
	print(build(sys.argv[1]))
