import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from .utils import storage_path
from ..model.configuration_manager import ConfigurationManager, _internal_save
from ..model.service_container import ServiceContainer
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..web.app import WebSettings, create_app
from ..web.documents import SECRET_MASK, validate_properties
from ..web.sessions import SessionStore
from ..web.visibility import evaluate, find_problems, hidden_names, null_hidden

def _error_shape(test: unittest.TestCase, resp, status: int):
	test.assertEqual(resp.status_code, status, resp.text)
	body = resp.json()
	test.assertIs(body["success"], False)
	test.assertIsInstance(body["message"], str)
	return body

def decode_case_value(value):
	"""JSON files cannot hold NaN or Infinity: form_rules.json writes them as `{ "$number": "NaN" }` (FormValidation.test.ts decodes the same marker)."""
	if isinstance(value, dict) and "$number" in value:
		return float(value["$number"])
	return value

class WebApiTestBase(unittest.TestCase):
	"""Each test works on a private copy of the test storage, so writes never touch the original."""
	token: str|None = None

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.storage = os.path.join(self.tmp.name, ".storage")
		shutil.copytree(storage_path(), self.storage)
		self.cm = ConfigurationManager(storage_path=self.storage)
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(TimeOfDay, SystemTimeOfDay())
		self.app = create_app(WebSettings(api_token=self.token), root, self._routers())
		self.client = TestClient(self.app, raise_server_exceptions=False)

	def tearDown(self):
		self.client.close()
		self.tmp.cleanup()

	def write_datasource_settings(self, ident: str, doc: dict) -> str:
		"""Create the stored settings of a datasource; the CI test storage has no datasources/plugins folders."""
		folder = os.path.join(self.storage, "datasources", ident)
		os.makedirs(folder, exist_ok=True)
		settings_file = os.path.join(folder, "settings.json")
		with open(settings_file, "w") as f:
			json.dump(doc, f)
		cob = self.cm.find(settings_file)
		if cob is not None:
			cob.evict()
		return settings_file

	def _routers(self):
		routers = {}
		routers.update(self.cm.load_routers(self.cm.enum_datasources()))
		return routers

class TestSettings(WebApiTestBase):
	def test_get_device_settings_has_id_and_rev(self):
		for name in ("system", "display", "theme"):
			resp = self.client.get(f"/api/settings/{name}")
			self.assertEqual(resp.status_code, 200, resp.text)
			doc = resp.json()
			self.assertEqual(doc["_id"], f"{name}-settings")
			self.assertTrue(doc["_rev"])

	def test_put_round_trip_changes_rev(self):
		doc = self.client.get("/api/settings/system").json()
		doc["locale"] = "fr-FR"
		resp = self.client.put("/api/settings/system", json=doc)
		self.assertEqual(resp.status_code, 200, resp.text)
		saved = resp.json()
		self.assertTrue(saved["success"])
		self.assertNotEqual(saved["rev"], doc["_rev"])
		again = self.client.get("/api/settings/system").json()
		self.assertEqual(again["locale"], "fr-FR")
		self.assertEqual(again["_rev"], saved["rev"])

	def test_put_without_id_is_accepted(self):
		doc = self.client.get("/api/settings/system").json()
		doc.pop("_id")
		self.assertEqual(self.client.put("/api/settings/system", json=doc).status_code, 200)

	def test_put_stale_rev_is_conflict_with_current_rev(self):
		doc = self.client.get("/api/settings/system").json()
		first = dict(doc, locale="de-DE")
		self.assertEqual(self.client.put("/api/settings/system", json=first).status_code, 200)
		second = dict(doc, locale="es-ES")  # still carries the old _rev
		body = _error_shape(self, self.client.put("/api/settings/system", json=second), 409)
		current = self.client.get("/api/settings/system").json()
		self.assertEqual(body["rev"], current["_rev"])
		self.assertEqual(current["locale"], "de-DE")

	def test_put_id_mismatch(self):
		doc = self.client.get("/api/settings/system").json()
		doc["_id"] = "display-settings"
		_error_shape(self, self.client.put("/api/settings/system", json=doc), 400)

	def test_put_rejects_bad_bodies(self):
		_error_shape(self, self.client.put("/api/settings/system", json=["not", "a", "dict"]), 422)
		_error_shape(self, self.client.put("/api/settings/system", content=b"{nope", headers={"content-type": "application/json"}), 422)
		doc = self.client.get("/api/settings/system").json()
		doc["timezoneName"] = 42
		body = _error_shape(self, self.client.put("/api/settings/system", json=doc), 422)
		self.assertEqual(body["errors"][0]["path"], ["timezoneName"])

	def test_unknown_settings_name_is_404(self):
		for name in ("nope", "..", "%2e%2e", "..%2f..%2fsecrets", "system-settings"):
			_error_shape(self, self.client.get(f"/api/settings/{name}"), 404)
			_error_shape(self, self.client.get(f"/api/schemas/{name}"), 404)

	def test_schemas(self):
		for name in ("system", "display", "theme"):
			resp = self.client.get(f"/api/schemas/{name}")
			self.assertEqual(resp.status_code, 200)
			self.assertIn("schema", resp.json())

