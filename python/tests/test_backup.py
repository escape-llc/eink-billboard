"""
Backup and restore of the storage (#368): the sealed archive, what a backup may hold, the routes, and the Application's rules that keep the notifications of a restore to one.
"""
import base64
import io
import json
import os
import threading
import time
import unittest
import zipfile
from concurrent.futures import Future
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..model import configuration_manager as cmod
from ..model.configuration_manager import BACKUP_AREAS, RestoreFailed, backup_file
from ..task.application import Application
from ..task.message_router import MessageRouter
from ..task.messages import ConfigurationChanged, ConfigurationWatcherEvent, RestoreBegin, RestoreEnd, RestoreSettled
from ..utils import backup_archive
from ..utils.backup_archive import HEADER_BYTES, MAGIC, NOT_OPENED, BackupError, passphrase_problem, seal, unseal
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

PASSPHRASE = "correct horse battery"
NOW = datetime(2026, 1, 1, 12, 0).astimezone()
KEY = "SECRET-KEY-0123456789"

def put(cob: Any, document: dict) -> None:
	"""Store a document whether or not there is one (a save needs the revision it replaces)."""
	rev, _ = cob.get()
	committed, _ = cob.save(rev, document)
	assert committed

def encrypted(plain: bytes, passphrase: str = PASSPHRASE) -> bytes:
	"""A sealed archive around any bytes, for the ones `seal` would never make."""
	salt, nonce = os.urandom(backup_archive.SALT_BYTES), os.urandom(backup_archive.NONCE_BYTES)
	header = MAGIC + bytes((backup_archive.SCRYPT_LOG2_N, backup_archive.SCRYPT_R, backup_archive.SCRYPT_P)) + salt + nonce
	return header + AESGCM(backup_archive._key(passphrase, salt)).encrypt(nonce, plain, header)

def sealed_zip(entries: dict[str, bytes], passphrase: str = PASSPHRASE, *, raw_infos: list[zipfile.ZipInfo]|None = None) -> bytes:
	"""A sealed archive made by hand, for the archives `seal` would never make (a bad name, a link, too much)."""
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		for info in raw_infos or []:
			archive.writestr(info, b"x")
		for name, content in entries.items():
			archive.writestr(name, content)
	return encrypted(buffer.getvalue(), passphrase)

