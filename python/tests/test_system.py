"""
The System page's data (#390): the machine's readings, the Raspberry Pi's own when it is one, and the storage by area, plugin and data source. Numbers and our own words only.
"""
import os
import unittest
from unittest.mock import patch

import httpx

from ..datasources.metering import METER
from ..web import locate, system_info
from ..web.system_info import pi_info, throttle_flags
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings

class TestPi(unittest.TestCase):
	def fake(self, files: dict[str, str]):
		return patch.object(system_info, "_read", lambda path, limit=256: files.get(path))

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

	def test_a_pi_in_a_container_is_found_by_its_processor_list(self):
		# Podman masks `/sys/firmware`, so `/proc/device-tree/model` cannot be read in the container; the kernel's `Model` line is the same name
		cpuinfo = "\n".join(["processor\t: 0", "BogoMIPS\t: 108.00", "", "Revision\t: d04170", "Model\t\t: Raspberry Pi 5 Model B Rev 1.0"])
		with self.fake({ system_info.PI_CPUINFO: cpuinfo, system_info.PI_TEMPERATURE: "52350" }):
			info = pi_info()
		assert info is not None
		self.assertEqual((info["model"], info["temperature_c"]), ("Raspberry Pi 5 Model B Rev 1.0", 52.4))
		with self.fake({ system_info.PI_CPUINFO: "\n".join(["processor\t: 0", "Model\t\t: Some Other Board"]) }):
			self.assertIsNone(pi_info())

	def test_the_fan_is_found_by_its_sensor_name_not_its_number(self):
		hwmon = lambda n, name: { os.path.join(system_info.HWMON, f"hwmon{n}", "name"): name }
		files = { system_info.PI_MODEL: "Raspberry Pi 5 Model B Rev 1.0", **hwmon(0, "cpu_thermal"), **hwmon(1, "rp1_adc"), **hwmon(2, "pwmfan"),
			os.path.join(system_info.HWMON, "hwmon2", "fan1_input"): "3120", os.path.join(system_info.HWMON, "hwmon2", "pwm1"): "102" }
		with self.fake(files), patch.object(system_info, "_entries", lambda path: ["hwmon0", "hwmon1", "hwmon2"]):
			info = pi_info()
		assert info is not None
		self.assertEqual((info["fan_rpm"], info["fan_percent"]), (3120, 40))
		# a Pi without a fan (or a reading it cannot give) has none
		del files[os.path.join(system_info.HWMON, "hwmon2", "name")]
		with self.fake(files), patch.object(system_info, "_entries", lambda path: ["hwmon0", "hwmon1", "hwmon2"]):
			self.assertNotIn("fan_rpm", pi_info() or {})

	def test_a_pi_without_get_throttled_says_under_voltage_from_its_voltage_sensor(self):
		# a Pi 5 has no `get_throttled`; its `rpi_volt` sensor's alarm is the warning that remains
		alarm = os.path.join(system_info.HWMON, "hwmon3", "in0_lcrit_alarm")
		files = { system_info.PI_MODEL: "Raspberry Pi 5 Model B Rev 1.1", os.path.join(system_info.HWMON, "hwmon3", "name"): "rpi_volt", alarm: "1" }
		entries = patch.object(system_info, "_entries", lambda path: ["hwmon3"])
		with self.fake(files), entries:
			info = pi_info()
		assert info is not None
		self.assertEqual((info["throttled"], info["throttled_now"]), (["Under-voltage now"], True))
		files[alarm] = "0"
		with self.fake(files), entries:
			info = pi_info()
		assert info is not None
		self.assertEqual((info["throttled"], info["throttled_now"]), ([], False))
		# `get_throttled`, where there is one, is the reading (it says more)
		with self.fake({ **files, alarm: "1", system_info.PI_THROTTLED: "0" }), entries:
			self.assertEqual((pi_info() or {})["throttled"], [])
		# neither: no power row
		del files[alarm]
		with self.fake(files), entries:
			self.assertNotIn("throttled", pi_info() or {})

	def test_the_power_bits_are_in_words(self):
		self.assertEqual(throttle_flags(0), [])
		self.assertEqual(throttle_flags(1 << 3), ["Temperature limit now"])
		self.assertEqual(throttle_flags(1 << 17), ["Frequency capped since start"])

