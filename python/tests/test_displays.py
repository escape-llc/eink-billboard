"""
Display devices as descriptors (#397): `python/displays/<id>/display-info.json`, chosen by the display document's `display_type` (a `schema` field, as a plugin chooses its data source), their
settings stored in that document and checked like a task's content, their defaults filled in, and the Display task making the one the setting names.
"""
import json
import os
import unittest
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock

from ..display.display_base import picture_size
from ..display.mock_display import MockDisplay
from ..task.configure_event import ConfigureEvent, ConfigureOptions
from ..task.display import Display
from ..task.message_router import MessageRouter
from .test_web_api import WebApiTestBase
from .utils import temp_configuration_manager

NOW = datetime(2026, 1, 1, 12).astimezone()

class TestTheDescriptors(unittest.TestCase):
	def test_the_four_displays_are_installed_and_each_says_how_it_is_made(self):
		cm = temp_configuration_manager(self)
		found = { d["info"]["id"]: d for d in cm.enum_displays() }
		self.assertEqual(sorted(found), ["inky", "mock", "tk", "waveshare"])
		for did, item in found.items():
			with self.subTest(did):
				self.assertIn("display-device", item["info"]["features"])
				self.assertTrue(os.path.isfile(os.path.join(item["path"], item["info"]["file"])))

	def test_a_display_is_made_from_its_descriptor_and_a_disabled_one_is_not(self):
		cm = temp_configuration_manager(self)
		mock = next(d for d in cm.enum_displays() if d["info"]["id"] == "mock")
		made = cm.create_display(mock)
		self.assertIsInstance(made, MockDisplay)
		self.assertEqual(made.name, "mock")
		off = { "info": { **mock["info"], "disabled": True }, "path": mock["path"] }
		self.assertIsNone(cm.create_display(cast(Any, off)))

class TestPictureSize(unittest.TestCase):
	def test_width_and_height_with_the_descriptors_default_for_what_is_missing_or_unusable(self):
		self.assertEqual(picture_size({ "width": 320, "height": 240 }), (320, 240))
		self.assertEqual(picture_size({}), (800, 480))
		self.assertEqual(picture_size(None), (800, 480))
		for bad in (0, -5, "wide", 1.5, True, None):
			self.assertEqual(picture_size({ "width": bad, "height": bad }), (800, 480))

class TestSeedingAndUpgrade(unittest.TestCase):
	def test_a_new_storage_has_the_chosen_displays_defaults_in_its_document(self):
		cm = temp_configuration_manager(self)
		_, document = cm.settings_manager().open("display").get()
		assert document is not None
		self.assertEqual((document["display_type"], document["width"], document["height"], document["outputFolder"], document["cleanOutputFolder"]), ("mock", 800, 480, "eink-billboard-mock", False))
		self.assertNotIn("model", document)
		self.assertNotIn("borderColor", document)

	def test_a_document_whose_choice_changed_gets_its_devices_keys_at_the_next_start(self):
		cm = temp_configuration_manager(self)
		cob = cm.settings_manager().open("display")
		rev, document = cob.get()
		assert document is not None
		self.assertTrue(cob.save(rev, { **document, "display_type": "inky" })[0])
		changed = cm.upgrade_settings()
		self.assertIn("display-settings.json", changed)
		cm.evict_all()
		_, upgraded = cm.settings_manager().open("display").get()
		assert upgraded is not None
		self.assertEqual(upgraded["borderColor"], "white")
		# what the person set stays
		rev, upgraded = cm.settings_manager().open("display").get()
		assert upgraded is not None
		cm.settings_manager().open("display").save(rev, { **upgraded, "borderColor": "black" })
		cm.upgrade_settings()
		cm.evict_all()
		self.assertEqual(cm.settings_manager().open("display").get()[1]["borderColor"], "black")  # type: ignore[index]