class TestSealedArchive(unittest.TestCase):
	files = { "settings/system-settings.json": b'{"timeFormat": "24h"}', "plugins/slide-show/state.json": b"{}" }

	def test_what_is_sealed_opens_with_the_passphrase_and_is_the_same(self):
		self.assertEqual(unseal(seal(self.files, PASSPHRASE), PASSPHRASE), self.files)

	def test_nothing_in_the_file_can_be_read_without_the_passphrase(self):
		blob = seal(self.files, PASSPHRASE)
		for hidden in (b"system-settings", b"slide-show", b"timeFormat", b"PK"):
			self.assertNotIn(hidden, blob)
		self.assertTrue(blob.startswith(MAGIC))

	def test_two_backups_of_the_same_files_differ(self):
		self.assertNotEqual(seal(self.files, PASSPHRASE), seal(self.files, PASSPHRASE))

	def test_a_wrong_passphrase_and_a_damaged_file_say_the_same(self):
		blob = seal(self.files, PASSPHRASE)
		with self.assertRaises(BackupError) as wrong:
			unseal(blob, "another passphrase")
		damaged = bytearray(blob)
		damaged[-5] ^= 1
		with self.assertRaises(BackupError) as hurt:
			unseal(bytes(damaged), PASSPHRASE)
		header = bytearray(blob)
		header[len(MAGIC) + 3] ^= 1   # the salt is authenticated too
		with self.assertRaises(BackupError) as salted:
			unseal(bytes(header), PASSPHRASE)
		self.assertEqual({wrong.exception.message, hurt.exception.message, salted.exception.message}, {NOT_OPENED})

	def test_what_is_not_a_backup_is_said_so(self):
		for data in (b"", b"hello world" * 20, b"PK\x03\x04" + b"0" * 100):
			with self.assertRaises(BackupError) as e:
				unseal(data, PASSPHRASE)
			self.assertIn("not an eInk Billboard backup", e.exception.message)

	def test_a_header_that_asks_for_another_cost_is_refused_before_any_work(self):
		blob = bytearray(seal(self.files, PASSPHRASE))
		blob[len(MAGIC)] = 24   # scrypt N of 2**24: 2 GB
		with patch.object(backup_archive, "_key", side_effect=AssertionError("derived")):
			with self.assertRaises(BackupError):
				unseal(bytes(blob), PASSPHRASE)

	def test_a_passphrase_needs_twelve_characters(self):
		self.assertIsNotNone(passphrase_problem("short"))
		self.assertIsNotNone(passphrase_problem(None))
		self.assertIsNone(passphrase_problem("a" * 12))
		with self.assertRaises(BackupError):
			seal(self.files, "short")

	def test_a_passphrase_that_is_not_text_is_refused_not_a_crash(self):
		# JSON allows a lone surrogate; encoding it would raise
		lone = chr(0xD800) * 12
		self.assertIsNotNone(passphrase_problem(lone))
		with self.assertRaises(BackupError):
			seal(self.files, lone)
		with self.assertRaises(BackupError) as e:
			unseal(seal(self.files, PASSPHRASE), lone)
		self.assertEqual(e.exception.message, NOT_OPENED)

	def test_a_name_that_could_leave_the_storage_is_refused(self):
		for name in ("/etc/passwd", "../settings/x.json", "settings/../../x.json", "C:/x.json", "settings//x.json", "./x.json", ""):
			with self.subTest(name):
				with self.assertRaises(BackupError) as e:
					unseal(sealed_zip({ name or " ": b"{}" }) if name else sealed_zip({}, raw_infos=[zipfile.ZipInfo("")]), PASSPHRASE)
				self.assertIn("not allowed", e.exception.message)

	def test_a_backslash_is_not_a_separator(self):
		# (Python's own zipfile turns it into a slash on Windows, so this is the check itself)
		self.assertTrue(backup_archive.unsafe_name("settings" + chr(92) + "x.json"))

	def test_a_link_and_a_folder_are_refused(self):
		link = zipfile.ZipInfo("settings/link.json")
		link.external_attr = (0o120777 << 16)
		with self.assertRaisesRegex(BackupError, "not a file"):
			unseal(sealed_zip({}, raw_infos=[link]), PASSPHRASE)
		with self.assertRaisesRegex(BackupError, "not a file"):
			unseal(sealed_zip({}, raw_infos=[zipfile.ZipInfo("settings/")]), PASSPHRASE)

	def test_a_file_twice_is_refused(self):
		duplicate = zipfile.ZipInfo("settings/a.json")
		with self.assertWarns(UserWarning):
			with self.assertRaisesRegex(BackupError, "twice"):
				unseal(sealed_zip({ "settings/a.json": b"{}" }, raw_infos=[duplicate]), PASSPHRASE)

	def test_a_zip_bomb_is_stopped_by_counting_what_comes_out(self):
		# a few hundred bytes that would be a megabyte: the header says what it likes, the bytes are counted
		bomb = sealed_zip({ "settings/a.json": b"0" * (1024 * 1024) })
		with patch.object(backup_archive, "MAX_MEMBER_BYTES", 1000):
			with self.assertRaisesRegex(BackupError, "more than"):
				unseal(bomb, PASSPHRASE)
		many = sealed_zip({ f"settings/f{i}.json": b"0" * 600 for i in range(5) })
		with patch.object(backup_archive, "MAX_TOTAL_BYTES", 2000):
			with self.assertRaisesRegex(BackupError, "more than"):
				unseal(many, PASSPHRASE)

	def test_too_many_files_are_refused(self):
		with patch.object(backup_archive, "MAX_MEMBERS", 3):
			with self.assertRaisesRegex(BackupError, "more files"):
				unseal(sealed_zip({ f"settings/f{i}.json": b"{}" for i in range(4) }), PASSPHRASE)

	def test_a_file_larger_than_a_backup_can_be_is_refused_unread(self):
		with self.assertRaisesRegex(BackupError, "larger"):
			unseal(MAGIC + b"0" * backup_archive.MAX_ARCHIVE_BYTES, PASSPHRASE)

	def test_a_damaged_member_is_the_damaged_file_message(self):
		buffer = io.BytesIO()
		with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
			archive.writestr("settings/a.json", b'{"a": 1}' * 50)
		raw = bytearray(buffer.getvalue())
		raw[60] ^= 0xFF
		damaged = encrypted(bytes(raw))
		self.assertGreater(len(damaged), HEADER_BYTES)
		with self.assertRaises(BackupError) as e:
			unseal(damaged, PASSPHRASE)
		self.assertEqual(e.exception.message, NOT_OPENED)

