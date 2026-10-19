"""
Versioned documents (#391): a document carries the `_schema` of its source, migrations bring an older one up in order, and the sources' numbers are raised (with a migration) when a setting
changes shape. `fixtures/schema_shapes.json` records each source's properties at its current number: this test fails when one disappears or changes without the number being raised.
To record a source's new shape after raising its number: `uv run python -m python.tests.test_schema_versions --record`.
"""
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

from ..model import migrations
from ..model.configuration_manager import ConfigurationManager
from ..model.migrations import MIGRATIONS, MigrationGap, TooNew, migrate, migrate_file
from ..model.schedule import SCHEMA_PLAYLIST, SCHEMA_TASKS
from ..model.schema_versions import SchemaId, file_version, schema_id_of, stamped
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

SHAPES = os.path.join(os.path.dirname(__file__), "fixtures", "schema_shapes.json")
SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "storage", "schemas")
SYSTEM = "urn:inky:storage:schema:system"

def sources() -> dict[str, dict]:
	"""Every source of a settings document, by its `_schema` family: `{ family: { urn, properties } }` (the device schemas, then the descriptors that have settings)."""
	found: dict[str, dict] = {}
	for name in sorted(os.listdir(SCHEMAS)):
		with open(os.path.join(SCHEMAS, name), encoding="utf-8") as f:
			schema = json.load(f)
		found[name[:-5]] = { "urn": schema.get("_schema"), "properties": (schema.get("schema") or {}).get("properties") or [], "label": f"schemas/{name}" }
	cm = ConfigurationManager()
	# the display document's source is its schema together with the settings of every display device (they are chosen with its `display_type` and stored in it)
	for device in cm.enum_displays():
		found["display"]["properties"] = [*found["display"]["properties"], *(((device["info"].get("instanceSettings") or {}).get("schema") or {}).get("properties") or [])]
	for kind, items in (("plugin", cm.enum_plugins()), ("datasource", cm.enum_datasources())):
		for item in items:
			settings = item["info"].get("settings")
			if isinstance(settings, dict):
				found[f"{kind}:{item['info']['id']}"] = { "urn": settings.get("_schema"), "properties": (settings.get("schema") or {}).get("properties") or [], "label": f"{kind} {item['info']['id']}" }
	return found

def shape_of(properties: list[dict]) -> dict[str, dict]:
	"""What a migration would have to care about in a property: its name, its type, and what it may be (`enum`, `format`). Titles, descriptions, limits and defaults may change freely."""
	return { p["name"]: { k: p[k] for k in ("type", "enum", "format") if k in p } for p in properties if isinstance(p, dict) and isinstance(p.get("name"), str) and p.get("type") != "header" }

class TestSchemaId(unittest.TestCase):
	def test_a_urn_is_taken_apart(self):
		found = SchemaId.parse("urn:inky:storage:schema:datasource:year_progress:12")
		assert found is not None
		self.assertEqual((found.family, found.version), ("urn:inky:storage:schema:datasource:year_progress", 12))
		self.assertEqual(str(found.with_version(13)), "urn:inky:storage:schema:datasource:year_progress:13")

	def test_the_urn_an_earlier_release_wrote_is_the_same_family(self):
		found = SchemaId.parse("urn:inky:storage:settings:system:1")
		assert found is not None
		self.assertEqual((found.family, found.version), (SYSTEM, 1))
		upgraded, _ = migrate(f"{SYSTEM}:1", { "_schema": "urn:inky:storage:settings:system:1", "a": 1 })
		self.assertEqual(upgraded, { "_schema": f"{SYSTEM}:1", "a": 1 })

	def test_what_is_not_ours_is_none(self):
		for bad in (None, 5, "", "system", "urn:inky:storage:schema:system", "urn:inky:storage:schema:system:0", "urn:inky:storage:schema:system:x", "urn:other:schema:system:1", "urn:inky:storage:schema:system:-1"):
			with self.subTest(bad):
				self.assertIsNone(SchemaId.parse(bad))

	def test_a_document_without_a_schema_or_version_is_the_first(self):
		self.assertIsNone(schema_id_of({ "a": 1 }))
		self.assertEqual(file_version({ "a": 1 }), 1)
		self.assertEqual(file_version({ "_version": 3 }), 3)
		for bad in (0, -1, True, "2", 1.5, None):
			self.assertEqual(file_version({ "_version": bad }), 1)