class TestValidateProperties(unittest.TestCase):
	def test_rules_shared_with_the_form(self):
		path = os.path.join(os.path.dirname(__file__), "form_rules.json")
		with open(path, "r", encoding="utf-8") as f:
			cases = json.load(f)["cases"]
		self.assertGreater(len(cases), 10)
		for case in cases:
			with self.subTest(case["name"]):
				errors = validate_properties({ "f": decode_case_value(case["value"]) }, [case["field"]])
				self.assertEqual(errors[0]["message"] if errors else None, case["error"])
				if errors:
					self.assertEqual(errors[0]["path"], ["f"])

	def test_missing_required_is_reported_and_headers_are_skipped(self):
		props = [{ "name": "a", "type": "string", "required": True }, { "name": "h", "type": "header", "label": "H" }]
		self.assertEqual(validate_properties({}, props), [{ "path": ["a"], "message": "Required" }])

	def test_items_lookup_limits_the_values(self):
		props = [{ "name": "tf", "type": "string", "lookup": "fmt", "required": True }]
		lookups = { "fmt": { "items": [{ "name": "24h", "value": "24h" }, { "name": "12h", "value": "12h" }] } }
		self.assertEqual(validate_properties({ "tf": "12h" }, props, lookups), [])
		self.assertEqual(validate_properties({ "tf": "9h" }, props, lookups)[0]["message"], "Not one of the allowed values")
		# a URL lookup cannot be checked here
		self.assertEqual(validate_properties({ "tf": "anything" }, props, { "fmt": { "url": "/x" } }), [])

class TestVisibility(unittest.TestCase):
	def test_rules_shared_with_the_form(self):
		path = os.path.join(os.path.dirname(__file__), "form_visibility.json")
		with open(path, "r", encoding="utf-8") as f:
			cases = json.load(f)["cases"]
		self.assertGreater(len(cases), 10)
		for case in cases:
			with self.subTest(case["name"]):
				self.assertEqual(evaluate(case["predicate"], case["values"]), case["visible"])

	PROPS = [
		{ "name": "randomizeDate", "type": "boolean" },
		{ "name": "customDate", "type": "date", "required": True, "visibleIf": { "field": "randomizeDate", "eq": False } },
	]

	def test_hidden_properties_are_not_validated_and_are_stored_as_null(self):
		doc = { "randomizeDate": True, "customDate": "2026-01-01" }
		self.assertEqual(hidden_names(self.PROPS, doc), { "customDate" })
		self.assertEqual(null_hidden(doc, self.PROPS), { "randomizeDate": True, "customDate": None })
		self.assertEqual(validate_properties(null_hidden(doc, self.PROPS), self.PROPS), [])
		# visible again: required applies
		shown = null_hidden({ "randomizeDate": False }, self.PROPS)
		self.assertEqual(validate_properties(shown, self.PROPS), [{ "path": ["customDate"], "message": "Required" }])

	def test_find_problems(self):
		self.assertEqual(find_problems(self.PROPS), [])
		self.assertIn("unknown field 'nope'", find_problems([{ "name": "a", "visibleIf": { "field": "nope", "eq": 1 } }])[0])
		self.assertIn("needs eq, ne, in or set", find_problems([{ "name": "a", "visibleIf": { "field": "a" } }])[0])
		cyc = [{ "name": "a", "visibleIf": { "field": "b", "set": True } }, { "name": "b", "visibleIf": { "field": "a", "set": True } }]
		self.assertTrue(any("cycle" in m for m in find_problems(cyc)))