class TestClockReading(unittest.TestCase):
	def test_the_clock_is_said_when_timesyncd_can_be_asked_and_left_out_when_not(self):
		from unittest.mock import patch
		from ..web import system_info
		for state, expected in (("synced", "synced"), ("unsynced", "unsynced"), ("unknown", None)):
			with self.subTest(state=state), patch.object(system_info.ClockSync, "state", return_value=state):
				self.assertEqual(system_info.host_info().get("clock"), expected)

class TestSystemRoute(WebApiTestBase):
	def test_the_machine_and_the_storage_are_reported(self):
		body = self.client.get("/api/system").json()
		self.assertEqual(sorted(body), ["host", "load", "pi", "storage", "usage"])
		self.assertTrue(body["host"]["python"])
		self.assertGreater(body["host"]["cpus"], 0)
		# the app has run for a moment, the machine for longer (or as long): two readings, not one
		self.assertIn("app_uptime_seconds", body["host"])
		self.assertLessEqual(body["host"]["app_uptime_seconds"], body["host"]["uptime_seconds"])
		self.assertGreater(body["load"]["memory"]["total"], 0)
		self.assertEqual([a["name"] for a in body["storage"]["areas"]], ["settings", "schedules", "plugins", "datasources", "schemas", "state"])
		self.assertGreater(body["storage"]["volume"]["total"], 0)

	def test_a_quota_the_user_set_is_on_the_usage_card_and_only_a_valid_one(self):
		METER.reset()
		self.addCleanup(METER.reset)
		METER.call("openweathermap-api", 200, None, 0, 10)
		# nothing set: no quota; set: the limit, the reset day and the period's calls
		usage = {u["id"]: u for u in self.client.get("/api/system").json()["usage"]}
		self.assertIsNone(usage["openweathermap-api"]["quota"])
		save_datasource_settings(self.cm, "openweathermap-api", { **self._settings("openweathermap-api"), "monthlyQuota": 1000, "quotaResetDay": 5 })
		save_datasource_settings(self.cm, "thunderforest-api", { **self._settings("thunderforest-api"), "monthlyQuota": 200 })
		usage = {u["id"]: u for u in self.client.get("/api/system").json()["usage"]}
		quota = usage["openweathermap-api"]["quota"]
		self.assertEqual((quota["limit"], quota["resetDay"], quota["used"]), (1000, 5, 1))
		# a source with a quota and no calls yet is there, at 0 and on the default reset day
		self.assertEqual((usage["thunderforest-api"]["quota"]["used"], usage["thunderforest-api"]["quota"]["resetDay"]), (0, 1))
		# a limit that is not a whole number above 0, or a reset day out of range, is no limit / the 1st
		save_datasource_settings(self.cm, "openweathermap-api", { **self._settings("openweathermap-api"), "monthlyQuota": 0, "quotaResetDay": 31 })
		save_datasource_settings(self.cm, "thunderforest-api", { **self._settings("thunderforest-api"), "monthlyQuota": 200, "quotaResetDay": 31 })
		usage = {u["id"]: u for u in self.client.get("/api/system").json()["usage"]}
		self.assertIsNone(usage["openweathermap-api"]["quota"])
		self.assertEqual(usage["thunderforest-api"]["quota"]["resetDay"], 1)

	def _settings(self, ident: str) -> dict:
		return dict(self.cm.datasource_manager(ident).open().get()[1] or {})

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
		with patch.object(system_info, "_read", lambda path, limit=256: "Raspberry Pi 5 Model B" if path == system_info.PI_MODEL else None):
			self.assertEqual(self.client.get("/api/system").json()["pi"]["model"], "Raspberry Pi 5 Model B")
		with patch.object(system_info, "_read", lambda path, limit=256: None):
			self.assertIsNone(self.client.get("/api/system").json()["pi"])

	def test_the_answer_model_passes_every_reading_and_leaves_out_what_is_missing(self):
		# the route's response model (#590) names every field: a Pi's readings all reach the page, and one it cannot give is absent, not null
		files = { system_info.PI_MODEL: "Raspberry Pi 5 Model B", system_info.PI_TEMPERATURE: "61250", system_info.PI_THROTTLED: "50005" }
		with patch.object(system_info, "_read", lambda path, limit=256: files.get(path)):
			pi = self.client.get("/api/system").json()["pi"]
			self.assertEqual(sorted(pi), sorted(pi_info() or {}))
		with patch.object(system_info, "_read", lambda path, limit=256: "Raspberry Pi 5 Model B" if path == system_info.PI_MODEL else None):
			self.assertNotIn("temperature_c", self.client.get("/api/system").json()["pi"])

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