class TestMigrate(unittest.TestCase):
	chain = { SYSTEM: {
		1: lambda doc: { **{ k: v for k, v in doc.items() if k != "timeFormat" }, "clock": doc.get("timeFormat") },
		2: lambda doc: { **doc, "clock": { "12h": "12-hour", "24h": "24-hour" }.get(doc.get("clock"), doc.get("clock")) },
	} }

	def go(self, document: dict, version: int = 3, defaults: dict|None = None):
		return migrate(f"{SYSTEM}:{version}", document, defaults, self.chain)

	def test_the_steps_run_in_order_and_the_document_is_stamped(self):
		upgraded, steps = self.go({ "timeFormat": "24h", "locale": "en-US" }, defaults={ "extra": None })
		self.assertEqual(upgraded, { "_schema": f"{SYSTEM}:3", "locale": "en-US", "clock": "24-hour", "extra": None })
		self.assertEqual(steps, ["1 to 2", "2 to 3"])

	def test_it_starts_where_the_document_is(self):
		upgraded, steps = self.go({ "_schema": f"{SYSTEM}:2", "clock": "12h" })
		self.assertEqual((upgraded["clock"], steps), ("12-hour", ["2 to 3"]))

	def test_a_current_document_is_the_same_and_the_input_is_never_changed(self):
		document = { "_schema": f"{SYSTEM}:3", "clock": "x" }
		upgraded, steps = self.go(document)
		self.assertEqual((upgraded, steps), (document, []))
		old = { "timeFormat": "24h" }
		self.go(old)
		self.assertEqual(old, { "timeFormat": "24h" })

	def test_what_the_person_set_is_kept_and_only_missing_keys_are_filled(self):
		upgraded, _ = self.go({ "_schema": f"{SYSTEM}:3", "locale": "de-DE" }, defaults={ "locale": "en-US", "tz": "UTC", "_hidden": 1 })
		self.assertEqual(upgraded, { "_schema": f"{SYSTEM}:3", "locale": "de-DE", "tz": "UTC" })

	def test_a_missing_step_is_a_gap_not_a_silent_skip(self):
		with self.assertRaises(MigrationGap) as e:
			migrate(f"{SYSTEM}:4", { "_schema": f"{SYSTEM}:3" }, None, self.chain)
		self.assertEqual(e.exception.version, 3)

	def test_a_document_from_newer_code_is_refused_unchanged(self):
		with self.assertRaises(TooNew) as e:
			self.go({ "_schema": f"{SYSTEM}:9", "secret": "SECRET" })
		self.assertEqual((e.exception.found, e.exception.known), (9, 3))
		self.assertNotIn("SECRET", str(e.exception))

	def test_another_kinds_schema_or_a_schema_that_is_not_ours_is_refused(self):
		for schema in ("urn:inky:storage:schema:theme:1", "garbage", 5):
			with self.subTest(schema):
				with self.assertRaises(ValueError):
					self.go({ "_schema": schema })

	def test_a_step_that_registers_twice_is_refused(self):
		with patch.dict(MIGRATIONS, {}, clear=False):
			migrations.migration("urn:inky:storage:schema:test", 1)(lambda d: d)
			with self.assertRaises(ValueError):
				migrations.migration("urn:inky:storage:schema:test", 1)(lambda d: d)
			MIGRATIONS.pop("urn:inky:storage:schema:test", None)

class TestMigrateFile(unittest.TestCase):
	def test_the_states(self):
		self.assertEqual(migrate_file({ "a": 1 }, 1), ({ "_version": 1, "a": 1 }, "upgraded"))
		self.assertEqual(migrate_file({ "_version": 1, "a": 1 }, 1), ({ "_version": 1, "a": 1 }, "current"))
		self.assertEqual(migrate_file({ "_version": 5 }, 1), (None, "newer"))
		self.assertEqual(migrate_file("not a dict", 1), (None, "unusable"))
		self.assertEqual(migrate_file({ "a": 1 }, 2), (None, "unusable"))

	def test_steps_run_and_a_failing_one_is_unusable(self):
		step = lambda doc: { "b": doc["a"] }
		self.assertEqual(migrate_file({ "a": 1 }, 2, { 1: step }), ({ "_version": 2, "b": 1 }, "upgraded"))
		self.assertEqual(migrate_file({ "x": 1 }, 2, { 1: step }), (None, "unusable"))
		self.assertEqual(stamped({ "a": 1, "_version": 9 }, 2), { "_version": 2, "a": 1 })

