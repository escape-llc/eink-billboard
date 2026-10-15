import json
import os
import unittest
from unittest.mock import patch

from starlette.websockets import WebSocketDisconnect

from ..task.telemetry_hub import TelemetryHub
from ..web.access import MIN_PASSWORD, SETUP_CODE_ENV, WRONG_CODES, clear_password, hash_password, password_problem, verify_password
from .test_web_api import WebApiTestBase

CODE = "1234 5678"
PASSWORD = "correct horse battery"

class TestPasswordHash(unittest.TestCase):
	def test_a_password_checks_against_its_record_only(self):
		record = hash_password(PASSWORD)
		self.assertEqual((record["algo"], record["n"], record["r"], record["p"]), ("scrypt", 2 ** 14, 8, 1))
		self.assertTrue(verify_password(PASSWORD, record))
		for wrong in ("correct horse battery ", "Correct horse battery", "", "x" * 300):
			with self.subTest(wrong):
				self.assertFalse(verify_password(wrong, record))
		self.assertNotIn(PASSWORD, json.dumps(record))

	def test_the_same_password_gives_different_records(self):
		self.assertNotEqual(hash_password(PASSWORD)["hash"], hash_password(PASSWORD)["hash"])

	def test_what_is_not_a_record_or_a_password_is_a_no(self):
		for record in (None, {}, "text", { "algo": "md5" }, { "algo": "scrypt", "n": 1 }, { "algo": "scrypt", "n": 16384, "r": 8, "p": 1, "salt": "zz", "hash": "00" }):
			with self.subTest(record):
				self.assertFalse(verify_password(PASSWORD, record))
		self.assertFalse(verify_password(None, hash_password(PASSWORD)))
		self.assertFalse(verify_password(12345678, hash_password(PASSWORD)))

	def test_a_short_or_huge_password_is_refused_in_words(self):
		self.assertIsNone(password_problem("x" * MIN_PASSWORD))
		for bad in ("short", "", None, 12345678, "x" * 300):
			with self.subTest(bad):
				self.assertIsInstance(password_problem(bad), str)

class AccessBase(WebApiTestBase):
	def setUp(self):
		patcher = patch.dict(os.environ, { SETUP_CODE_ENV: CODE })
		patcher.start()
		self.addCleanup(patcher.stop)
		super().setUp()

	def stored(self) -> dict:
		return self.cm.settings_manager().open("access").get()[1] or {}

class TestLocalDeviceIsOpen(AccessBase):
	"""Listening on this machine only: open as before, until a password is set."""
	def test_nothing_is_asked_and_nothing_is_to_set_up(self):
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		self.assertEqual(self.client.get("/api/access").json(), { "required": False, "setupRequired": False, "passwordSet": False, "localOnly": True })
		self.assertEqual(self.client.post("/api/session").json(), { "success": True, "required": False })

	def test_a_password_set_on_a_local_device_is_required_from_then_on(self):
		resp = self.client.put("/api/access/password", json={ "new": PASSWORD })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200, "the setter stays signed in")
		self.client.cookies.clear()
		other = self.client.get("/api/settings/system")
		self.assertEqual((other.status_code, other.json()["message"]), (401, "Sign in to use this device."))
		self.assertNotIn("setup", other.json())

