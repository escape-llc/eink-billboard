"""
Google and Microsoft calendars: connecting an account (signing in once, from the settings page) and reading its calendars.

The device has no browser of its own, so each provider's sign-in happens on whatever device the user has:
- **Microsoft: the device code flow** (RFC 8628). The settings page shows a code and the microsoft.com address; the user signs in
  anywhere, and the page asks this server to poll until the sign-in is done.
- **Google: the authorization code flow with PKCE** and a `http://localhost` redirect (Google's device flow does not allow calendar
  scopes). The page opens Google's sign-in; the browser ends on a localhost address that does not load; the user pastes that address
  back, and this server exchanges the code.
Both need the user's own app registration (a Google "Desktop" OAuth client, an Entra public client), whose ids are in the account's row.

**Tokens never go in the settings** (the browser reads those): they are in `tokens.json` in the data source's storage folder, written
atomically, read by nothing that serves a route. A token is for the account's name *and* client id: a changed client means "not connected".
Messages from here are ours: never a token, a code or a provider's error text beyond its error code.
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx

from ...model.configuration_manager import _internal_save
from ...plugins.plugin_base import PermanentError
from .sources import Event, _text, safe_color

logger = logging.getLogger(__name__)

PROVIDERS = ("google", "microsoft")
MICROSOFT_LOGIN = "https://login.microsoftonline.com"
MICROSOFT_SCOPE = "offline_access Calendars.Read"
GRAPH = "https://graph.microsoft.com/v1.0"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
# a Desktop client may redirect to the loopback address; nothing listens there, the user copies the address instead
GOOGLE_REDIRECT = "http://localhost"
TENANT = re.compile(r"^[A-Za-z0-9.-]{1,64}$")
# a sign-in started from the settings page is good for this long
SESSION_SECONDS = 15 * 60
# refresh a little before the provider says the access token ends
EARLY_SECONDS = 120
MAX_PAGES = 20

class AccountError(RuntimeError):
	"""A connect step that did not work; the message is ours and safe to show."""

# ---- the token file -------------------------------------------------------------------------------------------------------------

class TokenStore:
	"""The tokens of the connected accounts, by account name, in one JSON file. One lock for the process: the web app and the layers share it."""
	_lock = threading.Lock()

	def __init__(self, folder: str):
		self.path = os.path.join(folder, "tokens.json")

	def _load(self) -> dict:
		try:
			with open(self.path, "r", encoding="utf-8") as f:
				data = json.load(f)
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def get(self, name: str, client_id: str) -> dict|None:
		"""The tokens of the account, or None when it is not connected (or was connected with another client)."""
		with self._lock:
			record = self._load().get(name)
		return record if isinstance(record, dict) and record.get("client_id") == client_id and record.get("refresh_token") else None

	def put(self, name: str, record: dict, keep: set[str]|None = None) -> None:
		"""Store an account's tokens; with `keep`, the tokens of accounts no longer in the settings are dropped."""
		with self._lock:
			data = self._load()
			data[name] = record
			if keep is not None:
				data = { k: v for k, v in data.items() if k in keep or k == name }
			os.makedirs(os.path.dirname(self.path), exist_ok=True)
			_internal_save(self.path, data)

	def remove(self, name: str) -> None:
		with self._lock:
			data = self._load()
			if name in data:
				del data[name]
				_internal_save(self.path, data)

def _record(provider: str, client_id: str, answer: Mapping[str, Any], previous: Mapping[str, Any]|None = None) -> dict:
	"""What is kept of a token answer. A refresh may not send a new refresh token (Google's do not): the old one is kept."""
	refresh = answer.get("refresh_token") or (previous or {}).get("refresh_token")
	expires = answer.get("expires_in")
	return {
		"provider": provider,
		"client_id": client_id,
		"refresh_token": refresh,
		"access_token": answer.get("access_token"),
		"expires_at": time.time() + (expires if isinstance(expires, (int, float)) else 3600),
	}

# ---- the accounts in the settings -----------------------------------------------------------------------------------------------

def find_account(settings: Mapping[str, Any]|None, name: Any) -> dict|None:
	for row in (settings or {}).get("accounts") or []:
		if isinstance(row, dict) and row.get("name") == name and isinstance(name, str):
			return row
	return None