class TestEverySourceIsVersioned(unittest.TestCase):
	def test_every_source_has_a_well_formed_schema_of_its_own_kind(self):
		seen: set[str] = set()
		for key, source in sources().items():
			with self.subTest(key):
				found = SchemaId.parse(source["urn"])
				assert found is not None, f"{source['label']} has no usable _schema (urn:inky:storage:schema:<name>:<number>)"
				expected = f"urn:inky:storage:schema:{key.replace(':', ':')}" if ":" in key else f"urn:inky:storage:schema:{key}"
				self.assertEqual(found.family, expected)
				self.assertNotIn(found.family, seen)
				seen.add(found.family)

	def test_the_schedule_kinds_are_versioned_too(self):
		for urn in (SCHEMA_PLAYLIST, SCHEMA_TASKS):
			self.assertIsNotNone(SchemaId.parse(urn))

	def test_a_new_storage_is_seeded_with_each_documents_schema(self):
		cm = temp_configuration_manager(self)
		by_urn = { s["urn"] for s in sources().values() }
		checked = 0
		for stem in ("system", "display", "theme", "devices", "master-prompts"):
			_, document = cm.settings_manager().open(stem).get()
			assert document is not None
			self.assertIn(document.get("_schema"), by_urn, stem)
			checked += 1
		_, rss = cm.datasource_manager("rss").open().get()
		assert rss is not None
		self.assertEqual(rss["_schema"], "urn:inky:storage:schema:datasource:rss:1")
		self.assertGreater(checked, 3)

class TestSnapshot(unittest.TestCase):
	"""A source's properties may not disappear or change shape while its number stays: raise the number, add the migration, record the shape."""
	def setUp(self):
		with open(SHAPES, encoding="utf-8") as f:
			self.recorded: dict[str, Any] = json.load(f)

	def test_a_shape_does_not_change_without_its_number_and_a_migration(self):
		for key, source in sources().items():
			with self.subTest(key):
				found = SchemaId.parse(source["urn"])
				assert found is not None
				snapshot = self.recorded.get(found.family)
				assert snapshot is not None, f"{source['label']} is not recorded in fixtures/schema_shapes.json (run: python -m python.tests.test_schema_versions --record)"
				if found.version > snapshot["version"]:
					chain = MIGRATIONS.get(found.family, {})
					missing = [n for n in range(snapshot["version"], found.version) if n not in chain]
					self.assertEqual(missing, [], f"{source['label']} is at version {found.version}: it needs a migration from {missing} (python/model/migrations.py)")
					self.fail(f"{source['label']} is at version {found.version} and its migration exists: record the new shape (python -m python.tests.test_schema_versions --record)")
				self.assertEqual(found.version, snapshot["version"], f"{source['label']} went back from version {snapshot['version']}")
				now = shape_of(source["properties"])
				for name, shape in snapshot["properties"].items():
					self.assertIn(name, now, f"{source['label']}: '{name}' is gone but the number is still {found.version}: raise it, add the migration and record the shape")
					self.assertEqual(now[name], shape, f"{source['label']}: '{name}' changed shape but the number is still {found.version}: raise it, add the migration and record the shape")

	def test_nothing_recorded_is_for_a_source_that_is_gone(self):
		families = { SchemaId.parse(s["urn"]).family for s in sources().values() if SchemaId.parse(s["urn"]) is not None }  # type: ignore[union-attr]
		self.assertEqual(sorted(set(self.recorded) - families), [])