class TestDescriptors(unittest.TestCase):
	"""Every descriptor in the repository (not the test storage) must have well-formed `visibleIf` rules."""
	@staticmethod
	def _property_lists(node, where):
		if isinstance(node, dict):
			props = node.get("properties")
			if isinstance(props, list) and all(isinstance(p, dict) and "name" in p for p in props):
				yield where, props
			for k, v in node.items():
				yield from TestDescriptors._property_lists(v, f"{where}/{k}")
		elif isinstance(node, list):
			for i, v in enumerate(node):
				yield from TestDescriptors._property_lists(v, f"{where}[{i}]")

	def test_visible_if_rules_are_well_formed(self):
		import glob
		root = os.path.dirname(os.path.dirname(__file__))
		files = glob.glob(os.path.join(root, "storage", "schemas", "*.json")) \
			+ glob.glob(os.path.join(root, "plugins", "*", "*-info.json")) \
			+ glob.glob(os.path.join(root, "datasources", "*", "*-info.json"))
		self.assertGreater(len(files), 5)
		checked = 0
		for path in files:
			with open(path, "r", encoding="utf-8") as f:
				doc = json.load(f)
			for where, props in self._property_lists(doc, os.path.relpath(path, root)):
				checked += 1
				with self.subTest(where):
					self.assertEqual(find_problems(props), [])
		self.assertGreater(checked, 5)

class TestSettingsValidation(WebApiTestBase):
	def test_put_out_of_range_and_unknown_choice_are_422_with_the_field_path(self):
		doc = self.client.get("/api/settings/theme").json()
		doc["hue"] = 400
		body = _error_shape(self, self.client.put("/api/settings/theme", json=doc), 422)
		self.assertEqual(body["errors"][0], { "path": ["hue"], "message": "Maximum 360" })
		doc = self.client.get("/api/settings/system").json()
		doc["timeFormat"] = "9h"
		body = _error_shape(self, self.client.put("/api/settings/system", json=doc), 422)
		self.assertEqual(body["errors"][0]["path"], ["timeFormat"])

class TestNonFiniteNumbers(WebApiTestBase):
	"""Starlette's JSON parser accepts NaN, Infinity and 1e999; a stored NaN made every later GET a 500 (JSONResponse refuses it)."""
	RAW = '{"theme": "complementary", "hue": %s, "saturation": 80, "lightness": 50}'

	def _put_raw(self, text: str):
		return self.client.put("/api/settings/theme", content=text.encode(), headers={ "content-type": "application/json" })

	def test_declared_number_rejects_non_finite(self):
		before = self.client.get("/api/settings/theme").json()
		for literal in ("NaN", "Infinity", "-Infinity", "1e999"):
			with self.subTest(literal):
				body = _error_shape(self, self._put_raw(self.RAW % literal), 422)
				self.assertEqual(body["errors"][0], { "path": ["hue"], "message": "Must be a finite number" })
		# nothing was stored, so the settings are still readable
		after = self.client.get("/api/settings/theme")
		self.assertEqual(after.status_code, 200, after.text)
		self.assertEqual(after.json()["_rev"], before["_rev"])

	def test_unknown_and_nested_keys_reject_non_finite(self):
		doc = self.client.get("/api/settings/theme").json()
		text = json.dumps(doc)[:-1] + ', "extra": NaN, "deep": {"list": [1, Infinity]}}'
		body = _error_shape(self, self._put_raw(text), 422)
		paths = [e["path"] for e in body["errors"]]
		self.assertIn(["extra"], paths)
		self.assertIn(["deep", "list", "1"], paths)
		self.assertTrue(all(e["message"] == "Must be a finite number" for e in body["errors"]))
		self.assertEqual(self.client.get("/api/settings/theme").status_code, 200)

