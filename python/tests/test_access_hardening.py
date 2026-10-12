import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ..task.telemetry_hub import TelemetryHub
from ..web.app import WebSettings, create_app
from ..web.hosts import HostPolicy, host_of
from ..web.sessions import SignInThrottle
from .test_web_api import WebApiTestBase

class TestHostOf(unittest.TestCase):
	def test_the_port_and_the_brackets_go(self):
		for header, host in (("localhost:8080", "localhost"), ("Example.COM", "example.com"), ("[::1]:8080", "::1"), ("[::1]", "::1"), ("192.168.1.5:80", "192.168.1.5"), ("", None), (None, None)):
			with self.subTest(header):
				self.assertEqual(host_of(header), host)

class TestHostPolicy(unittest.TestCase):
	def test_this_device_by_any_address_or_its_names(self):
		policy = HostPolicy()
		for header in ("localhost", "localhost:8080", "127.0.0.1:8080", "[::1]:80", "192.168.1.20", "10.0.0.5:8080", "[fe80::1]", "app.localhost"):
			with self.subTest(header):
				self.assertTrue(policy.allows(header))

	def test_a_name_that_could_be_rebound_is_refused(self):
		policy = HostPolicy()
		for header in ("evil.example", "evil.example:8080", "rebind.attacker.test", "localhost.evil.example", None, ""):
			with self.subTest(header):
				self.assertFalse(policy.allows(header))

	def test_names_from_the_user_are_allowed(self):
		policy = HostPolicy(("Eink.Home.Arpa",))
		self.assertTrue(policy.allows("eink.home.arpa:8080"))
		self.assertFalse(policy.allows("other.home.arpa"))

class TestServerRefusesOtherNames(WebApiTestBase):
	def test_a_rebound_name_gets_421_in_the_error_shape(self):
		resp = self.client.get("/api/settings/system", headers={ "Host": "rebind.attacker.test:8080" })
		self.assertEqual(resp.status_code, 421)
		body = resp.json()
		self.assertEqual((body["success"], sorted(body)), (False, ["id", "message", "success"]))

	def test_the_web_app_and_unknown_paths_are_refused_too(self):
		for path in ("/", "/api/nothing", "/api/session"):
			with self.subTest(path):
				self.assertEqual(self.client.get(path, headers={ "Host": "rebind.attacker.test" }).status_code, 421)

	def test_the_address_works(self):
		self.assertEqual(self.client.get("/api/settings/system", headers={ "Host": "192.168.1.20:8080" }).status_code, 200)

	def test_the_telemetry_socket_checks_the_name_as_well(self):
		self.app.state.root_container.add_service(TelemetryHub, TelemetryHub())
		with self.assertRaises(WebSocketDisconnect) as refused:
			with self.client.websocket_connect("/api/telemetry/ws", headers={ "Host": "rebind.attacker.test" }):
				pass
		self.assertEqual(refused.exception.code, 4403)

	def test_a_name_from_allow_host_is_answered(self):
		client = TestClient(create_app(WebSettings(allowed_hosts=("eink.home.arpa",))))
		self.assertNotEqual(client.get("/api/nothing", headers={ "Host": "eink.home.arpa" }).status_code, 421)

class Clock:
	def __init__(self):
		self.now = 1000.0
	def __call__(self):
		return self.now

class TestSignInThrottle(unittest.TestCase):
	def test_a_few_failures_are_free_then_the_wait_doubles(self):
		clock = Clock()
		throttle = SignInThrottle(clock)
		waits = []
		for _ in range(7):
			waits.append(throttle.wait("10.0.0.9"))
			throttle.failed("10.0.0.9")
		self.assertEqual(waits[:4], [0, 0, 0, 0])
		throttle.failed("10.0.0.9")
		self.assertEqual(throttle.wait("10.0.0.9"), 32.0)
		clock.now += 32.1
		self.assertEqual(throttle.wait("10.0.0.9"), 0.0)

	def test_the_wait_has_a_ceiling_and_a_success_or_quiet_forgets(self):
		clock = Clock()
		throttle = SignInThrottle(clock)
		for _ in range(40):
			throttle.failed("a")
		self.assertEqual(throttle.wait("a"), throttle.MAX_WAIT)
		self.assertEqual(throttle.wait("b"), 0.0, "another client is not slowed")
		throttle.succeeded("a")
		self.assertEqual(throttle.wait("a"), 0.0)
		for _ in range(8):
			throttle.failed("a")
		clock.now += throttle.FORGET_AFTER + 1
		self.assertEqual(throttle.wait("a"), 0.0)

class TestSignInRoute(WebApiTestBase):
	token = "t0ken"

	def test_wrong_tokens_are_slowed_with_429_and_the_right_one_works_after(self):
		statuses = [self.client.post("/api/session", headers={ "Authorization": "Bearer guess-4242" }).status_code for _ in range(6)]
		self.assertEqual(statuses[:3], [401, 401, 401])
		self.assertIn(429, statuses)
		resp = self.client.post("/api/session", headers={ "Authorization": f"Bearer {self.token}" })
		self.assertEqual(resp.status_code, 429, "even the right token waits while the door is closed")
		self.assertIn("retry-after", resp.headers)
		self.assertNotIn("guess-4242", resp.text)