class TestStoredDocuments(WebApiTestBase):
	def stored(self, name: str) -> dict:
		self.cm.evict_all()
		_, document = self.cm.settings_manager().open(name).get()
		assert document is not None
		return document

	def test_a_saved_document_carries_the_sources_schema_whatever_the_body_says(self):
		body = self.client.get("/api/settings/system").json()
		self.assertEqual(body["_schema"], f"{SYSTEM}:1")
		for claimed in ("urn:inky:storage:schema:system:99", "bogus", None):
			with self.subTest(claimed):
				resp = self.client.put("/api/settings/system", json={ **body, "_schema": claimed })
				self.assertEqual(resp.status_code, 200, resp.text)
				body = self.client.get("/api/settings/system").json()
				self.assertEqual(self.stored("system")["_schema"], f"{SYSTEM}:1")

	def test_a_datasource_and_a_plugin_document_carry_theirs(self):
		body = self.client.get("/api/datasources/rss/settings").json()
		self.assertEqual(self.client.put("/api/datasources/rss/settings", json={ **body, "_schema": "bogus" }).status_code, 200)
		self.cm.evict_all()
		self.assertEqual(self.cm.datasource_manager("rss").open().get()[1]["_schema"], "urn:inky:storage:schema:datasource:rss:1")  # type: ignore[index]

class TestUpgradeAtStart(unittest.TestCase):
	def setUp(self):
		self.cm = temp_configuration_manager(self)
		self.schema_path = os.path.join(self.cm.storage_schemas, "system.json")

	def raise_system_to(self, number: int) -> None:
		"""What a newer release does: the shipped schema (refreshed into the storage at start) is at a higher number."""
		with open(self.schema_path, encoding="utf-8") as f:
			schema = json.load(f)
		schema["_schema"] = f"{SYSTEM}:{number}"
		with open(self.schema_path, "w", encoding="utf-8") as f:
			json.dump(schema, f)

	def document(self) -> dict:
		self.cm.evict_all()
		_, document = self.cm.settings_manager().open("system").get()
		assert document is not None
		return document

	def test_an_older_document_is_migrated_filled_and_stamped_once(self):
		rev, document = self.cm.settings_manager().open("system").get()
		assert document is not None
		self.cm.settings_manager().open("system").save(rev, { **{ k: v for k, v in document.items() if k != "_schema" }, "timeFormat": "12h" })
		self.raise_system_to(2)
		step = lambda doc: { **doc, "clockStyle": doc["timeFormat"] }
		with patch.dict(MIGRATIONS, { SYSTEM: { 1: step } }):
			changed = self.cm.upgrade_settings()
			self.assertIn("system-settings.json", changed)
			upgraded = self.document()
			self.assertEqual((upgraded["_schema"], upgraded["clockStyle"], upgraded["timeFormat"]), (f"{SYSTEM}:2", "12h", "12h"))
			self.assertEqual(self.cm.upgrade_settings(), [])
		self.assertEqual(self.cm.upgrade_problems, [])

	def test_a_document_from_newer_code_is_left_alone_and_named(self):
		rev, document = self.cm.settings_manager().open("system").get()
		assert document is not None
		newer = { **document, "_schema": f"{SYSTEM}:9", "timeFormat": "SECRET-FUTURE-VALUE" }
		self.cm.settings_manager().open("system").save(rev, newer)
		with self.assertLogs("python.model.configuration_manager", level="WARNING") as logged:
			changed = self.cm.upgrade_settings()
		self.assertNotIn("system-settings.json", changed)
		self.assertEqual(self.cm.upgrade_problems, ["system-settings.json"])
		self.assertEqual(self.document(), newer)
		self.assertNotIn("SECRET-FUTURE-VALUE", "\n".join(logged.output))

	def test_a_source_raised_without_its_migration_leaves_the_document_alone(self):
		self.raise_system_to(2)
		with patch.dict(MIGRATIONS, {}, clear=False):
			MIGRATIONS.pop(SYSTEM, None)
			with self.assertLogs("python.model.configuration_manager", level="ERROR"):
				self.cm.upgrade_settings()
		self.assertEqual(self.cm.upgrade_problems, ["system-settings.json"])
		self.assertEqual(self.document()["_schema"], f"{SYSTEM}:1")

	def test_a_schedule_is_stamped_by_its_kind_and_left_alone_when_current(self):
		self.assertEqual(self.cm.upgrade_settings(), [])
		path = self.cm.schedule_manager()
		path.write("playlist-x.json", { "_schema": SCHEMA_PLAYLIST, "id": "playlist-x", "name": "x", "items": [] })
		self.assertEqual(self.cm.upgrade_settings(), [])