class TestPluginsAndDatasources(WebApiTestBase):
	def test_lists(self):
		plugins = self.client.get("/api/plugins/list").json()
		datasources = self.client.get("/api/datasources/list").json()
		self.assertIn("slide-show", {p["id"] for p in plugins})
		self.assertIn("openai-image", {d["id"] for d in datasources})

	def test_unknown_ids_are_404_and_create_nothing(self):
		before = sorted(os.listdir(self.storage))
		evil = ("nope", "..", "%2e%2e", "..%2f..%2fevil", "..%5c..%5cevil", "x%00y")
		for ident in evil:
			for kind in ("plugins", "datasources"):
				_error_shape(self, self.client.get(f"/api/{kind}/{ident}/settings"), 404)
				_error_shape(self, self.client.put(f"/api/{kind}/{ident}/settings", json={"a": 1}), 404)
		self.assertEqual(sorted(os.listdir(self.storage)), before)
		self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil")))

	def test_unknown_ids_are_not_echoed_back(self):
		probe = "zz-probe-zz"
		for url in (f"/api/plugins/{probe}/settings", f"/api/datasources/{probe}/settings", f"/api/settings/{probe}", f"/api/schemas/{probe}"):
			resp = self.client.get(url)
			self.assertEqual(resp.status_code, 404, url)
			self.assertNotIn(probe, resp.text, url)

	def test_datasource_settings_round_trip(self):
		self.write_datasource_settings("wpotd", {"shrinkToFit": True})
		resp = self.client.get("/api/datasources/wpotd/settings")
		self.assertEqual(resp.status_code, 200, resp.text)
		doc = resp.json()
		self.assertEqual(doc["_id"], "datasource-wpotd-settings")
		doc["shrinkToFit"] = False
		self.assertEqual(self.client.put("/api/datasources/wpotd/settings", json=doc).status_code, 200)
		self.assertIs(self.client.get("/api/datasources/wpotd/settings").json()["shrinkToFit"], False)

	def test_missing_settings_is_404_and_first_save_needs_no_rev(self):
		# a plugin with no stored settings.json yet
		for ident in ("clock", "wpotd"):
			settings_file = os.path.join(self.storage, "datasources", ident, "settings.json")
			if os.path.exists(settings_file):
				os.remove(settings_file)
			cob = self.cm.find(settings_file)
			if cob is not None:
				cob.evict()
			resp = self.client.get(f"/api/datasources/{ident}/settings")
			body = _error_shape(self, resp, 404)
			self.assertIsNone(body["rev"])
			resp = self.client.put(f"/api/datasources/{ident}/settings", json={"x": 1})
			self.assertEqual(resp.status_code, 200, resp.text)

	def test_secrets_are_masked_and_kept(self):
		url = "/api/datasources/openai-image/settings"
		settings_file = self.write_datasource_settings("openai-image", {"apiKey": "sk-test-1"})

		doc = self.client.get(url).json()
		self.assertEqual(doc["apiKey"], SECRET_MASK)
		self.assertNotIn("sk-test-1", json.dumps(doc))

		# saving the masked value back keeps the stored secret
		self.assertEqual(self.client.put(url, json=doc).status_code, 200)
		with open(settings_file) as f:
			self.assertEqual(json.load(f)["apiKey"], "sk-test-1")

		# omitting it keeps it too
		doc = self.client.get(url).json()
		doc.pop("apiKey")
		self.assertEqual(self.client.put(url, json=doc).status_code, 200)
		with open(settings_file) as f:
			self.assertEqual(json.load(f)["apiKey"], "sk-test-1")

		# a new value replaces it
		doc = self.client.get(url).json()
		doc["apiKey"] = "sk-test-2"
		self.assertEqual(self.client.put(url, json=doc).status_code, 200)
		with open(settings_file) as f:
			self.assertEqual(json.load(f)["apiKey"], "sk-test-2")
		self.assertEqual(self.client.get(url).json()["apiKey"], SECRET_MASK)

class TestSecretMaskOnFirstSave(WebApiTestBase):
	URL = "/api/datasources/openai-image/settings"

	def _no_stored_settings(self):
		settings_file = self.write_datasource_settings("openai-image", {})
		os.remove(settings_file)
		cob = self.cm.find(settings_file)
		if cob is not None:
			cob.evict()
		return settings_file

	def test_the_literal_mask_is_not_stored_as_a_secret(self):
		settings_file = self._no_stored_settings()
		body = _error_shape(self, self.client.put(self.URL, json={ "apiKey": SECRET_MASK }), 422)
		self.assertEqual(body["errors"][0], { "path": ["apiKey"], "message": "Enter the key" })
		self.assertFalse(os.path.exists(settings_file))

	def test_the_literal_mask_is_refused_when_the_stored_settings_have_no_key(self):
		self.write_datasource_settings("openai-image", { "other": 1 })
		doc = self.client.get(self.URL).json()
		doc["apiKey"] = SECRET_MASK
		_error_shape(self, self.client.put(self.URL, json=doc), 422)

	def test_a_first_save_with_a_real_key_is_stored(self):
		self._no_stored_settings()
		self.assertEqual(self.client.put(self.URL, json={ "apiKey": "sk-new" }).status_code, 200)

class TestSchemaFile(WebApiTestBase):
	def test_a_missing_schema_file_is_the_uniform_404(self):
		os.remove(os.path.join(self.storage, "schemas", "theme.json"))
		body = _error_shape(self, self.client.get("/api/schemas/theme"), 404)
		self.assertIn("id", body)

class TestLookups(WebApiTestBase):
	def test_lookups(self):
		tz = self.client.get("/api/lookups/timezone").json()
		self.assertIn("America/New_York", {x["value"] for x in tz})
		self.assertEqual({x["value"] for x in self.client.get("/api/lookups/locale").json()}, {"en-US", "es-ES", "fr-FR", "de-DE"})

	def test_plugin_contributed_router(self):
		resp = self.client.get("/api/datasource/newspaper/lookups/newspaperSlug")
		self.assertEqual(resp.status_code, 200)
		self.assertTrue(all({"name", "value"} <= x.keys() for x in resp.json()))

