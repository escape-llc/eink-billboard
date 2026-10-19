"""
The sealed archive of a backup (#368): a ZIP of the storage's files, encrypted with a passphrase of its own. It holds API keys, so there is no other kind: no plain archive and no masked one.

The file is one blob, so even the names inside are hidden: a header (the magic, the scrypt cost, a random salt, a random nonce), then the ZIP encrypted with AES-256-GCM under a key made
from the passphrase with scrypt. The header is authenticated with the ciphertext, so a changed cost or salt fails like a changed byte. The passphrase is not the device password (a reset
would make the backup unreadable); it is never stored, logged or put in a file: everything here happens in memory.

This module knows archives and not the storage: it takes and gives `{name: bytes}`. Which names may be in a backup, and what a restore does with them, is `ConfigurationManager`'s (it is the
only code that touches the storage root) and `python/web/backup.py`'s. What an archive is allowed to *be* is checked here, before anything is looked at: how large, how many members, no
absolute or `..` names, no links, no duplicates, and the sizes counted as the bytes come out, never believed from the ZIP's own header (a ZIP bomb says it is small).
"""
import hashlib
import io
import os
import stat
import zipfile
import zlib
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"EINKBKP1"
# the only cost this version writes and reads: a header that asks for more would make the device allocate what the sender chose
SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P = 15, 8, 1
SALT_BYTES, NONCE_BYTES = 16, 12
HEADER_BYTES = len(MAGIC) + 3 + SALT_BYTES + NONCE_BYTES
# scrypt wants 128 * N * r bytes (32 MiB here) and OpenSSL's default ceiling is exactly 32 MiB
SCRYPT_MAX_MEMORY = 96 * 1024 * 1024

MIN_PASSPHRASE = 12
MAX_PASSPHRASE = 256
# the whole file (a storage is a few hundred kilobytes), the members and what they unpack to
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 500
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024

# one message for a wrong passphrase and for a file that was changed: the difference is for an attacker to learn
NOT_OPENED = "That is not the right passphrase, or the file is damaged."
NOT_A_BACKUP = "That file is not an eInk Billboard backup."

class BackupError(Exception):
	"""Our own words for a person (never an exception's text, never a name from the archive): the message is safe to send."""
	def __init__(self, message: str):
		super().__init__(message)
		self.message = message

def _encodable(passphrase: str) -> bool:
	"""JSON can carry a lone surrogate (an escaped half of a UTF-16 pair) that is no text: it cannot be turned into the bytes the key is made from."""
	try:
		passphrase.encode("utf-8")
		return True
	except UnicodeEncodeError:
		return False

def passphrase_problem(passphrase: Any) -> str|None:
	"""Why this cannot be a backup passphrase, in words that are safe to show; None when it can."""
	if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE:
		return f"The passphrase needs at least {MIN_PASSPHRASE} characters."
	if len(passphrase) > MAX_PASSPHRASE:
		return f"The passphrase can have at most {MAX_PASSPHRASE} characters."
	if not _encodable(passphrase):
		return "The passphrase has a character that is not text."
	return None

def _key(passphrase: str, salt: bytes) -> bytes:
	return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** SCRYPT_LOG2_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=SCRYPT_MAX_MEMORY)

def unsafe_name(name: str) -> bool:
	"""A member name that could leave the storage (or is not a name at all): absolute, a drive, a backslash, an empty part, `.` or `..`, a control character."""
	if not name or len(name) > 255 or name.startswith("/") or "\\" in name or ":" in name or any(ord(c) < 32 for c in name):
		return True
	return any(part in ("", ".", "..") for part in name.split("/"))

def _zip(files: Mapping[str, bytes]) -> bytes:
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		for name in sorted(files):
			if unsafe_name(name):
				raise ValueError("a file name is not safe")
			# a fixed time: the archive says nothing about when each file changed, and the same files make the same ZIP
			info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
			info.compress_type = zipfile.ZIP_DEFLATED
			archive.writestr(info, files[name])
	return buffer.getvalue()