def account_names(settings: Mapping[str, Any]|None) -> set[str]:
	return { row["name"] for row in (settings or {}).get("accounts") or [] if isinstance(row, dict) and isinstance(row.get("name"), str) }

def _check(account: Mapping[str, Any]) -> tuple[str, str]:
	"""The provider and client id of a usable account row (a PermanentError says what to fix)."""
	name = account.get("name")
	provider = account.get("provider")
	client_id = account.get("clientId")
	if provider not in PROVIDERS:
		raise PermanentError(f"The account '{name}' has no provider.")
	if not isinstance(client_id, str) or not client_id:
		raise PermanentError(f"The account '{name}' needs its client id.")
	if provider == "google" and not account.get("clientSecret"):
		raise PermanentError(f"The account '{name}' needs its client secret.")
	if provider == "microsoft" and not TENANT.match(str(account.get("tenant") or "common")):
		raise PermanentError(f"The account '{name}' has a tenant that is not a name.")
	return str(provider), client_id

def _tenant(account: Mapping[str, Any]) -> str:
	return str(account.get("tenant") or "common")

# ---- connecting: the steps the settings page runs ---------------------------------------------------------------------------------

@dataclass
class Session:
	account: str
	provider: str
	client_id: str
	expires: float
	device_code: str|None = None
	interval: int = 5
	verifier: str|None = None
	state: str|None = None
	extra: dict = field(default_factory=dict)

class Sessions:
	"""The sign-ins in progress, by a random id the page holds. In memory: a restart means starting again."""
	def __init__(self):
		self._lock = threading.Lock()
		self._sessions: dict[str, Session] = {}

	def add(self, session: Session) -> str:
		ident = secrets.token_urlsafe(24)
		with self._lock:
			now = time.time()
			self._sessions = { k: v for k, v in self._sessions.items() if v.expires > now }
			self._sessions[ident] = session
		return ident

	def get(self, ident: Any) -> Session:
		with self._lock:
			session = self._sessions.get(ident) if isinstance(ident, str) else None
		if session is None or session.expires < time.time():
			raise AccountError("This sign-in has expired. Start again with Connect.")
		return session

	def end(self, ident: str) -> None:
		with self._lock:
			self._sessions.pop(ident, None)

SESSIONS = Sessions()

def _pkce() -> tuple[str, str]:
	verifier = secrets.token_urlsafe(64)
	challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
	return verifier, challenge

async def _form(client: httpx.AsyncClient, url: str, data: Mapping[str, str]) -> tuple[int, dict]:
	"""POST a form; the status and the JSON answer (empty when it is not JSON)."""
	resp = await client.post(url, data=dict(data), headers={ "Accept": "application/json" })
	try:
		body = resp.json()
	except ValueError:
		body = {}
	return resp.status_code, body if isinstance(body, dict) else {}

async def start(client: httpx.AsyncClient, account: Mapping[str, Any]) -> dict:
	"""
	The first step: what the page shows. `{ session, message, link?, code?, input?, poll? }`: a link to open, a code to type there,
	a box for the address Google sent the browser to, or how often to ask whether the sign-in is done.
	"""
	try:
		provider, client_id = _check(account)
	except PermanentError as problem:
		raise AccountError(str(problem)) from None
	name = str(account.get("name"))
	if provider == "microsoft":
		status, body = await _form(client, f"{MICROSOFT_LOGIN}/{_tenant(account)}/oauth2/v2.0/devicecode", { "client_id": client_id, "scope": MICROSOFT_SCOPE })
		if status != 200 or not body.get("device_code"):
			raise AccountError(f"Microsoft did not start the sign-in ({_code(body, status)}). Check the client id and tenant.")
		interval = int(body.get("interval") or 5)
		session = Session(name, provider, client_id, time.time() + min(SESSION_SECONDS, int(body.get("expires_in") or SESSION_SECONDS)), device_code=str(body["device_code"]), interval=interval, extra={ "tenant": _tenant(account) })
		return {
			"session": SESSIONS.add(session),
			"message": "Open the address, sign in, and enter this code. This page waits for the sign-in.",
			"link": str(body.get("verification_uri") or "https://microsoft.com/devicelogin"),
			"code": str(body.get("user_code") or ""),
			"poll": interval,
		}
	verifier, challenge = _pkce()
	state = secrets.token_urlsafe(16)
	session = Session(name, provider, client_id, time.time() + SESSION_SECONDS, verifier=verifier, state=state)
	query = urlencode({
		"client_id": client_id, "redirect_uri": GOOGLE_REDIRECT, "response_type": "code", "scope": GOOGLE_SCOPE,
		"code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "consent",
	})
	return {
		"session": SESSIONS.add(session),
		"message": "Open the address and sign in. Your browser then goes to a localhost address that does not load: copy that whole address here.",
		"link": f"{GOOGLE_AUTH}?{query}",
		"input": "The address your browser went to",
	}