class TestNewDeviceOnTheNetwork(AccessBase):
	local = False

	def test_everything_but_setup_asks_for_the_setup_first(self):
		resp = self.client.get("/api/settings/system")
		self.assertEqual((resp.status_code, resp.json()["setup"]), (401, True))
		self.assertEqual(self.client.get("/api/access").json(), { "required": True, "setupRequired": True, "passwordSet": False, "localOnly": False })
		self.assertEqual(self.client.post("/api/session", json={ "password": PASSWORD }).status_code, 401)

	def test_the_setup_code_claims_the_device_and_signs_in(self):
		self.assertEqual(self.client.post("/api/access/setup", json={ "code": "0000 0000", "password": PASSWORD }).status_code, 403)
		self.assertEqual(self.client.post("/api/access/setup", json={ "code": CODE, "password": "short" }).status_code, 422)
		resp = self.client.post("/api/access/setup", json={ "code": CODE.replace(" ", ""), "password": PASSWORD })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertIn("HttpOnly", resp.headers["set-cookie"])
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		self.assertEqual(self.client.post("/api/access/setup", json={ "code": CODE, "password": PASSWORD }).status_code, 409, "claimed once")

	def test_claiming_takes_the_setup_page_off_the_panel(self):
		calls = []
		self.app.state.access.on_claimed = lambda: calls.append(1)
		self.client.post("/api/access/setup", json={ "code": "0000 0000", "password": PASSWORD })
		self.assertEqual(calls, [], "a wrong code claims nothing")
		self.client.post("/api/access/setup", json={ "code": CODE, "password": PASSWORD })
		self.assertEqual(calls, [1])

	def test_the_hash_is_stored_and_never_served(self):
		self.client.post("/api/access/setup", json={ "code": CODE, "password": PASSWORD })
		record = self.stored()["passwordHash"]
		self.assertTrue(verify_password(PASSWORD, record))
		self.assertEqual(self.client.get("/api/settings/access").status_code, 404)
		self.assertEqual(self.client.get("/api/schemas/access").status_code, 404)
		self.assertEqual(self.client.put("/api/settings/access", json={ "passwordHash": None }).status_code, 404)
		for path in ("/api/access", "/api/settings/system", "/api/settings/display", "/api/telemetry"):
			body = self.client.get(path).text
			for leaked in (PASSWORD, record["hash"], record["salt"]):
				self.assertNotIn(leaked, body)

	def test_the_code_is_replaced_after_too_many_wrong_ones(self):
		access = self.app.state.access
		self.assertEqual(access.setup_code(), CODE)
		changed: list[int] = []
		access.on_code_changed = lambda: changed.append(1)
		with patch.dict(os.environ, { SETUP_CODE_ENV: "" }):
			for _ in range(WRONG_CODES):
				self.assertFalse(access.check_code("0000 0000"))
			second = access.setup_code()
		self.assertNotEqual(second, CODE)
		self.assertRegex(second or "", r"^\d{4} \d{4}$")
		self.assertEqual(changed, [1], "the panel's setup page is told once, so it shows the new code")
		self.assertFalse(access.check_code(CODE), "the old one no longer works")

	def test_the_telemetry_socket_waits_for_a_sign_in_too(self):
		self.app.state.root_container.add_service(TelemetryHub, TelemetryHub())
		with self.assertRaises(WebSocketDisconnect) as refused:
			with self.client.websocket_connect("/api/telemetry/ws"):
				pass
		self.assertEqual(refused.exception.code, 4401)

class TestClaimedDevice(AccessBase):
	local = False

	def setUp(self):
		super().setUp()
		self.client.post("/api/access/setup", json={ "code": CODE, "password": PASSWORD })
		self.client.cookies.clear()

	def test_the_password_signs_in_and_a_wrong_one_does_not(self):
		resp = self.client.get("/api/settings/system")
		self.assertEqual((resp.status_code, resp.json()["message"]), (401, "Sign in to use this device."))
		self.assertEqual(self.client.get("/api/access").json()["setupRequired"], False)
		wrong = self.client.post("/api/session", json={ "password": "not the password" })
		self.assertEqual((wrong.status_code, wrong.json()["message"]), (401, "Wrong password."))
		self.assertNotIn("not the password", wrong.text)
		self.assertEqual(self.client.post("/api/session", json={ "password": PASSWORD }).status_code, 200)
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		self.client.delete("/api/session")
		self.assertEqual(self.client.get("/api/settings/system").status_code, 401)

	def test_the_setup_code_is_gone(self):
		self.assertIsNone(self.app.state.access.setup_code())
		self.assertEqual(self.client.post("/api/access/setup", json={ "code": CODE, "password": "another password" }).status_code, 409)

	def test_changing_the_password_needs_the_current_one(self):
		self.client.post("/api/session", json={ "password": PASSWORD })
		self.assertEqual(self.client.put("/api/access/password", json={ "current": "nope nope nope", "new": "a brand new password" }).status_code, 403)
		self.assertEqual(self.client.put("/api/access/password", json={ "current": PASSWORD, "new": "short" }).status_code, 422)
		self.assertEqual(self.client.put("/api/access/password", json={ "current": PASSWORD, "new": "a brand new password" }).status_code, 200)
		self.client.cookies.clear()
		self.assertEqual(self.client.post("/api/session", json={ "password": PASSWORD }).status_code, 401)
		self.assertEqual(self.client.post("/api/session", json={ "password": "a brand new password" }).status_code, 200)

	def test_a_password_change_needs_a_sign_in_first(self):
		self.assertEqual(self.client.put("/api/access/password", json={ "current": PASSWORD, "new": "a brand new password" }).status_code, 401)

	def test_reset_makes_the_device_new_again(self):
		self.assertTrue(clear_password(self.cm))
		self.assertFalse(clear_password(self.cm), "nothing left to forget")
		self.assertEqual(self.client.get("/api/access").json()["setupRequired"], True)
		self.assertEqual(self.client.get("/api/settings/system").json()["setup"], True)

	def test_wrong_passwords_are_slowed_like_wrong_tokens(self):
		statuses = [self.client.post("/api/session", json={ "password": "guess number %d" % n }).status_code for n in range(6)]
		self.assertEqual(statuses[:3], [401, 401, 401])
		self.assertIn(429, statuses)
		self.assertEqual(self.client.post("/api/session", json={ "password": PASSWORD }).status_code, 429)

