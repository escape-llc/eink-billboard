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
from ..web.documents import SECRET_MASK
from ..web.sessions import SessionStore

def _error_shape(test: unittest.TestCase, resp, status: int):
	test.assertEqual(resp.status_code, status, resp.text)
	body = resp.json()
	test.assertIs(body["success"], False)
	test.assertIsInstance(body["message"], str)
	return body

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
