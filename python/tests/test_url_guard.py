import unittest
from unittest.mock import patch

import httpx

from ..utils import url_guard
from ..utils.url_guard import UrlRefused, check_url, fetch_checked, refused_reason

PUBLIC = "93.184.216.34"

def resolver(table: dict[str, list[str]]):
	"""A name service for the tests (they have no DNS): the names it does not know are not found."""
	async def resolve(host: str, port: int) -> list[str]:
		if host not in table:
			raise OSError("no such host")
		return table[host]
	return resolve

class TestRefusedReason(unittest.TestCase):
	def test_this_device_and_the_reserved_ranges_are_refused(self):
		for address in ("127.0.0.1", "127.1.2.3", "0.0.0.0", "::1", "::", "169.254.169.254", "169.254.0.1", "fe80::1", "224.0.0.1", "ff02::1", "240.0.0.1", "::ffff:127.0.0.1", "::ffff:169.254.169.254"):
			with self.subTest(address):
				self.assertIsNotNone(refused_reason(address))

	def test_an_ipv6_address_that_stands_for_an_ipv4_one_is_judged_by_it(self):
		"""Mapped, 6to4 and NAT64 forms reach the IPv4 address inside them on a network that translates them (#456)."""
		for inside, form in (("127.0.0.1", "2002:7f00:1::"), ("127.0.0.1", "64:ff9b::7f00:1"), ("169.254.169.254", "2002:a9fe:a9fe::1"), ("169.254.169.254", "64:ff9b::a9fe:a9fe"),
				("127.0.0.1", "::ffff:7f00:1"), ("0.0.0.0", "2002::")):
			with self.subTest(f"{form} is {inside}"):
				self.assertIsNotNone(refused_reason(form))
		# the same forms of a public IPv4 address are the internet (NAT64 is how an IPv6-only network reaches it)
		for form in ("2002:5db8:d822::", "64:ff9b::5db8:d822", "::ffff:5db8:d822"):
			with self.subTest(form):
				self.assertIsNone(refused_reason(form))

	def test_teredo_is_refused(self):
		self.assertEqual(refused_reason("2001:0:4136:e378:8000:63bf:3fff:fdd2"), "a reserved address")

	def test_the_home_network_and_the_internet_are_allowed(self):
		for address in ("192.168.1.20", "10.0.0.5", "172.16.4.4", "fd12:3456:789a::1", PUBLIC, "2606:2800:220:1:248:1893:25c8:1946", "::ffff:192.168.1.20"):
			with self.subTest(address):
				self.assertIsNone(refused_reason(address))

class TestCheckUrl(unittest.IsolatedAsyncioTestCase):
	async def test_only_http_and_https_with_a_host(self):
		for url in ("ftp://example.test/f", "file:///etc/passwd", "gopher://example.test", "http://", "example.test/feed", ""):
			with self.subTest(url), self.assertRaisesRegex(UrlRefused, "Only http and https"):
				await check_url(url)

	async def test_a_name_is_checked_by_every_address_it_has(self):
		table = { "ok.test": [PUBLIC], "inside.test": ["127.0.0.1"], "both.test": [PUBLIC, "10.0.0.1", "169.254.169.254"], "lan.test": ["192.168.1.9"] }
		with patch.object(url_guard, "_resolve", resolver(table)):
			await check_url("https://ok.test/feed")
			await check_url("http://lan.test:8080/feed")
			for url in ("https://inside.test/", "http://both.test/"):
				with self.subTest(url), self.assertRaisesRegex(UrlRefused, "cannot be used here"):
					await check_url(url)
			with self.assertRaisesRegex(UrlRefused, "could not be found"):
				await check_url("https://unknown.test/")

	async def test_an_address_is_checked_without_asking_a_name_service(self):
		async def never(host, port):
			raise AssertionError("an IP address needs no lookup")
		with patch.object(url_guard, "_resolve", never):
			await check_url("http://192.168.1.20/feed")
			await check_url("http://[2606:2800:220:1:248:1893:25c8:1946]/")
			for url in ("http://127.0.0.1/", "http://[::1]:8080/", "http://169.254.169.254/latest/meta-data"):
				with self.subTest(url), self.assertRaises(UrlRefused):
					await check_url(url)

	async def test_the_refusal_never_holds_the_address(self):
		with patch.object(url_guard, "_resolve", resolver({ "secret-host.test": ["127.0.0.1"] })):
			with self.assertRaises(UrlRefused) as raised:
				await check_url("https://user:token@secret-host.test/feed?key=abc")
		for leaked in ("secret-host", "token", "abc", "127.0.0.1"):
			self.assertNotIn(leaked, str(raised.exception))