class TestDeviceWithAToken(AccessBase):
	"""The API token stays the credential of scripts, and it counts as claiming the device."""
	local = False
	token = "t0ken"

	def test_no_setup_is_asked_and_the_token_works(self):
		self.assertEqual(self.client.get("/api/access").json()["setupRequired"], False)
		self.assertEqual(self.client.get("/api/settings/system").status_code, 401)
		self.assertEqual(self.client.get("/api/settings/system", headers={ "Authorization": "Bearer t0ken" }).status_code, 200)

	def test_the_web_app_may_still_sign_in_with_the_token(self):
		self.assertEqual(self.client.post("/api/session", headers={ "Authorization": "Bearer t0ken" }).status_code, 200)
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)

class TestSwitches(AccessBase):
	def test_no_auth_keeps_a_network_device_open(self):
		self.app.state.access.mode = "none"
		self.app.state.access.local = False
		self.assertEqual(self.client.get("/api/settings/system").status_code, 200)
		self.assertEqual(self.client.get("/api/access").json()["required"], False)

	def test_require_auth_applies_the_rules_on_a_local_device(self):
		self.app.state.access.mode = "always"
		self.assertEqual(self.client.get("/api/settings/system").json()["setup"], True)
		self.assertEqual(self.client.get("/api/access").json()["localOnly"], True)

class TestPublicUrl(unittest.TestCase):
	def setUp(self):
		import importlib
		self.main = importlib.import_module("python.eink-billboard")

	def test_only_an_http_address_with_a_host_counts(self):
		of = self.main.public_url_of
		self.assertEqual(of(" http://localhost:8080/ "), "http://localhost:8080")
		self.assertEqual(of("https://billboard.home.arpa/app/"), "https://billboard.home.arpa/app")
		for bad in (None, "", "  ", "localhost:8080", "ftp://x", "javascript:alert(1)", "http://", "http://user:pw@host"):
			self.assertIsNone(of(bad), bad)

	def test_the_setup_page_and_the_log_use_it(self):
		from unittest.mock import MagicMock
		self.assertEqual(self.main.setup_address(8080, "http://localhost:8080"), "http://localhost:8080")
		access = MagicMock()
		access.setup_code.return_value = "1234 5678"
		self.assertEqual(self.main.setup_notice(access, 8080, "http://localhost:8080"), ["Open http://localhost:8080", "Setup code 1234 5678"])
		with self.assertLogs(self.main.logger, "WARNING") as logged:
			self.main.announce_setup_code(access, 8080, "http://localhost:8080")
		# a block of its own, the address and the code each on a line: easy to find in a long log, and to copy
		lines = logged.output[0].splitlines()
		self.assertIn("  Open the web app:  http://localhost:8080", lines)
		self.assertIn("  Setup code:        1234 5678", lines)
		self.assertEqual(sum(1 for line in lines if line.startswith("=====")), 2)

	def test_production_logs_less_than_development_and_the_environment_decides_last(self):
		import logging
		self.assertEqual(self.main.log_level(False, None), logging.INFO)
		self.assertEqual(self.main.log_level(True, None), logging.DEBUG)
		self.assertEqual(self.main.log_level(False, "debug"), logging.DEBUG)
		self.assertEqual(self.main.log_level(True, " Warning "), logging.WARNING)
		for unknown in ("", "loud", "5"):
			self.assertEqual(self.main.log_level(False, unknown), logging.INFO, unknown)

