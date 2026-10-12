"""
Who may use the device: the device password, the setup code that claims a new device, and when authentication is required at all.

- There is **no default credential**. A device that listens on the network starts *unclaimed*; it prints a one-time **setup code** in its log (and
  `Application` draws it on the panel), and whoever enters that code chooses the device password. Seeing the log or the panel proves they are the owner.
- A device bound to this machine only (`--host localhost`) works open, as before, until a password is set; then the password is required too.
- `--token` / `EINK_API_TOKEN` stays the credential for scripts (and counts as "claimed"); `--no-auth` keeps the device open (a trusted network, on purpose).
  `--require-auth` applies the rules on a local bind too (the browser tests).
- The password is kept as a salted scrypt hash in the `access` settings, which no route serves (it is not in `DEVICE_SETTINGS`).
"""
import hashlib
import hmac
import logging
import os
import secrets
import threading
from typing import Any, Callable

from ..model.configuration_manager import ConfigurationManager

logger = logging.getLogger(__name__)

SETTINGS = "access"
SETUP_CODE_ENV = "EINK_SETUP_CODE"
MIN_PASSWORD = 8
MAX_PASSWORD = 256
WRONG_CODES = 5
_SCRYPT = { "n": 2 ** 14, "r": 8, "p": 1 }

def hash_password(password: str) -> dict:
	"""A record to store: the parameters, a random salt and the scrypt hash, as text."""
	salt = os.urandom(16)
	digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
	return { "algo": "scrypt", **_SCRYPT, "salt": salt.hex(), "hash": digest.hex() }

def verify_password(password: Any, record: Any) -> bool:
	"""True when `password` is the one `record` was made from. Anything that is not a record, or not text, is simply no."""
	if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD or not isinstance(record, dict):
		return False
	try:
		if record.get("algo") != "scrypt":
			return False
		params = { k: int(record[k]) for k in ("n", "r", "p") }
		digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(record["salt"]), dklen=32, **params)
		return hmac.compare_digest(digest, bytes.fromhex(record["hash"]))
	except (KeyError, TypeError, ValueError):
		return False

def password_problem(password: Any) -> str|None:
	"""Why this cannot be the device password, in words that are safe to show; None when it can."""
	if not isinstance(password, str) or len(password) < MIN_PASSWORD:
		return f"The password needs at least {MIN_PASSWORD} characters."
	if len(password) > MAX_PASSWORD:
		return f"The password can have at most {MAX_PASSWORD} characters."
	return None

def _new_code() -> str:
	forced = os.environ.get(SETUP_CODE_ENV)
	if forced:
		return forced
	digits = f"{secrets.randbelow(10 ** 8):08d}"
	return f"{digits[:4]} {digits[4:]}"

def _plain(code: str) -> str:
	return "".join(code.split())

class AccessState:
	"""The rules of the sign-in for one server, read fresh from the stored settings."""
	def __init__(self, mode: str, local: bool, api_token: str|None, manager: Callable[[], ConfigurationManager|None]):
		# mode: "auto" (the rules above), "none" (--no-auth) or "always" (--require-auth)
		self.mode = mode
		self.local = local
		self.api_token = api_token
		self._manager = manager
		self._lock = threading.Lock()
		self._code: str|None = None
		self._wrong = 0

	def _cob(self):
		cm = self._manager()
		return cm.settings_manager().open(SETTINGS) if cm is not None else None

	def _document(self) -> tuple[str|None, dict]:
		cob = self._cob()
		if cob is None:
			return None, {}
		rev, document = cob.get()
		return rev, document or {}

	def password_set(self) -> bool:
		return isinstance(self._document()[1].get("passwordHash"), dict)

	def claimed(self) -> bool:
		return bool(self.api_token) or self.password_set()

	def required(self) -> bool:
		if self.mode == "none":
			return False
		return self.mode == "always" or not self.local or bool(self.api_token) or self.password_set()

	def setup_open(self) -> bool:
		"""A new device that must be claimed before anything else can be used."""
		return self.required() and not self.claimed()

	def verify(self, password: Any) -> bool:
		return verify_password(password, self._document()[1].get("passwordHash"))

	def set_password(self, password: str) -> None:
		"""Store the password (the caller checked who may), and forget the setup code."""
		cob = self._cob()
		if cob is None:
			raise RuntimeError("Settings are not available.")
		for _ in range(3):
			rev, document = self._document()
			committed, _ = cob.save(rev, { **document, "passwordHash": hash_password(password) })
			if committed:
				with self._lock:
					self._code = None
					self._wrong = 0
				return
		raise RuntimeError("The password could not be saved.")

	# ---- the setup code ----
	def setup_code(self) -> str|None:
		"""The code that claims this device (made on first use, and again after too many wrong ones); None when nothing needs claiming."""
		if not self.setup_open():
			return None
		with self._lock:
			if self._code is None:
				self._code = _new_code()
			return self._code

	def check_code(self, given: Any) -> bool:
		"""True for the right code. Wrong ones are counted; after a few the code is replaced (and logged, as at start)."""
		code = self.setup_code()
		if code is None or not isinstance(given, str):
			return False
		if hmac.compare_digest(_plain(given).encode(), _plain(code).encode()):
			return True
		with self._lock:
			self._wrong += 1
			if self._wrong >= WRONG_CODES:
				self._wrong = 0
				self._code = _new_code()
				logger.warning(f"Too many wrong setup codes: the new setup code is {self._code}")
		return False

def clear_password(cm: ConfigurationManager) -> bool:
	"""`--reset-password`: forget the stored password, so a network device is unclaimed again. True when there was one."""
	cob = cm.settings_manager().open(SETTINGS)
	rev, document = cob.get()
	if not document or "passwordHash" not in document:
		return False
	committed, _ = cob.save(rev, { k: v for k, v in document.items() if k != "passwordHash" })
	return committed