class TestSchedule(WebApiTestBase):
	def test_lists(self):
		pl = self.client.get("/api/schedule/playlist/list").json()
		self.assertTrue(pl["success"])
		self.assertGreater(len(pl["playlists"]), 0)
		self.assertTrue(all("_rev" in p for p in pl["playlists"]))
		tl = self.client.get("/api/schedule/timer/list").json()
		self.assertTrue(tl["success"])
		self.assertGreater(len(tl["timed"]), 0)

	def test_lists_are_empty_not_errors_without_schedules(self):
		for name in os.listdir(os.path.join(self.storage, "schedules")):
			os.remove(os.path.join(self.storage, "schedules", name))
		self.assertEqual(self.client.get("/api/schedule/playlist/list").json(), {"success": True, "playlists": []})
		self.assertEqual(self.client.get("/api/schedule/timer/list").json(), {"success": True, "timed": []})
		render = self.client.get("/api/schedule/tasks/render").json()
		self.assertTrue(render["success"])
		self.assertEqual(render["render"], [])

	def test_render(self):
		resp = self.client.get("/api/schedule/tasks/render", params={"start": "2026-01-05", "days": 2})
		self.assertEqual(resp.status_code, 200, resp.text)
		doc = resp.json()
		self.assertEqual(doc["days"], 2)
		self.assertTrue(doc["start_ts"].startswith("2026-01-05T00:00:00"))
		self.assertGreater(len(doc["render"]), 0)
		self.assertTrue({"schedule", "id", "scheduled_time"} <= doc["render"][0].keys())

	def test_render_validates_parameters(self):
		for params in ({"days": 0}, {"days": 100000}, {"days": "x"}, {"start": "not-a-date"}):
			_error_shape(self, self.client.get("/api/schedule/tasks/render", params=params), 422)