class TestFetchChecked(unittest.IsolatedAsyncioTestCase):
	async def fetch(self, handler, url: str, table: dict[str, list[str]]|None = None, **kwargs):
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
			with patch.object(url_guard, "_resolve", resolver(table or { "a.test": [PUBLIC], "b.test": [PUBLIC] })):
				return await fetch_checked(client, url, **kwargs)

	async def test_the_body_is_returned(self):
		self.assertEqual(await self.fetch(lambda r: httpx.Response(200, content=b"<rss/>"), "https://a.test/feed"), b"<rss/>")

	async def test_a_redirect_is_followed_and_checked_at_every_hop(self):
		seen: list[str] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(str(request.url))
			if request.url.host == "a.test":
				return httpx.Response(302, headers={ "Location": "https://b.test/moved" })
			return httpx.Response(200, content=b"moved")
		self.assertEqual(await self.fetch(handler, "https://a.test/feed"), b"moved")
		self.assertEqual(seen, ["https://a.test/feed", "https://b.test/moved"])

	async def test_a_redirect_to_this_device_is_refused_and_never_requested(self):
		seen: list[str] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request.url.host)
			return httpx.Response(302, headers={ "Location": "http://127.0.0.1:8080/api/settings/system" })
		with self.assertRaises(UrlRefused):
			await self.fetch(handler, "https://a.test/feed")
		self.assertEqual(seen, ["a.test"], "the second request must not be made")

	async def test_a_relative_redirect_stays_on_the_host(self):
		def handler(request: httpx.Request) -> httpx.Response:
			return httpx.Response(302, headers={ "Location": "/there" }) if request.url.path == "/feed" else httpx.Response(200, content=request.url.path.encode())
		self.assertEqual(await self.fetch(handler, "https://a.test/feed"), b"/there")

	async def test_a_loop_of_redirects_ends(self):
		with self.assertRaisesRegex(UrlRefused, "too many times"):
			await self.fetch(lambda r: httpx.Response(302, headers={ "Location": "https://a.test/again" }), "https://a.test/feed")

	async def test_an_error_status_and_a_big_body_are_errors(self):
		with self.assertRaises(httpx.HTTPStatusError):
			await self.fetch(lambda r: httpx.Response(503), "https://a.test/feed")
		with self.assertRaisesRegex(RuntimeError, "too large"):
			await self.fetch(lambda r: httpx.Response(200, content=b"x" * 101), "https://a.test/feed", max_bytes=100)

