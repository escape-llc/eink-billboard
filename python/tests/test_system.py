"""
The System page's data (#390): the machine's readings, the Raspberry Pi's own when it is one, and the storage by area, plugin and data source. Numbers and our own words only.
"""
import json
import os
import unittest
from unittest.mock import patch

import httpx

from ..web import locate, system_info
from ..web.system_info import pi_info, throttle_flags
from .test_web_api import WebApiTestBase

class TestPi(unittest.TestCase):
	def fake(self, files: dict[str, str]):
		return patch.object(system_info, "_read", lambda path: files.get(path))

	def test_a_machine_that_is_not_a_pi_has_no_pi_readings(self):
		with self.fake({}):
			self.assertIsNone(pi_info())
		with self.fake({ system_info.PI_MODEL: "Some Other Board" }):
			self.assertIsNone(pi_info())

	def test_a_pi_says_its_model_temperature_and_power_state(self):
		files = { system_info.PI_MODEL: "Raspberry Pi 5 Model B Rev 1.0", system_info.PI_TEMPERATURE: "61250", system_info.PI_THROTTLED: "50005" }
		with self.fake(files):
			info = pi_info()
		assert info is not None
		self.assertEqual((info["model"], info["temperature_c"], info["throttled_now"]), ("Raspberry Pi 5 Model B Rev 1.0", 61.2, True))
		self.assertEqual(info["throttled"][:2], ["Under-voltage now", "Throttled now"])
		self.assertIn("Under-voltage since start", info["throttled"])

	def test_a_pi_that_is_fine_has_no_warnings_and_unreadable_values_are_left_out(self):
		with self.fake({ system_info.PI_MODEL: "Raspberry Pi Zero 2 W Rev 1.0", system_info.PI_THROTTLED: "0", system_info.PI_TEMPERATURE: "hot" }):
			info = pi_info()
		assert info is not None
		self.assertEqual((info["throttled"], info["throttled_now"]), ([], False))
		self.assertNotIn("temperature_c", info)
		with self.fake({ system_info.PI_MODEL: "Raspberry Pi 4", system_info.PI_THROTTLED: "zz" }):
			self.assertNotIn("throttled", pi_info() or {})

	def test_the_power_bits_are_in_words(self):
		self.assertEqual(throttle_flags(0), [])
		self.assertEqual(throttle_flags(1 << 3), ["Temperature limit now"])
		self.assertEqual(throttle_flags(1 << 17), ["Frequency capped since start"])

class TestSystemRoute(WebApiTestBase):
	def test_the_machine_and_the_storage_are_reported(self):
		body = self.client.get("/api/system").json()
		self.assertEqual(sorted(body), ["host", "load", "pi", "storage"])
		self.assertTrue(body["host"]["python"])
		self.assertGreater(body["host"]["cpus"], 0)
		self.assertGreater(body["load"]["memory"]["total"], 0)
		self.assertEqual([a["name"] for a in body["storage"]["areas"]], ["settings", "schedules", "plugins", "datasources", "schemas", "state"])
		self.assertGreater(body["storage"]["volume"]["total"], 0)

	def test_the_server_says_which_commit_it_is_and_nothing_else_passes_for_one(self):
		with patch.dict(os.environ, { "EINK_COMMIT": "a1b2c3d" }):
			self.assertEqual(self.client.get("/api/system").json()["host"]["commit"], "a1b2c3d")
		for bad in ("", "../../etc", "a1b2c3d; rm", "x" * 41):
			with patch.dict(os.environ, { "EINK_COMMIT": bad }):
				self.assertEqual(self.client.get("/api/system").json()["host"]["commit"], "unknown", bad)

	def test_nothing_that_names_the_machine_or_a_path_is_sent(self):
		text = self.client.get("/api/system").text
		for private in (self.storage, os.path.basename(self.tmp.name), os.environ.get("COMPUTERNAME", "no-such-name"), os.environ.get("USERNAME", "no-such-user")):
			self.assertNotIn(private, text)

	def test_a_pi_appears_only_on_a_pi(self):
		with patch.object(system_info, "_read", lambda path: "Raspberry Pi 5 Model B" if path == system_info.PI_MODEL else None):
			self.assertEqual(self.client.get("/api/system").json()["pi"]["model"], "Raspberry Pi 5 Model B")
		with patch.object(system_info, "_read", lambda path: None):
			self.assertIsNone(self.client.get("/api/system").json()["pi"])

	def test_the_storage_is_counted_by_plugin_and_data_source_with_what_they_keep(self):
		folder = os.path.join(self.storage, "datasources", "counted-source")
		os.makedirs(folder, exist_ok=True)
		for name, size in (("settings.json", 10), ("blob-aaaa.json", 20), ("blob-aaaa.bin", 1000), ("cache-bbbb.json", 5)):
			with open(os.path.join(folder, name), "wb") as f:
				f.write(b"x" * size)
		found = {d["id"]: d for d in self.client.get("/api/system").json()["storage"]["datasources"]}
		self.assertEqual((found["counted-source"]["files"], found["counted-source"]["bytes"], found["counted-source"]["kept_bytes"]), (4, 1035, 1025))
		self.assertEqual(sorted(found["counted-source"]), ["bytes", "files", "id", "kept_bytes"])

	def test_it_needs_the_token_when_there_is_one(self):
		self.client.close()
		self.token = "secret-token"
		self.setUp()
		self.assertEqual(self.client.get("/api/system").status_code, 401)
		self.assertEqual(self.client.get("/api/system", headers={ "Authorization": "Bearer secret-token" }).status_code, 200)

class TestLocateByIp(WebApiTestBase):
	"""The Location field's 'Locate by IP' button (#426): a rough position, in our words, and nothing saved."""

	def test_the_route_answers_a_position_and_saves_nothing(self):
		before = self.client.get("/api/settings/system").json()
		answer = self.client.post("/api/system/locate").json()
		self.assertTrue(answer["ok"], answer)
		self.assertEqual((answer["latitude"], answer["longitude"]), (42.3314, -83.0457))
		self.assertEqual(self.client.get("/api/settings/system").json(), before)

	def test_an_answer_is_read_in_our_words(self):
		def said(status: int, **kw) -> dict:
			return locate.describe(httpx.Response(status, **kw))
		self.assertIn("too many requests", said(429, json={ "error": True, "reason": "RateLimited" })["message"])
		self.assertEqual(said(500, text="boom")["message"], "The location service answered 500.")
		for bad in ({ "error": True, "reason": "Reserved IP Address" }, { "latitude": "x", "longitude": 1 }, { "latitude": 91, "longitude": 0 }, { "latitude": 0, "longitude": -181 }, { "latitude": True, "longitude": 0 }, [1, 2]):
			with self.subTest(bad):
				answer = said(200, json=bad)
				self.assertFalse(answer["ok"])
				self.assertNotIn("Reserved", answer["message"], "the service's own text is never passed on")
		self.assertFalse(said(200, text="not json")["ok"])

	def test_a_service_that_cannot_be_reached_is_said_so(self):
		def refuse(request: httpx.Request) -> httpx.Response:
			raise httpx.ConnectError("no route to 203.0.113.7")
		with patch.object(locate.AsyncHttpWorkerPool, "default_transport", httpx.MockTransport(refuse)):
			answer = self.client.post("/api/system/locate").json()
		self.assertFalse(answer["ok"])
		self.assertNotIn("203", answer["message"])

if __name__ == "__main__":
	unittest.main()