class TestScheduleRender(WebApiTestBase):
	"""The render endpoint over schedules the test writes itself (the CI storage has no other timer tasks to rely on)."""
	def _item(self, ident: str, trigger, enabled: bool = True) -> dict:
		return { "id": ident, "enabled": enabled, "title": f"Title {ident}", "task": { "plugin_name": "p", "content": {} }, "trigger": trigger }

	def _write_tasks(self, items: list[dict]) -> None:
		folder = os.path.join(self.storage, "schedules")
		for name in os.listdir(folder):
			os.remove(os.path.join(folder, name))
		with open(os.path.join(folder, "tasks.json"), "w", encoding="utf-8") as f:
			json.dump({ "_schema": "urn:inky:storage:schedule:tasks:1", "id": "rt", "name": "Render", "items": items }, f)

	def _set_timezone(self, name: str) -> None:
		doc = self.client.get("/api/settings/system").json()
		doc["timezoneName"] = name
		resp = self.client.put("/api/settings/system", json=doc)
		self.assertEqual(resp.status_code, 200, resp.text)

	def _at(self, hour: int, minute: int, days=None) -> dict:
		return { "on_startup": False, "day": { "type": "dayofweek", "days": days if days is not None else [0,1,2,3,4,5,6] }, "time": { "type": "specific", "hour": hour, "minute": minute } }

	def test_disabled_items_are_not_rendered(self):
		self._write_tasks([self._item("on", self._at(9, 0)), self._item("off", self._at(10, 0), enabled=False)])
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2026-01-05", "days": 2 }).json()
		self.assertEqual({r["id"] for r in doc["render"]}, {"on"})
		self.assertNotIn("off", [x["id"] for x in doc["not_render"]])

	def test_the_response_names_the_zone_the_times_are_in(self):
		self._write_tasks([self._item("a", self._at(9, 0))])
		self._set_timezone("Asia/Kolkata")
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2026-01-05", "days": 1 }).json()
		self.assertEqual(doc["timezone"], "Asia/Kolkata")
		self.assertTrue(doc["start_ts"].endswith("+05:30"))
		self.assertTrue(doc["render"][0]["scheduled_time"].endswith("+05:30"))

	def test_weekday_numbering_matches_the_ui(self):
		# 2026-01-04 is a Sunday: day 0
		self._write_tasks([self._item("sun", self._at(9, 0, [0])), self._item("mon", self._at(9, 0, [1]))])
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2026-01-04", "days": 2 }).json()
		got = {(r["id"], r["scheduled_time"][:10]) for r in doc["render"]}
		self.assertEqual(got, {("sun", "2026-01-04"), ("mon", "2026-01-05")})

	def test_one_bad_trigger_is_reported_and_the_rest_render(self):
		bad_hours = { "on_startup": False, "day": { "type": "dayofweek", "days": [0,1,2,3,4,5,6] }, "time": { "type": "hourofday", "hours": [25], "minutes": [0] } }
		bad_minutes = { "on_startup": False, "day": { "type": "dayofweek", "days": [0,1,2,3,4,5,6] }, "time": { "type": "hourofday", "hours": [9], "minutes": [60] } }
		bad_days = { "on_startup": False, "day": { "type": "dayofweek", "days": "monday" }, "time": { "type": "specific", "hour": 1, "minute": 0 } }
		no_day = { "on_startup": False, "time": { "type": "specific", "hour": 1, "minute": 0 } }
		self._write_tasks([
			self._item("good", self._at(9, 0)), self._item("h", bad_hours), self._item("m", bad_minutes),
			self._item("d", bad_days), self._item("nd", no_day), self._item("junk", "nonsense")  # type: ignore
		])
		with self.assertLogs("python.web.routers.schedule", level="WARNING"):
			resp = self.client.get("/api/schedule/tasks/render", params={ "start": "2026-01-05", "days": 1 })
		self.assertEqual(resp.status_code, 200, resp.text)
		doc = resp.json()
		self.assertEqual({r["id"] for r in doc["render"]}, {"good"})
		self.assertEqual({x["id"] for x in doc["invalid"]}, {"h", "m", "d", "nd", "junk"})
		for x in doc["invalid"]:
			self.assertTrue(x["message"])
			self.assertEqual(x["schedule"], "rt")

	def test_dst_gap_time_is_not_printed_with_a_bogus_offset(self):
		self._set_timezone("America/New_York")
		self._write_tasks([self._item("gap", self._at(2, 30))])
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2024-03-10", "days": 2 }).json()
		times = [r["scheduled_time"] for r in doc["render"]]
		self.assertEqual(times, ["2024-03-10T03:30:00-04:00", "2024-03-11T02:30:00-04:00"])
		self.assertEqual(doc["start_ts"], "2024-03-10T00:00:00-05:00")
		self.assertEqual(doc["end_ts"], "2024-03-12T00:00:00-04:00")

	def test_start_with_an_offset_is_converted_to_the_system_zone(self):
		self._set_timezone("America/New_York")
		self._write_tasks([self._item("a", self._at(9, 0))])
		# 01:00 UTC on the 11th is 21:00 on the 10th in New York
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2024-03-11T01:00:00+00:00", "days": 1 }).json()
		self.assertEqual(doc["start_ts"], "2024-03-10T00:00:00-05:00")
		self.assertTrue(doc["render"][0]["scheduled_time"].startswith("2024-03-10T09:00:00"))

	def test_out_of_range_start_is_422_not_500(self):
		self._write_tasks([self._item("a", self._at(9, 0))])
		for start in ("9999-12-31", "9999-12-31T23:59:59+00:00", "0001-01-01", "0001-01-01T00:00:00-12:00"):
			resp = self.client.get("/api/schedule/tasks/render", params={ "start": start, "days": 62 })
			_error_shape(self, resp, 422)

class TestErrorsAndAuth(WebApiTestBase):
	def test_unknown_api_path_is_json_404(self):
		_error_shape(self, self.client.get("/api/nope"), 404)

	def test_unhandled_error_hides_details(self):
		with mock.patch.object(ConfigurationManager, "settings_manager", side_effect=RuntimeError("secret path /etc/x")):
			body = _error_shape(self, self.client.get("/api/settings/system"), 500)
		self.assertNotIn("secret path", json.dumps(body))

	def test_not_ready_without_container(self):
		self.app.state.root_container = None
		_error_shape(self, self.client.get("/api/settings/system"), 503)

class TestToken(WebApiTestBase):
	token = "t0ken"

	def test_requires_bearer_token(self):
		_error_shape(self, self.client.get("/api/settings/system"), 401)
		_error_shape(self, self.client.get("/api/settings/system", headers={"Authorization": "Bearer wrong"}), 401)
		_error_shape(self, self.client.get("/api/settings/system", headers={"Authorization": "Basic t0ken"}), 401)
		_error_shape(self, self.client.put("/api/settings/system", json={}), 401)
		ok = self.client.get("/api/settings/system", headers={"Authorization": "Bearer t0ken"})
		self.assertEqual(ok.status_code, 200)

	def test_docs_need_the_token_too(self):
		for url in ("/api/docs", "/api/openapi.json"):
			with self.subTest(url):
				_error_shape(self, self.client.get(url), 401)
				self.assertEqual(self.client.get(url, headers={ "Authorization": "Bearer t0ken" }).status_code, 200)

	def test_docs_open_with_a_session_cookie(self):
		self.assertEqual(self.client.post("/api/session", headers={ "Authorization": "Bearer t0ken" }).status_code, 200)
		self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)
		self.assertEqual(self.client.get("/api/docs").status_code, 200)