def _code(body: Mapping[str, Any], status: int) -> str:
	"""A provider's error code (a short fixed word such as invalid_grant), or the status: never its description, which can echo input."""
	code = body.get("error")
	return code if isinstance(code, str) and re.match(r"^[a-z_]{1,40}$", code) else f"status {status}"

async def finish_google(client: httpx.AsyncClient, ident: Any, pasted: Any, account: Mapping[str, Any], store: TokenStore, keep: set[str]) -> dict:
	"""The second Google step: the address the browser was sent to holds the code (and our state); exchange it for tokens."""
	session = SESSIONS.get(ident)
	if session.provider != "google":
		raise AccountError("This sign-in is not a Google one.")
	query = parse_qs(urlsplit(str(pasted or "").strip()).query)
	if query.get("error"):
		SESSIONS.end(ident)
		raise AccountError("Google did not allow the access. Start again with Connect.")
	code = next(iter(query.get("code") or []), None)
	state = next(iter(query.get("state") or []), None)
	if not code:
		raise AccountError("That address has no code in it: copy the whole address from the browser.")
	if state != session.state:
		raise AccountError("That address is from another sign-in. Start again with Connect.")
	status, body = await _form(client, GOOGLE_TOKEN, {
		"grant_type": "authorization_code", "code": code, "client_id": session.client_id, "client_secret": str(account.get("clientSecret") or ""),
		"redirect_uri": GOOGLE_REDIRECT, "code_verifier": str(session.verifier),
	})
	SESSIONS.end(ident)
	if status != 200 or not body.get("refresh_token"):
		raise AccountError(f"Google did not give access ({_code(body, status)}). Start again with Connect.")
	store.put(session.account, _record("google", session.client_id, body), keep)
	return await _connected(client, session.account, "google", str(body.get("access_token")))

async def poll_microsoft(client: httpx.AsyncClient, ident: Any, store: TokenStore, keep: set[str]) -> dict:
	"""One ask of Microsoft whether the sign-in is done: `{ done: false, poll }` while it is not."""
	session = SESSIONS.get(ident)
	if session.provider != "microsoft" or not session.device_code:
		raise AccountError("This sign-in is not a Microsoft one.")
	tenant = session.extra.get("tenant", "common")
	status, body = await _form(client, f"{MICROSOFT_LOGIN}/{tenant}/oauth2/v2.0/token", {
		"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": session.client_id, "device_code": session.device_code,
	})
	error = body.get("error")
	if error == "authorization_pending":
		return { "done": False, "poll": session.interval }
	if error == "slow_down":
		session.interval += 5
		return { "done": False, "poll": session.interval }
	SESSIONS.end(ident)
	if error == "expired_token":
		raise AccountError("The code expired before the sign-in. Start again with Connect.")
	if error in ("authorization_declined", "access_denied"):
		raise AccountError("The sign-in was declined.")
	if status != 200 or not body.get("refresh_token"):
		raise AccountError(f"Microsoft did not give access ({_code(body, status)}). Start again with Connect.")
	store.put(session.account, _record("microsoft", session.client_id, body), keep)
	return await _connected(client, session.account, "microsoft", str(body.get("access_token")))