class TestFilesWithoutASource(unittest.TestCase):
	"""A refresh state, a kept list and the sign-ins have an integer `_version`; one from newer code is not read as ours (and the sign-ins are never overwritten)."""
	def setUp(self):
		self.cm = temp_configuration_manager(self)

	def put(self, cob: Any, document: dict) -> None:
		rev, _ = cob.get()
		self.assertTrue(cob.save(rev, document)[0])

	def test_the_refresh_state_is_stamped_and_a_newer_one_is_no_state(self):
		from ..display.refresh_gate import REFRESH_VERSION, RefreshState
		state = RefreshState(self.cm)
		state.save(100.0, "abc")
		self.cm.evict_all()
		self.assertEqual(self.cm.state_file("refresh").get()[1], { "_version": REFRESH_VERSION, "lastEnd": 100.0, "digest": "abc" })
		again = RefreshState(self.cm)
		again.load()
		self.assertEqual((again.last_end, again.digest), (100.0, "abc"))
		self.put(self.cm.state_file("refresh"), { "_version": REFRESH_VERSION + 1, "lastEnd": 5.0, "digest": "x" })
		newer = RefreshState(self.cm)
		with self.assertLogs("python.display.refresh_gate", level="WARNING"):
			newer.load()
		self.assertEqual((newer.last_end, newer.digest), (None, None))

	def test_a_file_from_before_versions_is_read_as_the_first(self):
		from ..display.refresh_gate import RefreshState
		self.put(self.cm.state_file("refresh"), { "lastEnd": 7.0, "digest": "d" })
		state = RefreshState(self.cm)
		state.load()
		self.assertEqual((state.last_end, state.digest), (7.0, "d"))

	def test_a_kept_list_is_stamped_and_a_newer_one_is_replaced(self):
		import asyncio
		from datetime import datetime
		from ..plugins.kept_list import KEPT_LIST_VERSION, list_file_name, open_list
		pcm = self.cm.plugin_manager("slide-show")
		now = datetime(2026, 1, 1, 12).astimezone()
		async def fetch() -> list:
			return ["a", "b"]
		asyncio.run(open_list(pcm, "slot", "fp", now, fetch, True, 0, 30))
		self.cm.evict_all()
		document = pcm.file(list_file_name("slot")).get()[1]
		assert document is not None
		self.assertEqual((document["_version"], document["items"]), (KEPT_LIST_VERSION, ["a", "b"]))
		self.put(pcm.file(list_file_name("slot")), { **document, "_version": KEPT_LIST_VERSION + 1, "items": ["from the future"] })
		kept = asyncio.run(open_list(pcm, "slot", "fp", now, fetch, True, 0, 30))
		self.assertEqual(kept.head(), "a")

	def test_the_sign_ins_are_stamped_and_a_newer_file_is_never_overwritten(self):
		from ..datasources.calendar.accounts import AccountError, TOKENS_VERSION, TokenStore
		store = TokenStore(self.cm.datasource_manager("calendar"))
		store.put("Home", { "client_id": "c", "refresh_token": "r" })
		self.cm.evict_all()
		saved = self.cm.datasource_manager("calendar").file("tokens").get()[1]
		assert saved is not None
		self.assertEqual((saved["_version"], sorted(k for k in saved if k != "_version")), (TOKENS_VERSION, ["Home"]))
		self.assertEqual(store.get("Home", "c"), { "client_id": "c", "refresh_token": "r" })
		self.put(self.cm.datasource_manager("calendar").file("tokens"), { **saved, "_version": TOKENS_VERSION + 1 })
		with self.assertRaises(AccountError):
			store.put("Work", { "client_id": "c", "refresh_token": "w" })
		self.assertEqual(self.cm.datasource_manager("calendar").file("tokens").get()[1]["_version"], TOKENS_VERSION + 1)  # type: ignore[index]

def record() -> None:
	"""Write `fixtures/schema_shapes.json` from the sources as they are now (after raising a number and adding its migration)."""
	recorded: dict[str, Any] = {}
	for source in sources().values():
		found = SchemaId.parse(source["urn"])
		assert found is not None, source["label"]
		recorded[found.family] = { "version": found.version, "properties": shape_of(source["properties"]) }
	with open(SHAPES, "w", encoding="utf-8", newline="\n") as f:
		json.dump(dict(sorted(recorded.items())), f, indent="\t")
		f.write("\n")
	print(f"Recorded {len(recorded)} sources in {SHAPES}")

if __name__ == "__main__":
	if "--record" in sys.argv:
		record()
	else:
		unittest.main()
