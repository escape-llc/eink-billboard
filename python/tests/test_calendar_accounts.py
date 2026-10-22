import base64
import hashlib
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx

from ..datasources.calendar.accounts import (AccountError, TokenStore, access_token, finish_google, poll_microsoft, read_account_calendar,
	read_google, read_microsoft, start)
from ..datasources.calendar.calendar import CalendarSources
from ..datasources.data_source import DataSourceExecutionContext
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .test_calendar import NOW, ZONE, FakeSettings, at
from .test_datasource_fixes import STATIC, _Cob
from .test_web_api import WebApiTestBase
from .utils import use_transport

GOOGLE = { "name": "Home", "provider": "google", "clientId": "g-client", "clientSecret": "g-secret" }
MICROSOFT = { "name": "Work", "provider": "microsoft", "clientId": "m-client", "tenant": "common" }

class FakeProviders(httpx.MockTransport):
	"""Google's and Microsoft's sign-in and calendar APIs, as far as the data source uses them. `requests` keeps what was asked."""
	def __init__(self, device_answers: list[dict]|None = None, refresh: dict|None = None):
		self.requests: list[httpx.Request] = []
		self.forms: list[dict] = []
		# what the device-code token endpoint answers, one per poll
		self.device_answers = list(device_answers or [])
		self.refresh = refresh
		super().__init__(self._handle)

	def _handle(self, request: httpx.Request) -> httpx.Response:
		self.requests.append(request)
		url = str(request.url)
		form = { k: v[0] for k, v in parse_qs(request.content.decode()).items() } if request.method == "POST" else {}
		self.forms.append(form)
		if url == "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode":
			if form.get("client_id") != "m-client":
				return httpx.Response(400, json={ "error": "invalid_client", "error_description": "AADSTS700016: secret detail" })
			return httpx.Response(200, json={ "device_code": "dev-123", "user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900, "interval": 5 })
		if url == "https://login.microsoftonline.com/common/oauth2/v2.0/token":
			if form.get("grant_type") == "refresh_token":
				return httpx.Response(200, json=self.refresh) if self.refresh else httpx.Response(400, json={ "error": "invalid_grant" })
			answer = self.device_answers.pop(0)
			return httpx.Response(200 if "access_token" in answer else 400, json=answer)
		if url == "https://oauth2.googleapis.com/token":
			if form.get("grant_type") == "refresh_token":
				return httpx.Response(200, json=self.refresh) if self.refresh else httpx.Response(400, json={ "error": "invalid_grant" })
			if form.get("code") != "the-code":
				return httpx.Response(400, json={ "error": "invalid_grant" })
			return httpx.Response(200, json={ "access_token": "g-access", "refresh_token": "g-refresh", "expires_in": 3599 })
		if request.url.host == "www.googleapis.com" and request.url.path == "/calendar/v3/users/me/calendarList":
			return httpx.Response(200, json={ "items": [{ "id": "primary@example.test", "summary": "Home" }, { "id": "family#holiday@group", "summary": "Family" }] })
		if request.url.host == "www.googleapis.com" and request.url.path.startswith("/calendar/v3/calendars/"):
			page = request.url.params.get("pageToken")
			if page is None:
				return httpx.Response(200, json={ "nextPageToken": "p2", "items": [
					{ "summary": "Dentist", "start": { "dateTime": "2026-10-08T16:30:00Z" }, "end": { "dateTime": "2026-10-08T17:15:00Z" }, "location": "Main St" },
					{ "summary": "Called off", "status": "cancelled", "start": { "dateTime": "2026-10-09T16:30:00Z" }, "end": { "dateTime": "2026-10-09T17:00:00Z" } },
				] })
			return httpx.Response(200, json={ "items": [{ "summary": "School holiday", "start": { "date": "2026-10-16" }, "end": { "date": "2026-10-17" } }] })
		if request.url.host == "graph.microsoft.com" and request.url.path == "/v1.0/me/calendars":
			return httpx.Response(200, json={ "value": [{ "id": "AAMk-1", "name": "Calendar" }] })
		if request.url.host == "graph.microsoft.com" and "calendarView" in request.url.path:
			if request.url.params.get("$skip") is None:
				return httpx.Response(200, json={ "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/calendarView?$skip=1", "value": [
					{ "subject": "Standup", "isAllDay": False, "start": { "dateTime": "2026-10-08T16:00:00.0000000", "timeZone": "UTC" }, "end": { "dateTime": "2026-10-08T16:15:00.0000000", "timeZone": "UTC" } },
				] })
			return httpx.Response(200, json={ "value": [
				{ "subject": "Offsite", "isAllDay": True, "start": { "dateTime": "2026-10-20T00:00:00.0000000" }, "end": { "dateTime": "2026-10-22T00:00:00.0000000" }, "location": { "displayName": "Lodge" } },
				{ "subject": "Gone", "isCancelled": True, "start": { "dateTime": "2026-10-21T10:00:00.0000000" }, "end": { "dateTime": "2026-10-21T11:00:00.0000000" } },
			] })
		raise httpx.ConnectError(f"offline test: {request.method} {url}", request=request)

class TokenStoreCase(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.cm = ConfigurationManager(storage_path=self.tmp.name)
		self.cm.ensure_folders()
		self.dsm = self.cm.datasource_manager("calendar")
		self.store = TokenStore(self.dsm)

	def connect(self, name: str, provider: str, client_id: str, expires_in: float = 3600, refresh: str = "old-refresh"):
		self.store.put(name, { "provider": provider, "client_id": client_id, "refresh_token": refresh, "access_token": "old-access", "expires_at": time.time() + expires_in })

class TestTokenStore(TokenStoreCase):
	def test_tokens_are_per_account_and_client(self):
		self.connect("Home", "google", "g-client")
		self.assertEqual(self.store.get("Home", "g-client")["refresh_token"], "old-refresh")
		self.assertIsNone(self.store.get("Home", "another-client"), "a new client must connect again")
		self.assertIsNone(self.store.get("Nobody", "g-client"))

	def test_accounts_that_are_gone_lose_their_tokens(self):
		self.connect("Home", "google", "g-client")
		self.connect("Old", "google", "g-client")
		self.store.put("Work", { "client_id": "m", "refresh_token": "r" }, keep={ "Home", "Work" })
		# the file's own `_version` is not an account
		self.assertEqual(sorted(k for k in (self.dsm.file("tokens").get()[1] or {}) if k != "_version"), ["Home", "Work"])

class TestMicrosoftSignIn(TokenStoreCase):
	async def test_the_device_code_flow_waits_then_keeps_the_tokens(self):
		fake = FakeProviders([{ "error": "authorization_pending" }, { "error": "slow_down" }, { "access_token": "m-access", "refresh_token": "m-refresh", "expires_in": 3600 }])
		async with httpx.AsyncClient(transport=fake) as client:
			first = await start(client, MICROSOFT)
			self.assertEqual((first["code"], first["link"], first["poll"]), ("ABCD-EFGH", "https://microsoft.com/devicelogin", 5))
			self.assertEqual(fake.forms[0]["scope"], "offline_access Calendars.Read")
			self.assertEqual(await poll_microsoft(client, first["session"], self.store, { "Work" }), { "done": False, "poll": 5 })
			self.assertEqual(await poll_microsoft(client, first["session"], self.store, { "Work" }), { "done": False, "poll": 10 }, "slow down: ask less often")
			done = await poll_microsoft(client, first["session"], self.store, { "Work" })
		self.assertTrue(done["done"] and done["ok"])
		self.assertEqual(done["message"], "'Work' is connected. Its calendars: Calendar (AAMk-1)")
		self.assertEqual(self.store.get("Work", "m-client")["refresh_token"], "m-refresh")
		self.assertNotIn("m-refresh", json.dumps(done))
		with self.assertRaisesRegex(AccountError, "expired"):
			await poll_microsoft(httpx.AsyncClient(transport=fake), first["session"], self.store, set())

	async def test_a_declined_or_expired_code_ends_the_sign_in(self):
		for answer, words in (({ "error": "authorization_declined" }, "declined"), ({ "error": "expired_token" }, "expired before the sign-in")):
			with self.subTest(answer):
				fake = FakeProviders([answer])
				async with httpx.AsyncClient(transport=fake) as client:
					first = await start(client, MICROSOFT)
					with self.assertRaisesRegex(AccountError, words):
						await poll_microsoft(client, first["session"], self.store, set())
				self.assertIsNone(self.store.get("Work", "m-client"))

	async def test_a_wrong_client_says_so_without_the_providers_words(self):
		async with httpx.AsyncClient(transport=FakeProviders()) as client:
			with self.assertRaises(AccountError) as raised:
				await start(client, { **MICROSOFT, "clientId": "wrong" })
		self.assertIn("invalid_client", str(raised.exception))
		self.assertNotIn("secret detail", str(raised.exception))

	async def test_an_account_row_that_cannot_work_is_refused_before_asking(self):
		fake = FakeProviders()
		async with httpx.AsyncClient(transport=fake) as client:
			for row, words in (({ **MICROSOFT, "clientId": "" }, "client id"), ({ **GOOGLE, "clientSecret": None }, "client secret"),
					({ **MICROSOFT, "tenant": "x/../y" }, "tenant"), ({ **MICROSOFT, "provider": "yahoo" }, "no provider")):
				with self.subTest(row), self.assertRaisesRegex(AccountError, words):
					await start(client, row)
		self.assertEqual(fake.requests, [])

class TestGoogleSignIn(TokenStoreCase):
	async def test_the_pasted_address_is_exchanged_with_the_pkce_verifier(self):
		fake = FakeProviders()
		async with httpx.AsyncClient(transport=fake) as client:
			first = await start(client, GOOGLE)
			link = parse_qs(urlsplit(first["link"]).query)
			self.assertEqual((link["redirect_uri"][0], link["code_challenge_method"][0], link["access_type"][0]), ("http://localhost", "S256", "offline"))
			self.assertEqual(link["scope"][0], "https://www.googleapis.com/auth/calendar.readonly")
			self.assertEqual(first["input"], "The address your browser went to")
			pasted = f"http://localhost/?state={link['state'][0]}&code=the-code&scope=x"
			done = await finish_google(client, first["session"], pasted, GOOGLE, self.store, { "Home" })
		self.assertEqual(done["message"], "'Home' is connected. Its calendars: Home (primary@example.test); Family (family#holiday@group)")
		exchange = next(f for f in fake.forms if f.get("grant_type") == "authorization_code")
		verifier = exchange["code_verifier"]
		challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
		self.assertEqual(challenge, link["code_challenge"][0])
		self.assertEqual((exchange["client_secret"], exchange["redirect_uri"]), ("g-secret", "http://localhost"))
		self.assertEqual(self.store.get("Home", "g-client")["refresh_token"], "g-refresh")

	async def test_an_address_from_another_sign_in_or_without_a_code_is_refused(self):
		async with httpx.AsyncClient(transport=FakeProviders()) as client:
			first = await start(client, GOOGLE)
			state = parse_qs(urlsplit(first["link"]).query)["state"][0]
			with self.assertRaisesRegex(AccountError, "another sign-in"):
				await finish_google(client, first["session"], "http://localhost/?state=forged&code=the-code", GOOGLE, self.store, set())
			with self.assertRaisesRegex(AccountError, "no code"):
				await finish_google(client, first["session"], f"http://localhost/?state={state}", GOOGLE, self.store, set())
			with self.assertRaisesRegex(AccountError, "did not allow"):
				await finish_google(client, first["session"], f"http://localhost/?state={state}&error=access_denied", GOOGLE, self.store, set())
			with self.assertRaisesRegex(AccountError, "expired"):
				await finish_google(client, "made-up", "http://localhost/?code=x", GOOGLE, self.store, set())
		self.assertIsNone(self.store.get("Home", "g-client"))

class TestAccessTokens(TokenStoreCase):
	async def test_a_fresh_token_is_used_as_it_is(self):
		self.connect("Home", "google", "g-client")
		fake = FakeProviders()
		async with httpx.AsyncClient(transport=fake) as client:
			self.assertEqual(await access_token(client, GOOGLE, self.store), "old-access")
		self.assertEqual(fake.requests, [])

	async def test_an_ending_token_is_refreshed_and_a_new_refresh_token_kept(self):
		self.connect("Work", "microsoft", "m-client", expires_in=30)
		fake = FakeProviders(refresh={ "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600 })
		async with httpx.AsyncClient(transport=fake) as client:
			self.assertEqual(await access_token(client, MICROSOFT, self.store), "new-access")
		self.assertEqual(self.store.get("Work", "m-client")["refresh_token"], "new-refresh")
		# Google does not send a new refresh token: the old one stays
		self.connect("Home", "google", "g-client", expires_in=-1)
		async with httpx.AsyncClient(transport=FakeProviders(refresh={ "access_token": "g-new", "expires_in": 3600 })) as client:
			self.assertEqual(await access_token(client, GOOGLE, self.store), "g-new")
		self.assertEqual(self.store.get("Home", "g-client")["refresh_token"], "old-refresh")

	async def test_a_refused_refresh_or_no_connection_is_permanent(self):
		self.connect("Home", "google", "g-client", expires_in=-1)
		async with httpx.AsyncClient(transport=FakeProviders()) as client:
			with self.assertRaisesRegex(PermanentError, "Sign in to the account 'Home' again"):
				await access_token(client, GOOGLE, self.store)
			with self.assertRaisesRegex(PermanentError, "'Work' is not connected"):
				await access_token(client, MICROSOFT, self.store)

class TestReading(TokenStoreCase):
	async def test_google_events_page_by_page_in_the_device_zone(self):
		fake = FakeProviders()
		async with httpx.AsyncClient(transport=fake) as client:
			events = await read_google(client, "tok", "family#holiday@group", at(1), at(1, month=11), ZONE, "Home", "#123456")
		self.assertEqual([(e.title, e.start, e.all_day) for e in events], [("Dentist", at(8, 9, 30), False), ("School holiday", at(16), True)])
		first = fake.requests[0]
		self.assertEqual(first.url.raw_path.decode().split("?")[0], "/calendar/v3/calendars/family%23holiday%40group/events", "the id is one path segment")
		self.assertEqual((first.url.params["singleEvents"], first.url.params["timeMin"]), ("true", "2026-10-01T07:00:00Z"))
		self.assertEqual(first.headers["Authorization"], "Bearer tok")

	async def test_microsoft_events_page_by_page_in_utc_then_the_device_zone(self):
		fake = FakeProviders()
		async with httpx.AsyncClient(transport=fake) as client:
			events = await read_microsoft(client, "tok", None, at(1), at(1, month=11), ZONE, "Work", None)
		self.assertEqual([(e.title, e.start, e.all_day) for e in events], [("Standup", at(8, 9), False), ("Offsite", at(20), True)])
		self.assertEqual(events[1].days()[-1], datetime(2026, 10, 21).date(), "an all-day event keeps its days")
		self.assertEqual(events[1].location, "Lodge")
		self.assertEqual(fake.requests[0].headers["Prefer"], 'outlook.timezone="UTC"')
		self.assertEqual(fake.requests[0].url.path, "/v1.0/me/calendarView")

	async def test_a_calendar_row_needs_its_account_of_the_same_provider(self):
		settings = { "accounts": [GOOGLE] }
		async with httpx.AsyncClient(transport=FakeProviders()) as client:
			for entry, words in (({ "name": "Cal", "source": "google", "account": "Nobody" }, "names no account"),
					({ "name": "Cal", "source": "microsoft", "account": "Home" }, "is microsoft, but its account 'Home' is google"),
					({ "name": "Cal", "source": "google", "account": "Home" }, "'Home' is not connected")):
				with self.subTest(entry), self.assertRaisesRegex(PermanentError, words):
					await read_account_calendar(client, entry, settings, self.store, at(1), at(2), ZONE)

class FolderSettings:
	"""Stands in for DatasourceConfigurationManager: these settings, and the real manager's files (where the tokens live)."""
	datasource_id = "calendar"
	def __init__(self, document, real):
		self.document = document
		self.real = real
	def open(self):
		return _Cob(self.document)
	def file(self, name):
		return self.real.file(name)

class TestSlot(TokenStoreCase):
	async def test_a_connected_accounts_calendars_show_with_the_others(self):
		self.connect("Home", "google", "g-client")
		self.connect("Work", "microsoft", "m-client")
		settings = { "cacheHours": 0, "accounts": [GOOGLE, MICROSOFT], "holidays": [], "calendars": [
			{ "name": "Mine", "source": "google", "account": "Home", "calendarId": None, "color": "#3366cc" },
			{ "name": "Job", "source": "microsoft", "account": "Work", "calendarId": "AAMk-1" },
		] }
		root = ServiceContainer()
		root.add_service(DatasourceConfigurationManager, cast(Any, FolderSettings(settings, self.dsm)))
		root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings()))
		root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
		fake = FakeProviders()
		use_transport(self, fake)
		answer = await CalendarSources("calendar", "Calendar Sources").open_async(DataSourceExecutionContext(root, (800, 480), NOW), { "start": NOW, "end": NOW + timedelta(days=31) })
		self.assertEqual({ (e.calendar, e.title) for e in answer.events }, { ("Mine", "Dentist"), ("Mine", "School holiday"), ("Job", "Standup"), ("Job", "Offsite") })
		self.assertIn("/v1.0/me/calendars/AAMk-1/calendarView", [r.url.path for r in fake.requests])

class TestConnectRoutes(WebApiTestBase):
	"""The Connect button's steps, through the real routes, from the saved settings."""
	def setUp(self):
		super().setUp()
		self.write_datasource_settings("calendar", { "weekStart": "monday", "cacheHours": 0.25, "staleDays": 30, "calendars": [], "holidays": [], "accounts": [GOOGLE, MICROSOFT] })
		self.fake = FakeProviders([{ "error": "authorization_pending" }, { "access_token": "m-access", "refresh_token": "m-refresh", "expires_in": 3600 }])
		patcher = patch.object(AsyncHttpWorkerPool, "default_transport", self.fake)
		patcher.start()
		self.addCleanup(patcher.stop)

	def post(self, step: str, body: dict) -> dict:
		resp = self.client.post(f"/api/datasource/calendar/connect/{step}", json=body)
		self.assertEqual(resp.status_code, 200, resp.text)
		return resp.json()

	def test_microsoft_connects_and_the_tokens_are_never_sent(self):
		first = self.post("start", { "key": "Work" })
		self.assertEqual((first["done"], first["code"]), (False, "ABCD-EFGH"))
		self.assertEqual(self.post("poll", { "session": first["session"] }), { "done": False, "poll": 5 })
		done = self.post("poll", { "session": first["session"] })
		self.assertTrue(done["ok"] and done["done"])
		with open(os.path.join(self.storage, "datasources", "calendar", "tokens.json"), encoding="utf-8") as f:
			self.assertEqual(json.load(f)["Work"]["refresh_token"], "m-refresh")
		settings = self.client.get("/api/datasources/calendar/settings").text
		self.assertNotIn("m-refresh", settings)
		self.assertNotIn("g-secret", settings, "the client secret is masked too")

	def test_google_connects_with_the_pasted_address(self):
		first = self.post("start", { "key": "Home" })
		state = parse_qs(urlsplit(first["link"]).query)["state"][0]
		done = self.post("continue", { "session": first["session"], "value": f"http://localhost/?code=the-code&state={state}" })
		self.assertTrue(done["ok"])
		self.assertIn("Family (family#holiday@group)", done["message"])

	def test_an_unsaved_account_or_a_stale_session_is_told_in_words(self):
		self.assertEqual(self.post("start", { "key": "Unsaved" }), { "done": True, "ok": False, "message": "Save the settings first: Connect uses the saved account." })
		self.assertEqual(self.post("poll", { "session": "nope" })["message"], "This sign-in has expired. Start again with Connect.")
		self.assertFalse(self.post("continue", { "session": None, "value": "x" })["ok"])

	def test_a_provider_that_cannot_be_reached_is_said_so(self):
		with patch.object(AsyncHttpWorkerPool, "default_transport", httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)))):
			answer = self.post("start", { "key": "Work" })
		self.assertEqual(answer, { "done": True, "ok": False, "message": "Could not reach the provider (ConnectError). Try again." })

	def test_the_account_rows_are_checked_on_save(self):
		doc = self.client.get("/api/datasources/calendar/settings").json()
		self.assertEqual(doc["accounts"][0]["clientSecret"], "********")
		doc["calendars"] = [{ "name": "Mine", "source": "google", "account": "Gone" }]
		doc["accounts"][1]["tenant"] = "a/b"
		resp = self.client.put("/api/datasources/calendar/settings", json=doc)
		self.assertEqual(resp.status_code, 422)
		self.assertEqual(resp.json()["errors"], [
			{ "path": ["calendars", "0", "account"], "message": "Not one of the allowed values" },
			{ "path": ["accounts", "1", "tenant"], "message": "Not in the expected format" },
		])
		doc["calendars"][0]["account"] = "Home"
		doc["accounts"][1]["tenant"] = "contoso.onmicrosoft.com"
		self.assertEqual(self.client.put("/api/datasources/calendar/settings", json=doc).status_code, 200)
		_, stored = self.cm.datasource_manager("calendar").open().get()
		self.assertEqual(stored["accounts"][0]["clientSecret"], "g-secret", "the masked secret was kept")
		self.assertEqual((stored["calendars"][0]["url"], stored["calendars"][0]["auth"]), (None, None), "an account calendar has no address")

if __name__ == "__main__":
	unittest.main()