def seal(files: Mapping[str, bytes], passphrase: str) -> bytes:
	"""The files as one encrypted blob. Raises `BackupError` for a passphrase that is not allowed or files that are over the limits."""
	problem = passphrase_problem(passphrase)
	if problem:
		raise BackupError(problem)
	if len(files) > MAX_MEMBERS or sum(len(content) for content in files.values()) > MAX_TOTAL_BYTES or any(len(content) > MAX_MEMBER_BYTES for content in files.values()):
		raise BackupError("The storage is too large to back up.")
	plain = _zip(files)
	salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
	header = MAGIC + bytes((SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P)) + salt + nonce
	blob = header + AESGCM(_key(passphrase, salt)).encrypt(nonce, plain, header)
	if len(blob) > MAX_ARCHIVE_BYTES:
		raise BackupError("The storage is too large to back up.")
	return blob

def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, room: int) -> bytes:
	"""One member's bytes, counted as they come out: more than the member limit, or than the total has room for, is refused."""
	limit = min(MAX_MEMBER_BYTES, room)
	try:
		with archive.open(info) as member:
			content = member.read(limit + 1)
	except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
		# a member that does not unpack (a bad checksum, a method we do not read): damaged before it was sealed
		raise BackupError(NOT_OPENED) from None
	if len(content) > limit:
		raise BackupError("That backup holds more than a backup of this device can.")
	return content

def unseal(blob: bytes, passphrase: Any) -> dict[str, bytes]:
	"""
	The files of a sealed archive. Raises `BackupError`: not a backup, the passphrase is not right or the file was changed (one message for both), or over the limits. Nothing in the
	archive is trusted: the names are only checked for safety here; whether the storage may have such a file is for the restore to decide.
	"""
	if not isinstance(blob, (bytes, bytearray)) or len(blob) > MAX_ARCHIVE_BYTES:
		raise BackupError("That file is larger than a backup of this device can be.")
	if len(blob) < HEADER_BYTES + 16 or not blob.startswith(MAGIC):
		raise BackupError(NOT_A_BACKUP)
	if not isinstance(passphrase, str) or not 0 < len(passphrase) <= MAX_PASSPHRASE or not _encodable(passphrase):
		raise BackupError(NOT_OPENED)
	header = bytes(blob[:HEADER_BYTES])
	if tuple(header[len(MAGIC):len(MAGIC) + 3]) != (SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P):
		raise BackupError("That backup was made with settings this version does not read.")
	salt = header[len(MAGIC) + 3:len(MAGIC) + 3 + SALT_BYTES]
	nonce = header[-NONCE_BYTES:]
	try:
		plain = AESGCM(_key(passphrase, salt)).decrypt(nonce, bytes(blob[HEADER_BYTES:]), header)
	except InvalidTag:
		raise BackupError(NOT_OPENED) from None
	try:
		archive = zipfile.ZipFile(io.BytesIO(plain))
	except zipfile.BadZipFile:
		# it decrypted (so it is ours) and is not a ZIP: damaged before it was sealed
		raise BackupError(NOT_OPENED) from None
	files: dict[str, bytes] = {}
	total = 0
	with archive:
		infos = archive.infolist()
		if len(infos) > MAX_MEMBERS:
			raise BackupError("That backup holds more files than a backup of this device can.")
		for info in infos:
			mode = info.external_attr >> 16
			# a ZIP made by most tools carries permission bits and no file type (0): that is a file; a link, a device or a folder says what it is
			if info.is_dir() or info.flag_bits & 0x1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
				raise BackupError("That backup holds something that is not a file.")
			if unsafe_name(info.filename):
				raise BackupError("That backup holds a file name that is not allowed.")
			if info.filename in files:
				raise BackupError("That backup holds a file twice.")
			content = _read_member(archive, info, MAX_TOTAL_BYTES - total)
			total += len(content)
			files[info.filename] = content
	return files