class TestDisplaySettingsApi(WebApiTestBase):
	def put(self, **changes: Any):
		body = self.client.get("/api/settings/display").json()
		return self.client.put("/api/settings/display", json={ **body, **changes })

	def test_the_installed_displays_are_listed_with_the_settings_of_their_own(self):
		listed = { d["id"]: d for d in self.client.get("/api/displays/list").json() }
		self.assertEqual(sorted(listed), ["inky", "mock", "tk", "waveshare"])
		names = { p["name"] for p in listed["mock"]["instanceSettings"]["schema"]["properties"] }
		self.assertEqual(names, { "width", "height", "outputFolder", "cleanOutputFolder", "inks" })

	def test_the_display_type_is_a_schema_field_that_offers_the_displays(self):
		schema = self.client.get("/api/schemas/display").json()["schema"]
		prop = next(p for p in schema["properties"] if p["name"] == "display_type")
		self.assertEqual((prop["type"], prop["lookup"], schema["lookups"]["display"]), ("schema", "display", { "schema": "displays", "features": ["display-device"] }))

	def test_the_chosen_devices_fields_are_checked_like_a_tasks_content(self):
		self.assertEqual(self.put(width=1024, height=600).status_code, 200)
		for changes, field in (({ "width": 10 }, "width"), ({ "height": 99999 }, "height"), ({ "width": "wide" }, "width"), ({ "outputFolder": 5 }, "outputFolder")):
			with self.subTest(changes):
				resp = self.put(**changes)
				self.assertEqual(resp.status_code, 422, resp.text)
				self.assertEqual([e["path"] for e in resp.json()["errors"]], [[field]])

	def test_only_the_chosen_devices_fields_are_checked(self):
		# the mock is chosen: a border color that would be refused for an Inky is not looked at
		self.assertEqual(self.put(borderColor="plaid").status_code, 200)
		resp = self.put(display_type="inky", borderColor="plaid")
		self.assertEqual(resp.status_code, 422)
		self.assertEqual([e["path"] for e in resp.json()["errors"]], [["borderColor"]])
		self.assertEqual(self.put(display_type="inky", borderColor="red").status_code, 200)

	def test_a_display_that_is_not_installed_is_refused(self):
		for bad in ("bogus", "MOCK", ""):
			with self.subTest(bad):
				resp = self.put(display_type=bad)
				self.assertEqual(resp.status_code, 422, resp.text)
				self.assertEqual(resp.json()["errors"][0]["path"], ["display_type"])

	def test_the_waveshare_model_is_one_of_its_drivers(self):
		self.assertEqual(self.put(display_type="waveshare", model="epd7in3e").status_code, 200)
		resp = self.put(display_type="waveshare", model="epd-nonsense")
		self.assertEqual(resp.status_code, 422)
		self.assertEqual(resp.json()["errors"][0]["path"], ["model"])

	def test_a_saved_display_document_carries_the_displays_schema(self):
		self.assertEqual(self.put(width=640).status_code, 200)
		self.cm.evict_all()
		document = self.cm.settings_manager().open("display").get()[1]
		assert document is not None
		self.assertEqual(document["_schema"], "urn:inky:storage:schema:display:1")

class TestTheDisplayTask(unittest.TestCase):
	def configure(self, display_type: str) -> list[Any]:
		cm = temp_configuration_manager(self)
		cob = cm.settings_manager().open("display")
		rev, document = cob.get()
		assert document is not None
		cob.save(rev, { **document, "display_type": display_type, "refreshInterval": 0 })
		task = Display("d", MessageRouter())
		notified: list[Any] = []
		sink = MagicMock()
		sink.accept.side_effect = notified.append
		isp = MagicMock()
		isp.get_service.return_value = None
		try:
			task._configure_event(ConfigureEvent(NOW, ConfigureOptions(cm, isp), "display", sink))
		finally:
			task.quitMsg(MagicMock())
		return notified

	def test_the_display_the_setting_names_is_made(self):
		notified = self.configure("mock")
		self.assertEqual([m.error for m in notified], [False])

	def test_an_unknown_display_is_a_failure_in_our_words(self):
		notified = self.configure("bogus")
		self.assertTrue(notified[0].error)
		self.assertIn("Unrecognized display type", str(notified[0].content))

	def test_the_descriptors_are_what_the_display_documents_lookup_offers(self):
		with open(os.path.join(os.path.dirname(__file__), "..", "storage", "schemas", "display.json"), encoding="utf-8") as f:
			schema = json.load(f)
		self.assertEqual(schema["schema"]["lookups"]["display"]["schema"], "displays")