class TestDocsWithoutAToken(WebApiTestBase):
	def test_docs_stay_open(self):
		self.assertEqual(self.client.get("/api/docs").status_code, 200)
		self.assertIn("paths", self.client.get("/api/openapi.json").json())

class TestSessions(WebApiTestBase):
	"""The web app signs in once and the server remembers it; the browser holds only an HttpOnly cookie."""
	token = "t0ken"
	BEARER = {"Authorization": "Bearer t0ken"}

	def sign_in(self):
		resp = self.client.post("/api/session", headers=self.BEARER)
		self.assertEqual(resp.status_code, 200, resp.text)
		return resp

	def test_sign_in_sets_a_cookie_scripts_cannot_read(self):
		cookie = self.sign_in().headers["set-cookie"]
		self.assertTrue(cookie.startswith("eink_session="))
		attributes = [a.strip().lower() for a in cookie.split(";")[1:]]
		self.assertIn("httponly", attributes)
		self.assertIn("samesite=strict", attributes)
		self.assertIn("path=/api", attributes)
		self.assertTrue(any(a.startswith("max-age=") for a in attributes))
		# plain HTTP is normal on a home network: a Secure cookie would never come back
		self.assertNotIn("secure", attributes)

	def test_the_cookie_alone_opens_the_api(self):
		_error_shape(self, self.client.get("/api/settings/system"), 401)
		self.sign_in()
		self.client.headers.pop("Authorization", None)
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		doc = self.client.get("/api/settings/system").json()
		self.assertEqual(self.client.put("/api/settings/system", json=doc).status_code, 200)

	def test_the_cookie_is_marked_secure_over_https(self):
		with TestClient(self.app, base_url="https://testserver") as https:
			cookie = https.post("/api/session", headers=self.BEARER).headers["set-cookie"]
		self.assertIn("secure", [a.strip().lower() for a in cookie.split(";")[1:]])

	def test_a_wrong_or_missing_token_starts_nothing(self):
		for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic t0ken"}):
			resp = self.client.post("/api/session", headers=headers)
			_error_shape(self, resp, 401)
			self.assertNotIn("set-cookie", resp.headers)
		_error_shape(self, self.client.get("/api/settings/system"), 401)

	def test_an_unknown_cookie_is_refused(self):
		self.client.cookies.set("eink_session", "not-a-session", path="/api")
		_error_shape(self, self.client.get("/api/settings/system"), 401)

	def test_signing_out_ends_the_session(self):
		self.sign_in()
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		sid = self.client.cookies.get("eink_session")
		resp = self.client.delete("/api/session")
		self.assertEqual(resp.status_code, 200)
		self.assertIn("max-age=0", resp.headers["set-cookie"].lower())
		# the old ID is dead on the server even if somebody kept it
		self.client.cookies.clear()
		self.client.cookies.set("eink_session", sid, path="/api")
		_error_shape(self, self.client.get("/api/settings/system"), 401)

	def test_a_session_expires(self):
		now = [1000.0]
		self.app.state.sessions = SessionStore(ttl_seconds=60, clock=lambda: now[0])
		self.sign_in()
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		now[0] += 61
		_error_shape(self, self.client.get("/api/settings/system"), 401)

	def test_the_bearer_token_still_works_for_scripts(self):
		self.assertEqual(self.client.get("/api/settings/system", headers=self.BEARER).status_code, 200)

class TestSessionsWithoutAToken(WebApiTestBase):
	def test_nothing_to_sign_in_to(self):
		resp = self.client.post("/api/session")
		self.assertEqual(resp.json(), {"success": True, "required": False})
		self.assertNotIn("set-cookie", resp.headers)

class TestSessionStore(unittest.TestCase):
	def test_ids_are_unique_and_unguessable(self):
		store = SessionStore()
		ids = {store.create() for _ in range(20)}
		self.assertEqual(len(ids), 20)
		self.assertTrue(all(len(i) >= 40 for i in ids))
		self.assertFalse(store.valid(None))
		self.assertFalse(store.valid(""))
		self.assertFalse(store.valid("guess"))

	def test_the_oldest_are_dropped_when_there_are_too_many(self):
		now = [0.0]
		store = SessionStore(max_sessions=3, clock=lambda: now[0])
		first = store.create()
		now[0] += 1
		others = []
		for _ in range(3):
			others.append(store.create())
			now[0] += 1
		self.assertFalse(store.valid(first))
		self.assertTrue(all(store.valid(s) for s in others))