class TestWhatABackupHolds(unittest.TestCase):
	def test_the_names_a_backup_may_hold(self):
		for name in ("settings/system-settings.json", "schedules/playlist-0123.json", "plugins/slide-show/state.json", "plugins/slide-show/list-abc123.json", "datasources/calendar-sources/tokens.json", "datasources/rss/settings.json"):
			with self.subTest(name):
				self.assertIsNotNone(backup_file(name))

	def test_the_device_password_the_schemas_the_state_and_the_caches_are_never_in_it(self):
		for name in ("settings/access-settings.json", "schemas/system.json", "state/refresh.json", "datasources/openweathermap-api/cache-0123abcd.json", "datasources/comicvine-api/cache-x.json"):
			with self.subTest(name):
				self.assertIsNone(backup_file(name))

	def test_what_is_not_a_plain_name_is_refused(self):
		for name in ("settings/x.txt", "settings/.tmp-1.json", "settings/a/b.json", "plugins/x.json", "plugins/../x/y.json", "plugins/a b/y.json", "other/x.json", "settings", "", None, 5):
			with self.subTest(name):
				self.assertIsNone(backup_file(name))

class TestStorageSide(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		put(self.cm.datasource_manager("openweathermap-api").open(), { "apiKey": KEY })
		# what must stay out
		put(self.cm.state_file("refresh"), { "last": 1 })
		put(self.cm.datasource_manager("openweathermap-api").file("cache-0123abcd"), { "answer": 1 })
		put(self.cm.plugin_manager("slide-show").file("list-aaaa"), { "left": ["a"] })

	def test_a_backup_has_the_settings_and_the_files_of_plugins_and_data_sources_and_not_the_rest(self):
		files = self.cm.backup_files()
		names = set(files)
		self.assertIn("settings/system-settings.json", names)
		self.assertIn("datasources/openweathermap-api/settings.json", names)
		self.assertIn("plugins/slide-show/list-aaaa.json", names)
		self.assertFalse({n for n in names if n.startswith(("schemas/", "state/")) or "/cache-" in n or n == "settings/access-settings.json"}, names)
		self.assertTrue(all(n.split("/")[0] in BACKUP_AREAS for n in names))
		self.assertIn(KEY.encode(), files["datasources/openweathermap-api/settings.json"])

	def test_the_device_password_is_never_in_it(self):
		put(self.cm.settings_manager().open("access"), { "passwordHash": { "algo": "scrypt", "salt": "00", "hash": "SECRETHASH" } })
		blob = b"".join(self.cm.backup_files().values())
		self.assertNotIn(b"SECRETHASH", blob)
		self.assertNotIn(b"passwordHash", blob)

	def test_a_file_that_is_damaged_is_left_out_not_fatal(self):
		path = self.cm.settings_manager().settings_path("theme")
		with open(path, "w") as f:
			f.write("{ not json")
		self.cm.evict_all()
		self.assertNotIn("settings/theme-settings.json", self.cm.backup_files())

	def test_a_restore_writes_by_name_and_nothing_is_deleted(self):
		documents = { "settings/theme-settings.json": { "scheme": "monochrome" }, "datasources/openweathermap-api/settings.json": { "apiKey": "other" } }
		extra = self.cm.plugin_manager("slide-show").file("list-aaaa")
		written = self.cm.write_backup(documents)
		self.assertEqual(sorted(written), sorted(documents))
		self.assertEqual(self.cm.settings_manager().open("theme").get()[1], { "scheme": "monochrome" })
		self.assertEqual(self.cm.datasource_manager("openweathermap-api").open().get()[1]["apiKey"], "other")
		self.assertEqual(extra.get()[1], { "left": ["a"] })

	def test_a_name_with_no_place_here_is_not_written(self):
		self.assertEqual(self.cm.write_backup({ "plugins/not-installed/settings.json": { "a": 1 } }), [])
		self.assertFalse(os.path.exists(os.path.join(self.cm.storage_plugins, "not-installed")))

	def test_a_failed_write_puts_back_what_was_written_and_removes_what_is_new(self):
		before_theme = self.cm.settings_manager().open("theme").get()[1]
		real = cmod._internal_save
		calls = []
		def failing(path, data):
			calls.append(path)
			if len(calls) == 3:
				raise OSError("disk full")
			return real(path, data)
		documents = { "settings/theme-settings.json": { "scheme": "changed" }, "plugins/slide-show/list-new1.json": { "left": [] }, "datasources/rss/settings.json": { "feeds": [] } }
		with patch.object(cmod, "_internal_save", failing):
			with self.assertRaises(RestoreFailed) as e:
				self.cm.write_backup(documents)
		self.assertEqual(e.exception.name, "datasources/rss/settings.json")
		self.cm.evict_all()
		self.assertEqual(self.cm.settings_manager().open("theme").get()[1], before_theme)
		self.assertIsNone(self.cm.plugin_manager("slide-show").file("list-new1").get()[1])

class StubApplication:
	"""What the routes need of the Application, recording how they use it."""
	def __init__(self, claimed: bool = True, refuse: str|None = None):
		self.playlist_layer = object()
		self._claimed, self.refuse = claimed, refuse
		self.calls: list[tuple] = []
	def claimed(self) -> bool:
		return self._claimed
	def begin_restore(self):
		self.calls.append(("begin",))
		return self.refuse
	def end_restore(self, ok, count):
		self.calls.append(("end", ok, count))

class BackupApiBase(WebApiTestBase):
	# the Application is a stub that says whether the device is claimed; the sign-in is not what these tests are about (a stored password would turn it on)
	auth = "none"

	def setUp(self):
		super().setUp()
		self.application = StubApplication()
		self.app.state.root_container.add_service(Application, self.application)
		put(self.cm.datasource_manager("openweathermap-api").open(), { "apiKey": KEY })

	def backup(self, passphrase: str = PASSPHRASE, confirm: str|None = None):
		return self.client.post("/api/backup", json={ "passphrase": passphrase, "confirm": passphrase if confirm is None else confirm })

	def restore(self, blob: bytes, passphrase: str = PASSPHRASE, apply: bool = False):
		return self.client.post("/api/restore", json={ "archive": base64.b64encode(blob).decode(), "passphrase": passphrase, "apply": apply })

class TestBackupRoutes(BackupApiBase):
	def test_a_backup_is_an_encrypted_file_that_never_holds_a_key_in_the_clear(self):
		resp = self.backup()
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(resp.headers["content-type"], "application/octet-stream")
		self.assertEqual(resp.headers["cache-control"], "no-store")
		self.assertIn("attachment", resp.headers["content-disposition"])
		self.assertTrue(resp.content.startswith(MAGIC))
		self.assertNotIn(KEY.encode(), resp.content)
		self.assertNotIn(b"openweathermap-api", resp.content)
		# and it does hold the key, for whoever has the passphrase
		self.assertIn(KEY.encode(), unseal(resp.content, PASSPHRASE)["datasources/openweathermap-api/settings.json"])

	def test_the_passphrase_must_be_long_enough_and_typed_twice(self):
		for body in ({}, { "passphrase": "short", "confirm": "short" }, { "passphrase": PASSPHRASE, "confirm": "something else entirely" }, { "passphrase": 5, "confirm": 5 }):
			with self.subTest(body):
				resp = self.client.post("/api/backup", json=body)
				self.assertEqual(resp.status_code, 422)
				self.assertFalse(resp.json()["success"])

	def test_an_unclaimed_device_makes_and_restores_nothing(self):
		self.application._claimed = False
		self.assertEqual(self.backup().status_code, 403)
		self.assertEqual(self.restore(b"x").status_code, 403)
		self.assertEqual(self.application.calls, [])

	def test_a_request_that_is_not_json_or_is_too_large_is_refused(self):
		self.assertEqual(self.client.post("/api/backup", content=b"not json", headers={ "Content-Type": "application/json" }).status_code, 400)
		with patch("python.web.routers.backup.MAX_BODY_BYTES", 100):
			resp = self.client.post("/api/restore", json={ "archive": "A" * 500 })
		self.assertEqual(resp.status_code, 413)

class TestRestoreRoutes(BackupApiBase):
	def make(self) -> bytes:
		return self.backup().content

	def change_key(self, value: str):
		cob = self.cm.datasource_manager("openweathermap-api").open()
		rev, doc = cob.get()
		cob.save(rev, { **(doc or {}), "apiKey": value })

	def test_the_preview_says_what_would_change_by_name_and_changes_nothing(self):
		blob = self.make()
		self.change_key("changed-by-hand")
		resp = self.restore(blob)
		self.assertEqual(resp.status_code, 200, resp.text)
		body = resp.json()
		self.assertFalse(body["applied"])
		self.assertEqual([(f["name"], f["status"]) for f in body["files"]], [("datasources/openweathermap-api/settings.json", "changed")])
		self.assertGreater(body["unchanged"], 0)
		self.assertNotIn(KEY, resp.text)
		self.assertNotIn("changed-by-hand", resp.text)
		self.assertEqual(self.cm.datasource_manager("openweathermap-api").open().get()[1]["apiKey"], "changed-by-hand")
		self.assertEqual(self.application.calls, [])

	def test_a_restore_writes_the_files_between_a_begin_and_an_end(self):
		blob = self.make()
		self.change_key("changed-by-hand")
		resp = self.restore(blob, apply=True)
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual((resp.json()["applied"], resp.json()["written"]), (True, 1))
		self.assertEqual(self.cm.datasource_manager("openweathermap-api").open().get()[1]["apiKey"], KEY)
		self.assertEqual(self.application.calls, [("begin",), ("end", True, 1)])

	def test_the_device_password_is_not_changed_by_a_restore(self):
		blob = self.make()
		put(self.cm.settings_manager().open("access"), { "passwordHash": { "algo": "scrypt", "salt": "00", "hash": "MINE" } })
		self.change_key("changed-by-hand")
		self.assertEqual(self.restore(blob, apply=True).status_code, 200)
		self.assertEqual(self.cm.settings_manager().open("access").get()[1]["passwordHash"]["hash"], "MINE")

	def test_a_new_file_is_created_and_a_file_the_backup_lacks_is_left_alone(self):
		blob = self.make()
		extra = self.cm.plugin_manager("slide-show").file("list-keepme")
		put(extra, { "left": ["x"] })
		os.remove(self.cm.datasource_manager("openweathermap-api").settings_path())
		self.cm.evict_all()
		body = self.restore(blob, apply=True).json()
		self.assertIn(("datasources/openweathermap-api/settings.json", "new"), [(f["name"], f["status"]) for f in body["files"]])
		self.assertEqual(extra.get()[1], { "left": ["x"] })

	def test_a_wrong_passphrase_is_a_403_that_counts_against_the_client(self):
		blob = self.make()
		resp = self.restore(blob, "not the right one")
		self.assertEqual(resp.status_code, 403)
		self.assertEqual(resp.json()["message"], NOT_OPENED)
		for _ in range(6):
			last = self.restore(blob, "not the right one")
		self.assertEqual(last.status_code, 429)
		self.assertEqual(self.application.calls, [])

	def test_something_that_is_not_a_backup_is_a_422(self):
		for archive in (b"", b"hello", b"x" * 500):
			with self.subTest(archive[:5]):
				self.assertEqual(self.restore(archive).status_code, 422)
		self.assertEqual(self.client.post("/api/restore", json={ "archive": "***not base64***", "passphrase": PASSPHRASE }).status_code, 422)

	def test_a_passphrase_that_is_not_text_is_a_403_not_a_crash(self):
		blob = self.make()
		resp = self.client.post("/api/restore", content=json.dumps({ "archive": base64.b64encode(blob).decode(), "passphrase": chr(0xD800) * 12 }, ensure_ascii=True), headers={ "Content-Type": "application/json" })
		self.assertEqual(resp.status_code, 403)

	def test_a_setting_that_is_not_set_yet_is_not_a_reason_to_refuse(self):
		# the factory storage has an API key that is null though the form will not save without one: a backup of it must restore
		resp = self.restore(self.make(), apply=False)
		self.assertEqual(resp.status_code, 200, resp.text)

	def test_a_document_that_fails_the_rules_refuses_the_whole_restore_and_names_no_value(self):
		bad = seal({ "settings/theme-settings.json": json.dumps({ "scheme": "not-a-scheme", "hue": KEY }).encode(), "settings/system-settings.json": b'{"timeFormat": "24h"}' }, PASSPHRASE)
		resp = self.restore(bad, apply=True)
		self.assertEqual(resp.status_code, 422)
		self.assertNotIn(KEY, resp.text)
		self.assertTrue(any(e["path"][0] == "settings/theme-settings.json" for e in resp.json()["errors"]))
		self.assertEqual(self.application.calls, [])

	def test_a_schedule_that_does_not_load_is_refused(self):
		bad = seal({ "schedules/playlist-x.json": json.dumps({ "_schema": "urn:inky:storage:schedule:playlist:1", "items": [{ "id": "a", "type": "Nope" }] }).encode() }, PASSPHRASE)
		resp = self.restore(bad, apply=True)
		self.assertEqual(resp.status_code, 422)
		self.assertTrue(all(e["path"][0] == "schedules/playlist-x.json" for e in resp.json()["errors"]))

	def test_a_name_this_device_has_no_place_for_is_left_out_and_counted(self):
		blob = seal({ "plugins/not-installed/state.json": b"{}", "settings/theme-settings.json": b'{"scheme": "monochrome"}', "settings/access-settings.json": b'{"passwordHash": {"hash": "X"}}', "settings/bogus-settings.json": b"{}" }, PASSPHRASE)
		body = self.restore(blob).json()
		self.assertEqual(body["leftOut"], 3)
		self.assertEqual([f["name"] for f in body["files"]], ["settings/theme-settings.json"])

	def test_a_restore_that_begins_is_refused_when_the_application_says_so(self):
		blob = self.make()
		self.change_key("changed-by-hand")
		self.application.refuse = "A restore is already running."
		resp = self.restore(blob, apply=True)
		self.assertEqual(resp.status_code, 409)
		self.assertEqual(self.cm.datasource_manager("openweathermap-api").open().get()[1]["apiKey"], "changed-by-hand")
		self.assertEqual(self.application.calls, [("begin",)])

	def test_a_failed_write_is_a_500_that_still_ends_the_restore(self):
		blob = self.make()
		self.change_key("changed-by-hand")
		with patch.object(cmod, "_internal_save", side_effect=OSError("disk full")):
			resp = self.restore(blob, apply=True)
		self.assertEqual(resp.status_code, 500)
		self.assertNotIn("disk full", resp.text)
		self.assertEqual(self.application.calls, [("begin",), ("end", False, 0)])

	def test_a_display_setting_that_changes_says_the_device_must_start_again(self):
		blob = seal({ "settings/display-settings.json": json.dumps({ **self.cm.shipped_settings("display"), "refreshInterval": 90 }).encode() }, PASSPHRASE)
		body = self.restore(blob).json()
		self.assertTrue(body["restartNeeded"])

SYSTEM = "urn:inky:storage:schema:system"

class TestRestoreMigrates(BackupApiBase):
	"""A restore brings the archive's documents up to this version (#391), refuses one from a newer version, and reads the manifest."""
	def raise_system_to(self, number: int) -> None:
		path = os.path.join(self.storage, "schemas", "system.json")
		with open(path, encoding="utf-8") as f:
			schema = json.load(f)
		schema["_schema"] = f"{SYSTEM}:{number}"
		with open(path, "w", encoding="utf-8") as f:
			json.dump(schema, f)
		self.cm.evict_all()

	def old_backup(self, **extra: Any) -> bytes:
		document = { "_schema": f"{SYSTEM}:1", "timezoneName": "America/New_York", "locale": "en-US", "timeFormat": "12h", **extra }
		return seal({ "settings/system-settings.json": json.dumps(document).encode() }, PASSPHRASE)

	def test_an_old_backup_is_brought_up_and_the_preview_says_so(self):
		self.raise_system_to(2)
		step = lambda doc: { **doc, "clockStyle": doc["timeFormat"] }
		with patch.dict(cast(dict, __import__("python.model.migrations", fromlist=["MIGRATIONS"]).MIGRATIONS), { SYSTEM: { 1: step } }):
			preview = self.restore(self.old_backup()).json()
			self.assertEqual(preview["upgraded"], [{ "name": "settings/system-settings.json", "label": "Settings: system", "from": 1, "to": 2 }])
			self.assertEqual(self.application.calls, [])
			done = self.restore(self.old_backup(), apply=True)
			self.assertEqual(done.status_code, 200, done.text)
		self.cm.evict_all()
		stored = self.cm.settings_manager().open("system").get()[1]
		assert stored is not None
		self.assertEqual((stored["_schema"], stored["clockStyle"], stored["timeFormat"]), (f"{SYSTEM}:2", "12h", "12h"))

	def test_a_backup_from_before_versions_is_the_first_version_and_gets_stamped(self):
		blob = seal({ "settings/system-settings.json": json.dumps({ "timezoneName": "America/New_York", "locale": "en-US", "timeFormat": "12h" }).encode() }, PASSPHRASE)
		self.assertEqual(self.restore(blob, apply=True).status_code, 200)
		self.cm.evict_all()
		self.assertEqual(self.cm.settings_manager().open("system").get()[1]["_schema"], f"{SYSTEM}:1")  # type: ignore[index]

	def test_a_document_from_a_newer_version_refuses_the_whole_restore_and_names_no_value(self):
		blob = seal({ "settings/system-settings.json": json.dumps({ "_schema": f"{SYSTEM}:9", "timeFormat": KEY }).encode(),
			"settings/theme-settings.json": b'{"scheme": "monochrome"}' }, PASSPHRASE)
		resp = self.restore(blob, apply=True)
		self.assertEqual(resp.status_code, 422)
		self.assertNotIn(KEY, resp.text)
		self.assertEqual([e["path"] for e in resp.json()["errors"]], [["settings/system-settings.json"]])
		self.assertIn("newer version", resp.json()["errors"][0]["message"])
		self.assertEqual(self.application.calls, [])

	def test_a_source_raised_without_its_migration_is_refused_too(self):
		self.raise_system_to(2)
		resp = self.restore(self.old_backup(), apply=True)
		self.assertEqual(resp.status_code, 422)
		self.assertIn("Cannot be brought up", resp.json()["errors"][0]["message"])

	def test_a_kept_list_or_sign_ins_from_a_newer_version_are_refused(self):
		for name in ("plugins/slide-show/list-aaaa.json", "datasources/calendar-sources/tokens.json"):
			with self.subTest(name):
				resp = self.restore(seal({ name: json.dumps({ "_version": 99, "items": [] }).encode() }, PASSPHRASE))
				self.assertEqual(resp.status_code, 422)
				self.assertEqual(resp.json()["errors"][0]["path"][0], name)

	def test_a_backup_carries_a_manifest_that_the_preview_reads_and_is_not_a_file_left_out(self):
		# (the device stamps every stored document at start; the helper that wrote this one did not)
		put(self.cm.datasource_manager("openweathermap-api").open(), { "_schema": "urn:inky:storage:schema:datasource:openweathermap-api:1", "apiKey": KEY })
		blob = self.make()
		files = unseal(blob, PASSPHRASE)
		manifest = json.loads(files["MANIFEST.json"])
		self.assertEqual((manifest["format"], manifest["files"]["settings/system-settings.json"]), (1, f"{SYSTEM}:1"))
		self.assertEqual(manifest["files"]["datasources/openweathermap-api/settings.json"], "urn:inky:storage:schema:datasource:openweathermap-api:1")
		body = self.restore(blob).json()
		self.assertEqual(body["madeAt"], manifest["created"])
		self.assertEqual(body["leftOut"], 0)

	def test_a_backup_without_a_manifest_still_restores_and_a_newer_format_does_not(self):
		self.assertIsNone(self.restore(seal({ "settings/theme-settings.json": b'{"scheme": "monochrome"}' }, PASSPHRASE)).json()["madeAt"])
		newer = seal({ "MANIFEST.json": json.dumps({ "format": 2, "created": "2030-01-01T00:00:00+00:00", "files": {} }).encode(), "settings/theme-settings.json": b"{}" }, PASSPHRASE)
		resp = self.restore(newer)
		self.assertEqual(resp.status_code, 422)
		self.assertIn("newer version", resp.json()["message"])
		# a manifest that cannot be read only informs: the documents are what is checked
		odd = seal({ "MANIFEST.json": b"not json", "settings/theme-settings.json": b'{"scheme": "monochrome"}' }, PASSPHRASE)
		self.assertEqual(self.restore(odd).status_code, 200)

	def make(self) -> bytes:
		return self.backup().content

class Recorder:
	def __init__(self) -> None:
		self.sent: list[tuple[str, Any]] = []
	def send(self, route: str, msg: Any) -> None:
		self.sent.append((route, msg))

class TestApplicationHoldsTheNotifications(unittest.TestCase):
	def setUp(self):
		self.app = Application("TestApp")
		self.app.cm = temp_configuration_manager(self)
		self.recorder = Recorder()
		self.app.router = cast(MessageRouter, self.recorder)
		self.addCleanup(self.app._end_restore_state)

	def begin(self) -> Any:
		reply: Future = Future()
		self.app._restore_begin(RestoreBegin(NOW, reply))
		return reply.result(timeout=1)

	def watcher(self, name: str = "a.json"):
		path = os.path.join(self.app.cm.storage_settings, name)  # type: ignore[union-attr]
		self.app._configuration_watcher_event(ConfigurationWatcherEvent(NOW, "modified", path))

	def sends(self, route: str) -> list:
		return [m for r, m in self.recorder.sent if r == route]

	def test_a_change_is_announced_to_every_task_as_it_is_when_no_restore_runs(self):
		self.watcher()
		self.assertEqual(len(self.sends("configuration")), 1)
		self.assertEqual(len(self.sends("telemetry")), 1)

	def test_many_files_of_a_restore_are_one_notice_and_one_telemetry_line_after_the_last(self):
		self.assertIsNone(self.begin())
		generation = self.app._restore_generation
		for i in range(25):
			self.watcher(f"f{i}.json")
		self.app._restore_end(RestoreEnd(NOW, True, 25))
		for i in range(25):
			self.watcher(f"g{i}.json")
		# nobody has heard a thing, however long the restore took
		self.assertEqual(self.recorder.sent, [])
		self.assertEqual(self.app._restore_state, "draining")
		self.app._restore_settled(RestoreSettled(NOW, generation, "quiet"))
		[changed] = self.sends("configuration")
		self.assertEqual((changed.area, changed.type), ("restore", "restore"))
		[telemetry] = self.sends("telemetry")
		self.assertEqual((telemetry.values["kind"], telemetry.values["files"], telemetry.values["ok"]), ("restore", 25, True))
		self.assertEqual(self.app._restore_state, "idle")
		# and the next change is announced as ever
		self.watcher()
		self.assertEqual(len(self.sends("configuration")), 2)

	def test_the_device_own_state_is_never_announced(self):
		self.assertIsNone(self.begin())
		self.app._configuration_watcher_event(ConfigurationWatcherEvent(NOW, "modified", os.path.join(self.app.cm.storage_state, "refresh.json")))  # type: ignore[union-attr]
		self.assertEqual(self.app._restore_absorbed, 0)

	def test_a_restore_is_refused_while_another_runs_and_when_unclaimed(self):
		self.assertIsNone(self.begin())
		self.assertIn("already running", self.begin())
		self.app._end_restore_state()
		self.app.setup_notice = lambda: ["Set up this device"]
		self.assertIn("not been claimed", self.begin())
		self.assertEqual(self.app._restore_state, "idle")

	def test_a_begin_that_nobody_waited_for_never_starts(self):
		reply: Future = Future()
		reply.cancel()
		self.app._restore_begin(RestoreBegin(NOW, reply))
		self.assertEqual(self.app._restore_state, "idle")

	def test_the_lease_ends_a_restore_whose_end_never_came(self):
		self.assertIsNone(self.begin())
		generation = self.app._restore_generation
		self.watcher()
		self.app._restore_settled(RestoreSettled(NOW, generation, "lease"))
		self.assertEqual(self.app._restore_state, "idle")
		[telemetry] = self.sends("telemetry")
		self.assertFalse(telemetry.values["ok"])
		self.assertEqual(len(self.sends("configuration")), 1)

	def test_a_late_timer_of_an_old_restore_does_nothing(self):
		self.assertIsNone(self.begin())
		old = self.app._restore_generation
		self.app._end_restore_state()
		self.assertIsNone(self.begin())
		self.app._restore_settled(RestoreSettled(NOW, old, "lease"))
		self.assertEqual(self.app._restore_state, "restoring")
		self.assertEqual(self.recorder.sent, [])

	def test_a_quiet_timer_while_files_are_still_being_written_does_nothing(self):
		self.assertIsNone(self.begin())
		self.app._restore_settled(RestoreSettled(NOW, self.app._restore_generation, "quiet"))
		self.assertEqual(self.app._restore_state, "restoring")

	def test_the_failed_restore_says_so_once(self):
		self.assertIsNone(self.begin())
		self.app._restore_end(RestoreEnd(NOW, False, 0))
		self.app._restore_settled(RestoreSettled(NOW, self.app._restore_generation, "cap"))
		[telemetry] = self.sends("telemetry")
		self.assertEqual((telemetry.values["ok"], telemetry.values["message"]), (False, "A backup could not be restored."))

	def test_a_quit_clears_a_restore_so_nothing_stays_held_back(self):
		self.assertIsNone(self.begin())
		self.app._handleStop(NOW)
		self.assertEqual(self.app._restore_state, "idle")
		self.watcher()
		self.assertEqual(len(self.sends("configuration")), 1)

	def test_the_timers_really_settle_after_the_last_event(self):
		"""The real timers, shortened: each absorbed event pushes the settling back, and one message ends it."""
		self.app.restore_quiet_seconds, self.app.restore_cap_seconds, self.app.restore_lease_seconds = 0.3, 5.0, 5.0
		self.assertIsNone(self.begin())
		self.app._restore_end(RestoreEnd(NOW, True, 3))
		for _ in range(4):
			time.sleep(0.15)
			self.watcher()
		settled = None
		deadline = time.monotonic() + 3
		while time.monotonic() < deadline and settled is None:
			try:
				message = self.app.msg_queue.get(timeout=0.1)
			except Exception:
				continue
			if isinstance(message, RestoreSettled):
				settled = message
		assert settled is not None
		self.assertEqual(settled.reason, "quiet")
		# not before the last event had been quiet for the whole time
		self.assertEqual(self.recorder.sent, [])
		self.app._restore_settled(settled)
		self.assertEqual(len(self.sends("configuration")), 1)

class TestEveryoneReadsAgainOnce(unittest.TestCase):
	def test_the_layers_treat_a_restore_as_everything_changed(self):
		from ..task.playlist_layer import PlaylistLayer
		from ..task.timer_layer import TimerLayer
		for layer_class in (PlaylistLayer, TimerLayer):
			with self.subTest(layer_class.__name__):
				layer = layer_class("L", cast(MessageRouter, Recorder()))
				layer.cm = cast(Any, object())
				layer.timebase = cast(Any, SimpleNamespace(current_time=lambda: NOW))
				fired = threading.Event()
				layer._reload = cast(Any, SimpleNamespace(trigger=fired.set))
				layer._configuration_changed(ConfigurationChanged(NOW, "restore", "restore", ""))
				self.assertTrue(fired.is_set())