class TestRedirectCredentials(unittest.IsolatedAsyncioTestCase):
	"""A redirect does not carry a sign-in to another origin (#456), and changes the method as the HTTP client would."""
	async def follow(self, routes: dict[str, httpx.Response], url: str, method: str = "GET", headers: dict[str, str]|None = None, content: bytes|None = None) -> list[httpx.Request]:
		"""Every request made, in order; `routes` answers by `scheme://host:port/path`, anything else is a 200."""
		seen: list[httpx.Request] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request)
			request.read()
			key = f"{request.url.scheme}://{request.url.host}:{request.url.port or (443 if request.url.scheme == 'https' else 80)}{request.url.path}"
			return routes.get(key) or httpx.Response(200, content=b"ok")
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
			with patch.object(url_guard, "_resolve", resolver({ "a.test": [PUBLIC], "b.test": [PUBLIC] })):
				async with url_guard.stream_checked(client, method, url, headers or { "Authorization": "Basic c2VjcmV0", "Cookie": "s=1", "Proxy-Authorization": "x", "User-Agent": "eink" }, content) as resp:
					await resp.aread()
		return seen
	def signed(self, request: httpx.Request) -> list[str]:
		return [h for h in ("authorization", "cookie", "proxy-authorization") if h in request.headers]
	def moved(self, to: str, status: int = 302) -> httpx.Response:
		return httpx.Response(status, headers={ "Location": to })

	async def test_a_redirect_on_the_same_origin_keeps_the_sign_in(self):
		seen = await self.follow({ "https://a.test:443/feed": self.moved("/moved") }, "https://a.test/feed")
		self.assertEqual([self.signed(r) for r in seen], [["authorization", "cookie", "proxy-authorization"]] * 2)

	async def test_a_redirect_to_another_host_drops_it_and_coming_back_does_not_bring_it_back(self):
		seen = await self.follow({
			"https://a.test:443/feed": self.moved("https://b.test/there"),
			"https://b.test:443/there": self.moved("https://a.test/back"),
		}, "https://a.test/feed")
		self.assertEqual([str(r.url) for r in seen], ["https://a.test/feed", "https://b.test/there", "https://a.test/back"])
		self.assertEqual([self.signed(r) for r in seen], [["authorization", "cookie", "proxy-authorization"], [], []])
		# what is not a sign-in still goes
		self.assertEqual(seen[1].headers["user-agent"], "eink")

	async def test_another_port_or_https_to_http_on_the_same_host_drops_it(self):
		for target in ("http://a.test/plain", "https://a.test:8443/other"):
			with self.subTest(target):
				seen = await self.follow({ "https://a.test:443/feed": self.moved(target) }, "https://a.test/feed")
				self.assertEqual(self.signed(seen[1]), [])

	async def test_the_header_names_are_matched_whatever_their_case(self):
		seen = await self.follow({ "https://a.test:443/feed": self.moved("https://b.test/x") }, "https://a.test/feed", headers={ "AUTHORIZATION": "Bearer t", "cookie": "s=1" })
		self.assertEqual(self.signed(seen[1]), [])

	async def test_a_303_after_a_report_is_a_get_with_no_body(self):
		seen = await self.follow({ "https://a.test:443/cal": self.moved("/result", 303) }, "https://a.test/cal", "REPORT",
			{ "Authorization": "Basic c2VjcmV0", "Content-Type": "application/xml", "Depth": "1" }, b"<query/>")
		self.assertEqual([(r.method, r.content) for r in seen], [("REPORT", b"<query/>"), ("GET", b"")])
		self.assertNotIn("content-type", seen[1].headers)

	async def test_a_307_keeps_the_method_and_the_body_and_a_301_keeps_a_report(self):
		for status in (307, 308, 301, 302):
			with self.subTest(status):
				seen = await self.follow({ "https://a.test:443/cal": self.moved("/moved", status) }, "https://a.test/cal", "REPORT", content=b"<query/>")
				self.assertEqual([(r.method, r.content) for r in seen], [("REPORT", b"<query/>")] * 2)

	async def test_a_post_on_a_301_or_302_becomes_a_get(self):
		for status in (301, 302):
			with self.subTest(status):
				seen = await self.follow({ "https://a.test:443/form": self.moved("/done", status) }, "https://a.test/form", "POST", content=b"a=1")
				self.assertEqual([r.method for r in seen], ["POST", "GET"])
				self.assertEqual(seen[1].content, b"")

	async def test_fetch_checked_follows_the_same_rules(self):
		seen: list[httpx.Request] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request)
			return self.moved("https://b.test/x") if request.url.host == "a.test" else httpx.Response(200, content=b"body")
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
			with patch.object(url_guard, "_resolve", resolver({ "a.test": [PUBLIC], "b.test": [PUBLIC] })):
				self.assertEqual(await fetch_checked(client, "https://a.test/feed", { "Authorization": "Bearer t" }), b"body")
		self.assertEqual([self.signed(r) for r in seen], [["authorization"], []])

class TestRunTimeFetches(unittest.IsolatedAsyncioTestCase):
	"""Addresses from a feed or an answer are fetched through the guard too (#189), not only by the Test buttons."""
	async def download(self, handler, url: str):
		from ..utils.image_utils import stream_to_buffer
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
			with patch.object(url_guard, "_resolve", resolver({ "a.test": [PUBLIC], "inside.test": ["127.0.0.1"] })):
				return (await stream_to_buffer(client, url)).read()

	async def test_a_public_download_works_and_follows_a_redirect(self):
		def handler(request: httpx.Request) -> httpx.Response:
			return httpx.Response(302, headers={ "Location": "/there" }) if request.url.path == "/start" else httpx.Response(200, content=b"picture")
		self.assertEqual(await self.download(handler, "https://a.test/start"), b"picture")

	async def test_this_device_and_the_metadata_address_are_never_requested(self):
		seen: list[str] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request.url.host)
			return httpx.Response(200, content=b"x")
		for url in ("http://127.0.0.1:8080/api/settings/system", "http://169.254.169.254/latest/meta-data/", "http://inside.test/p.jpg", "http://[::1]/x"):
			with self.subTest(url), self.assertRaises(UrlRefused):
				await self.download(handler, url)
		self.assertEqual(seen, [], "nothing was requested")

	async def test_a_redirect_from_a_public_host_to_this_device_is_stopped(self):
		seen: list[str] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request.url.host)
			return httpx.Response(302, headers={ "Location": "http://169.254.169.254/latest/meta-data/" })
		with self.assertRaises(UrlRefused):
			await self.download(handler, "https://a.test/pic.jpg")
		self.assertEqual(seen, ["a.test"])

	async def test_the_calendar_download_goes_through_the_guard(self):
		from ..datasources.calendar.sources import download
		async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"BEGIN:VCALENDAR"))) as client:
			with self.assertRaises(UrlRefused):
				await download(client, "GET", "http://127.0.0.1/cal.ics", {})
