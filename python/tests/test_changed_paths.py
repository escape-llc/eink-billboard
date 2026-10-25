"""
What a change of a stored file changes in the web API (#549, `python/model/changed_paths.py`): the routes a page asks for again. Every path is the start
of a route the server has, so a renamed route cannot leave a path that matches nothing.
"""
import json
import os
import unittest

from scripts.export_openapi import DOCUMENT
from ..model.changed_paths import EVERYTHING, MAX_PATHS, _unique, changed_paths
from ..model.configuration_manager import ConfigurationManager
from .utils import temp_configuration_manager

def _routes() -> list[list[str]]:
	with open(DOCUMENT, encoding="utf-8") as f:
		return [p.strip("/").split("/") for p in json.load(f)["paths"]]

def _starts_a_route(path: str, routes: list[list[str]]) -> bool:
	"""Whether the path is, segment by segment, the start of a route (a `{parameter}` segment matches any name)."""
	segments = path.strip("/").split("/")
	return any(len(r) >= len(segments) and all(a == b or (b.startswith("{") and b.endswith("}")) for a, b in zip(segments, r[:len(segments)], strict=True)) for r in routes)

class TestChangedPaths(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.routes = _routes()

	def setUp(self):
		self.cm: ConfigurationManager = temp_configuration_manager(self)

	def paths(self, *rel: str) -> list[str]:
		return changed_paths(self.cm, os.path.join(self.cm.STORAGE_PATH, *rel))

	def test_a_device_setting_is_its_route(self):
		self.assertEqual(self.paths("settings", "theme-settings.json"), ["/api/settings/theme"])
		self.assertEqual(self.paths("settings", "display-settings.json"), ["/api/settings/display"])

	def test_the_system_settings_also_change_the_providers_lists_and_the_timeline(self):
		paths = self.paths("settings", "system-settings.json")
		self.assertEqual(paths[0], "/api/settings/system")
		# the calendar pages' and the reminder overlay's calendars are the device's calendar provider's, which a system setting chooses
		self.assertIn("/api/datasources/calendar/lookups/calendar", paths)
		self.assertIn("/api/datasources/reminder-overlay/lookups/calendar", paths)
		self.assertIn("/api/schedule/tasks", paths)

	def test_the_password_is_whether_the_device_asks_for_a_sign_in(self):
		self.assertEqual(self.paths("settings", "access-settings.json"), ["/api/access"])

	def test_any_schedule_file_is_every_schedule_route(self):
		self.assertEqual(self.paths("schedules", "tasks-1234.json"), ["/api/schedule"])
		self.assertEqual(self.paths("schedules", "main.json"), ["/api/schedule"])

	def test_a_schema_is_its_route(self):
		self.assertEqual(self.paths("schemas", "theme.json"), ["/api/schemas/theme"])

	def test_a_plugins_settings_are_its_routes(self):
		self.assertEqual(self.paths("plugins", "slide-show", "settings.json"), ["/api/plugins/slide-show"])

	def test_a_providers_settings_change_the_choices_of_what_it_supplies(self):
		paths = self.paths("datasources", "openweathermap-api", "settings.json")
		self.assertEqual(paths[:2], ["/api/datasources/openweathermap-api", "/api/datasource/openweathermap-api"])
		self.assertIn("/api/lookups/providers/data-weather", paths)

	def test_a_providers_lists_are_read_by_the_lookups_from_it(self):
		paths = self.paths("datasources", "calendar-sources", "settings.json")
		self.assertIn("/api/lookups/providers/data-calendar", paths)
		for lookup in ("/api/datasources/calendar/lookups/calendar", "/api/datasources/calendar/lookups/holidaySet", "/api/datasources/reminder-overlay/lookups/calendar"):
			self.assertIn(lookup, paths)

	def test_a_page_source_changes_only_its_own_routes(self):
		self.assertEqual(self.paths("datasources", "rss", "settings.json"), ["/api/datasources/rss", "/api/datasource/rss"])

	def test_what_the_device_keeps_for_itself_is_no_routes_answer(self):
		for rel in (("datasources", "rss", "cache-abc.json"), ("datasources", "rss", "blob-abc.json"), ("datasources", "calendar-sources", "tokens.json"),
				("plugins", "slide-show", "list-abc.json"), ("state", "refresh.json")):
			self.assertEqual(self.paths(*rel), [], rel)

	def test_a_name_that_is_not_ours_is_nothing(self):
		# a folder of no installed item, a file that is not a settings document, a name that is not a leaf, and anything outside the storage
		self.assertEqual(self.paths("datasources", "not-installed", "settings.json"), [])
		self.assertEqual(self.paths("settings", "notes.txt"), [])
		self.assertEqual(self.paths("settings", ".x-settings.json"), [])
		self.assertEqual(self.paths("schedules", "sub", "a.json"), [])
		self.assertEqual(changed_paths(self.cm, os.path.join(os.path.dirname(self.cm.STORAGE_PATH), "elsewhere.json")), [])

	def test_too_many_paths_is_everything(self):
		self.assertEqual(_unique([f"/api/x/{i}" for i in range(MAX_PATHS)]), [f"/api/x/{i}" for i in range(MAX_PATHS)])
		self.assertEqual(_unique([f"/api/x/{i}" for i in range(MAX_PATHS + 1)]), [EVERYTHING])
		self.assertEqual(_unique(["/api/a", "/api/a"]), ["/api/a"])

	def test_every_path_starts_a_route_of_the_server(self):
		files = [("settings", f"{name}-settings.json") for name in ("system", "display", "theme", "master-prompts", "devices", "access")]
		files += [("schemas", f"{name}.json") for name in ("system", "display", "theme", "master-prompts", "devices")]
		files += [("plugins", str(p["info"]["id"]), "settings.json") for p in self.cm.enum_plugins()]
		files += [("datasources", str(d["info"]["id"]), "settings.json") for d in self.cm.enum_datasources()]
		files.append(("schedules", "x.json"))
		seen = 0
		for rel in files:
			for path in self.paths(*rel):
				seen += 1
				self.assertTrue(_starts_a_route(path, self.routes), f"{path} (from {'/'.join(rel)}) starts no route")
		self.assertGreater(seen, len(files))

if __name__ == "__main__":
	unittest.main()