class TestSetupPageOnThePanel(unittest.TestCase):
	def application(self, notice):
		import tempfile
		from datetime import datetime, timezone
		from unittest.mock import MagicMock
		from ..model.configuration_manager import ConfigurationManager
		from ..task.application import Application
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		app = Application("t")
		app.cm = ConfigurationManager(storage_path=tmp.name)
		app.cm.hard_reset()
		app.router = MagicMock()
		app.setup_notice = notice
		return app, datetime(2026, 1, 1, tzinfo=timezone.utc)

	def test_an_unclaimed_device_shows_how_to_claim_it(self):
		from ..task.display_messages import PriorityImage
		app, now = self.application(lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		app._show_setup_notice(800, 480, now)
		route, message = app.router.send.call_args.args
		self.assertEqual(route, "display")
		self.assertIsInstance(message, PriorityImage)
		self.assertEqual((message.title, message.img.size), ("Set up this device", (800, 480)))

	def test_claiming_revokes_the_setup_page(self):
		from ..task.display_messages import PriorityRevoke
		from ..task.messages import SetupDone
		app, now = self.application(lambda: None)
		app._setup_done(SetupDone(now))
		route, message = app.router.send.call_args.args
		self.assertEqual(route, "display")
		self.assertIsInstance(message, PriorityRevoke)
		self.assertEqual(message.title, "Set up this device")

	def test_the_setup_page_holds_the_panel_until_the_device_is_claimed(self):
		from ..task.application import SETUP_HOLD
		app, now = self.application(lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		app._show_setup_notice(800, 480, now)
		self.assertGreater(app.router.send.call_args.args[1].duration.days, 365)
		self.assertEqual(app.router.send.call_args.args[1].duration, SETUP_HOLD)

	def layers_of(self, app, now, notice):
		"""The application as the display settings find it: two layers that record what they are sent."""
		from unittest.mock import MagicMock
		from ..task.display_messages import DisplaySettings
		app.setup_notice = notice
		app.root_container = MagicMock()
		app.root_container.get_service.return_value = None
		app.playlist_layer, app.timer_layer = MagicMock(), MagicMock()
		app._display_settings(DisplaySettings(now, "mock", 800, 480, []))
		return app.playlist_layer, app.timer_layer

	def test_an_unclaimed_device_does_not_start_its_layers_until_it_is_claimed(self):
		from ..task.configure_event import ConfigureEvent
		from ..task.messages import SetupDone
		app, now = self.application(lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		playlist, timer = self.layers_of(app, now, lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		playlist.accept.assert_not_called()
		timer.accept.assert_not_called()
		self.assertEqual(app.router.send.call_args.args[1].title, "Set up this device")
		app.setup_notice = lambda: None
		app._setup_done(SetupDone(now))
		for layer, token in ((playlist, "playlist-layer"), (timer, "timer-layer")):
			[(event,), _] = layer.accept.call_args
			self.assertIsInstance(event, ConfigureEvent)
			self.assertEqual(event.token, token)
		self.assertIsNone(app._held)

	def test_the_layers_are_told_where_the_web_app_is(self):
		from unittest.mock import MagicMock
		from ..task.display_messages import DisplaySettings
		from ..utils.error_image import WebAddress
		app, now = self.application(lambda: None)
		web = WebAddress("http://10.0.0.14:8080")
		app.root_container = MagicMock()
		app.root_container.get_service.side_effect = lambda kind: web if kind is WebAddress else None
		app.playlist_layer, app.timer_layer = MagicMock(), MagicMock()
		app._display_settings(DisplaySettings(now, "mock", 800, 480, []))
		for layer in (app.playlist_layer, app.timer_layer):
			[(event,), _] = layer.accept.call_args
			self.assertIs(event.content.isp.get_service(WebAddress), web)

	def test_a_claimed_device_starts_its_layers_at_once(self):
		app, now = self.application(lambda: None)
		playlist, timer = self.layers_of(app, now, lambda: None)
		playlist.accept.assert_called_once()
		timer.accept.assert_called_once()
		app.router.send.assert_not_called()

	def test_a_new_setup_code_is_put_on_the_panel(self):
		from ..task.display_messages import PriorityImage, PriorityRevoke
		from ..task.messages import SetupCodeChanged
		app, now = self.application(lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		self.layers_of(app, now, lambda: ["Open http://pi.local", "Setup code 1234 5678"])
		app.router.send.reset_mock()
		app.setup_notice = lambda: ["Open http://pi.local", "Setup code 8765 4321"]
		app._setup_code_changed(SetupCodeChanged(now))
		sent = [call.args[1] for call in app.router.send.call_args_list]
		self.assertEqual([type(m) for m in sent], [PriorityRevoke, PriorityImage])
		# a claimed device (nothing held) has no page to refresh
		app._held = None
		app.router.send.reset_mock()
		app._setup_code_changed(SetupCodeChanged(now))
		app.router.send.assert_not_called()

	def test_a_claimed_device_shows_nothing(self):
		app, now = self.application(lambda: None)
		app._show_setup_notice(800, 480, now)
		app.router.send.assert_not_called()