async def _connected(client: httpx.AsyncClient, account: str, provider: str, token: str) -> dict:
	"""The last answer: done, with the account's calendars named, so the user can fill a row's calendar id."""
	try:
		calendars = await list_calendars(client, provider, token)
	except (httpx.HTTPError, ValueError, KeyError) as ex:
		logger.warning(f"The calendars of '{account}' could not be listed ({type(ex).__name__}).")
		return { "done": True, "ok": True, "message": f"'{account}' is connected." }
	listed = "; ".join(f"{c['name']} ({c['id']})" for c in calendars[:12])
	return { "done": True, "ok": True, "message": f"'{account}' is connected. Its calendars: {listed}" if listed else f"'{account}' is connected.", "calendars": calendars }

# ---- using an account: tokens, and reading its calendars ------------------------------------------------------------------------

async def access_token(client: httpx.AsyncClient, account: Mapping[str, Any], store: TokenStore) -> str:
	"""A current access token for the account, refreshed when it is about to end. Not connected, or a refused refresh, is permanent."""
	provider, client_id = _check(account)
	name = str(account.get("name"))
	record = store.get(name, client_id)
	if record is None:
		raise PermanentError(f"The account '{name}' is not connected: use Connect in the Calendar settings.")
	if record.get("access_token") and float(record.get("expires_at") or 0) - EARLY_SECONDS > time.time():
		return str(record["access_token"])
	if provider == "google":
		url = GOOGLE_TOKEN
		data = { "grant_type": "refresh_token", "refresh_token": str(record["refresh_token"]), "client_id": client_id, "client_secret": str(account.get("clientSecret") or "") }
	else:
		url = f"{MICROSOFT_LOGIN}/{_tenant(account)}/oauth2/v2.0/token"
		data = { "grant_type": "refresh_token", "refresh_token": str(record["refresh_token"]), "client_id": client_id, "scope": MICROSOFT_SCOPE }
	status, body = await _form(client, url, data)
	if status == 200 and body.get("access_token"):
		# Microsoft sends a new refresh token each time: keep it
		store.put(name, _record(provider, client_id, body, record))
		return str(body["access_token"])
	if body.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client", "interaction_required"):
		raise PermanentError(f"Sign in to the account '{name}' again: use Connect in the Calendar settings.")
	raise RuntimeError(f"The account '{name}' could not be refreshed ({_code(body, status)}).")