class TestWebApp(unittest.TestCase):
	"""The built web app in Vite's default layout: index.html and public/ files at the root, bundles in assets/."""
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.dist = os.path.join(self.tmp.name, "dist")
		os.makedirs(os.path.join(self.dist, "assets"))
		files = {
			"index.html": "<html>spa</html>",
			"logo.svg": "<svg>logo</svg>",
			os.path.join("assets", "a-1234.js"): "console.log(1)",
		}
		for name, text in files.items():
			with open(os.path.join(self.dist, name), "w") as f:
				f.write(text)
		with open(os.path.join(self.tmp.name, "secret.txt"), "w") as f:
			f.write("not served")
		self.client = TestClient(create_app(WebSettings(app_path=self.dist)))
	def tearDown(self):
		self.client.close()
		self.tmp.cleanup()

	def test_spa_fallback(self):
		for path in ("/", "/settings", "/some/deep/route"):
			resp = self.client.get(path)
			self.assertEqual(resp.status_code, 200)
			self.assertIn("spa", resp.text)

	def test_serves_public_files_from_the_root_and_assets(self):
		logo = self.client.get("/logo.svg")
		self.assertEqual(logo.status_code, 200)
		self.assertEqual(logo.text, "<svg>logo</svg>")
		self.assertEqual(logo.headers["content-type"].split(";")[0], "image/svg+xml")
		asset = self.client.get("/assets/a-1234.js")
		self.assertEqual(asset.text, "console.log(1)")
		self.assertIn("immutable", asset.headers["cache-control"])
		self.assertNotIn("immutable", logo.headers.get("cache-control", ""))

	def test_missing_file_falls_back_to_the_app(self):
		self.assertIn("spa", self.client.get("/assets/missing.js").text)

	def test_api_paths_never_fall_back_to_spa(self):
		resp = self.client.get("/api/whatever")
		self.assertEqual(resp.status_code, 404)
		self.assertEqual(resp.headers["content-type"], "application/json")

	def test_does_not_follow_a_link_out_of_the_bundle(self):
		link = os.path.join(self.dist, "assets", "outside.txt")
		try:
			os.symlink(os.path.join(self.tmp.name, "secret.txt"), link)
		except (OSError, NotImplementedError):
			self.skipTest("symbolic links are not available here")
		self.assertNotEqual(self.client.get("/assets/outside.txt").text, "not served")

	def test_does_not_escape_the_bundle_folder(self):
		for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%00"):
			resp = self.client.get(path)
			self.assertNotEqual(resp.text, "not served", path)

class TestCors(unittest.TestCase):
	def test_the_session_cookie_may_be_used_from_the_configured_origin(self):
		client = TestClient(create_app(WebSettings(cors_origin="http://localhost:5173")))
		resp = client.options("/api/session", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"})
		self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:5173")
		self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

	def test_only_configured_origin_is_allowed(self):
		client = TestClient(create_app(WebSettings(cors_origin="http://localhost:5173")))
		ok = client.options("/api/settings/system", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
		self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://localhost:5173")
		bad = client.options("/api/settings/system", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "PUT"})
		self.assertNotIn("access-control-allow-origin", bad.headers)

class TestAtomicSave(unittest.TestCase):
	def test_replaces_file_and_leaves_no_temp_files(self):
		with tempfile.TemporaryDirectory() as td:
			path = os.path.join(td, "s.json")
			_internal_save(path, {"a": 1})
			_internal_save(path, {"a": 2})
			with open(path) as f:
				self.assertEqual(json.load(f), {"a": 2})
			self.assertEqual(os.listdir(td), ["s.json"])

	def test_failure_propagates_and_keeps_original(self):
		with tempfile.TemporaryDirectory() as td:
			path = os.path.join(td, "s.json")
			_internal_save(path, {"a": 1})
			with mock.patch("os.replace", side_effect=OSError("disk full")):
				with self.assertRaises(OSError):
					_internal_save(path, {"a": 2})
			with open(path) as f:
				self.assertEqual(json.load(f), {"a": 1})
			self.assertEqual(os.listdir(td), ["s.json"])
			with self.assertRaises(TypeError):
				_internal_save(path, {"a": object()})
			with open(path) as f:
				self.assertEqual(json.load(f), {"a": 1})

if __name__ == '__main__':
	unittest.main()