async def _get_json(client: httpx.AsyncClient, url: str, token: str, params: Mapping[str, str]|None = None, headers: Mapping[str, str]|None = None) -> dict:
	resp = await client.get(url, params=params, headers={ "Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {}) })
	resp.raise_for_status()
	body = resp.json()
	if not isinstance(body, dict):
		raise ValueError("not an object")
	return body

async def list_calendars(client: httpx.AsyncClient, provider: str, token: str) -> list[dict]:
	"""The account's calendars, `{ name, id }`."""
	if provider == "google":
		body = await _get_json(client, f"{GOOGLE_API}/users/me/calendarList", token)
		return [{ "name": _text(c.get("summary")), "id": str(c.get("id")) } for c in body.get("items") or [] if isinstance(c, dict) and c.get("id")]
	body = await _get_json(client, f"{GRAPH}/me/calendars", token)
	return [{ "name": _text(c.get("name")), "id": str(c.get("id")) } for c in body.get("value") or [] if isinstance(c, dict) and c.get("id")]

def _rfc3339(when: datetime) -> str:
	return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _all_day(start: date, end: date, zone: tzinfo, title: str, location: str, calendar: str, color: str|None) -> Event:
	first = datetime.combine(start, datetime.min.time(), zone)
	last = datetime.combine(end, datetime.min.time(), zone)
	return Event(first, last if last > first else first + timedelta(days=1), True, title, location, calendar, color)

async def read_google(client: httpx.AsyncClient, token: str, calendar_id: str|None, start: datetime, end: datetime, zone: tzinfo, name: str, color: str|None) -> list[Event]:
	"""Google Calendar's `events.list` with recurrences expanded by Google (`singleEvents`), page by page."""
	url = f"{GOOGLE_API}/calendars/{quote(calendar_id or 'primary', safe='')}/events"
	params = { "singleEvents": "true", "orderBy": "startTime", "timeMin": _rfc3339(start), "timeMax": _rfc3339(end), "maxResults": "250" }
	found: list[Event] = []
	for _ in range(MAX_PAGES):
		body = await _get_json(client, url, token, params)
		for item in body.get("items") or []:
			if not isinstance(item, dict) or item.get("status") == "cancelled":
				continue
			title, location = _text(item.get("summary")) or "(untitled)", _text(item.get("location"))
			s, e = item.get("start") or {}, item.get("end") or {}
			if s.get("date"):
				found.append(_all_day(date.fromisoformat(s["date"]), date.fromisoformat(e.get("date") or s["date"]), zone, title, location, name, color))
			elif s.get("dateTime"):
				first = datetime.fromisoformat(s["dateTime"]).astimezone(zone)
				last = datetime.fromisoformat(e.get("dateTime") or s["dateTime"]).astimezone(zone)
				found.append(Event(first, max(first, last), False, title, location, name, color))
		next_page = body.get("nextPageToken")
		if not next_page:
			break
		params = { **params, "pageToken": str(next_page) }
	return found

def _graph_time(value: Mapping[str, Any]) -> datetime:
	"""A Graph `dateTimeTimeZone` asked for in UTC (`Prefer: outlook.timezone="UTC"`): seven decimals and no offset."""
	text = str(value.get("dateTime") or "")
	main, _, fraction = text.partition(".")
	return datetime.fromisoformat(main + (f".{fraction[:6]}" if fraction else "")).replace(tzinfo=timezone.utc)

async def read_microsoft(client: httpx.AsyncClient, token: str, calendar_id: str|None, start: datetime, end: datetime, zone: tzinfo, name: str, color: str|None) -> list[Event]:
	"""Graph's `calendarView` (recurrences expanded by Graph), page by page; an empty calendar id is the default calendar."""
	base = f"{GRAPH}/me/calendars/{quote(calendar_id, safe='')}/calendarView" if calendar_id else f"{GRAPH}/me/calendarView"
	url: str|None = base
	params: dict[str, str]|None = { "startDateTime": _rfc3339(start), "endDateTime": _rfc3339(end), "$top": "200",
		"$select": "subject,start,end,isAllDay,isCancelled,location" }
	found: list[Event] = []
	for _ in range(MAX_PAGES):
		if url is None:
			break
		body = await _get_json(client, url, token, params, { "Prefer": 'outlook.timezone="UTC"' })
		for item in body.get("value") or []:
			if not isinstance(item, dict) or item.get("isCancelled") is True:
				continue
			title = _text(item.get("subject")) or "(untitled)"
			location = _text((item.get("location") or {}).get("displayName"))
			first, last = _graph_time(item.get("start") or {}), _graph_time(item.get("end") or {})
			if item.get("isAllDay") is True:
				# an all-day event's midnights are the calendar's own days: read them as days, not as UTC instants
				found.append(_all_day(first.date(), last.date(), zone, title, location, name, color))
			else:
				first, last = first.astimezone(zone), last.astimezone(zone)
				found.append(Event(first, max(first, last), False, title, location, name, color))
		# the next page's address carries its own query
		next_link = body.get("@odata.nextLink")
		url, params = (str(next_link), None) if isinstance(next_link, str) and next_link.startswith(GRAPH + "/") else (None, None)
	return found

async def read_account_calendar(client: httpx.AsyncClient, entry: Mapping[str, Any], settings: Mapping[str, Any], store: TokenStore,
		start: datetime, end: datetime, zone: tzinfo) -> list[Event]:
	"""A calendar row of a Google or Microsoft account: its account must be in the settings, of the same provider, and connected."""
	name = str(entry.get("name"))
	account = find_account(settings, entry.get("account"))
	if account is None:
		raise PermanentError(f"The calendar '{name}' names no account in the Calendar settings.")
	if account.get("provider") != entry.get("source"):
		raise PermanentError(f"The calendar '{name}' is {entry.get('source')}, but its account '{account.get('name')}' is {account.get('provider')}.")
	token = await access_token(client, account, store)
	calendar_id = entry.get("calendarId") or None
	reader = read_google if entry.get("source") == "google" else read_microsoft
	return await reader(client, token, calendar_id, start, end, zone, name, safe_color(entry.get("color")))
