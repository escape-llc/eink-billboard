import json
import os
import shutil
import threading
import unittest

from .test_web_api import WebApiTestBase, _error_shape
from ..model.schedule_store import check_item_shape, merge_patch

BASE = "/api/schedule/timer"
SPECIFIC = { "on_startup": False, "day": { "type": "dayofweek", "days": [0, 1, 2, 3, 4, 5, 6] }, "time": { "type": "specific", "hour": 9, "minute": 0 } }

CONTENT = { "dataSource": "image-folder", "slideMax": 4, "slideMinutes": 2, "folder": "/x" }

def task_body(**over) -> dict:
	body = { "title": "Morning", "enabled": True, "trigger": SPECIFIC, "task": { "plugin_name": "slide-show", "content": CONTENT } }
	body.update(over)
	return body

class ScheduleApiBase(WebApiTestBase):
	"""The plugin and datasource descriptors come from the source tree (slide-show, image-folder); the test writes the schedules it needs."""
	def setUp(self):
		super().setUp()
		schedules = os.path.join(self.storage, "schedules")
		for name in os.listdir(schedules):
			os.remove(os.path.join(schedules, name))
		self.write_doc("doc-a", "A", [self.item("a1", "One"), self.item("a2", "Two")])

	def item(self, ident: str, title: str, **over) -> dict:
		return { "id": ident, "title": title, "enabled": True, "trigger": SPECIFIC,
			"task": { "plugin_name": "slide-show", "content": CONTENT }, **over }

	def write_doc(self, ident: str, name: str, items: list[dict], file: str|None = None) -> str:
		path = os.path.join(self.storage, "schedules", file or f"{ident}.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({ "_schema": "urn:inky:storage:schedule:tasks:1", "id": ident, "name": name, "items": items }, f)
		return path

	def stored(self, ident: str = "doc-a") -> dict:
		with open(os.path.join(self.storage, "schedules", f"{ident}.json"), encoding="utf-8") as f:
			return json.load(f)

	def doc(self, ident: str = "doc-a") -> dict:
		return self.client.get(f"{BASE}/{ident}").json()["schedule"]

	def rev_of_item(self, item_id: str, ident: str = "doc-a") -> str:
		return next(x for x in self.doc(ident)["items"] if x["id"] == item_id)["_rev"]

class TestDocuments(ScheduleApiBase):
	def test_list_and_get_carry_revisions_for_the_document_and_each_task(self):
		listed = self.client.get(f"{BASE}/list").json()["timed"]
		self.assertEqual([d["id"] for d in listed], ["doc-a"])
		doc = self.doc()
		self.assertEqual(doc["_rev"], listed[0]["_rev"])
		self.assertTrue(all(x["_rev"] for x in doc["items"]))
		self.assertNotEqual(doc["items"][0]["_rev"], doc["items"][1]["_rev"])

	def test_unknown_document_is_404_and_a_traversal_id_reaches_nothing(self):
		for ident in ("nope", "..%2F..%2Fsettings%2Fsystem-settings", "doc-a%00"):
			_error_shape(self, self.client.get(f"{BASE}/{ident}"), 404)

	def test_create_generates_the_id_and_the_file_name(self):
		resp = self.client.post(BASE, json={ "name": "  New  ", "items": [task_body()] })
		self.assertEqual(resp.status_code, 201, resp.text)
		doc = resp.json()["schedule"]
		self.assertTrue(doc["id"].startswith("tasks-"))
		self.assertEqual(doc["name"], "New")
		self.assertTrue(os.path.isfile(os.path.join(self.storage, "schedules", f"{doc['id']}.json")))
		self.assertTrue(doc["items"][0]["id"])
		self.assertEqual([d["id"] for d in self.client.get(f"{BASE}/list").json()["timed"]].count(doc["id"]), 1)

	def test_create_validates(self):
		body = _error_shape(self, self.client.post(BASE, json={ "items": [], "extra": 1 }), 422)
		self.assertEqual({tuple(e["path"]) for e in body["errors"]}, {("name",), ("extra",)})
		body = _error_shape(self, self.client.post(BASE, json={ "name": "x", "items": [task_body(trigger="x")] }), 422)
		self.assertEqual(body["errors"][0]["path"][:2], ["items", "0"])

	def test_rename_needs_the_current_rev_and_keeps_the_items(self):
		rev = self.doc()["_rev"]
		resp = self.client.patch(f"{BASE}/doc-a", json={ "name": "Renamed", "_rev": rev })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.stored()["name"], "Renamed")
		self.assertEqual(len(self.stored()["items"]), 2)
		body = _error_shape(self, self.client.patch(f"{BASE}/doc-a", json={ "name": "Again", "_rev": rev }), 409)
		self.assertEqual(body["rev"], resp.json()["rev"])

	def test_replace_document(self):
		rev = self.doc()["_rev"]
		resp = self.client.put(f"{BASE}/doc-a", json={ "name": "Replaced", "_rev": rev, "items": [task_body(id="a1")] })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual([x["id"] for x in self.stored()["items"]], ["a1"])
		_error_shape(self, self.client.put(f"{BASE}/doc-a", json={ "name": "x", "_rev": rev, "items": [] }), 409)
		_error_shape(self, self.client.put(f"{BASE}/doc-a", json={ "name": "x", "id": "other", "_rev": resp.json()["rev"], "items": [] }), 422)

	def test_replace_rejects_duplicate_item_ids(self):
		rev = self.doc()["_rev"]
		body = _error_shape(self, self.client.put(f"{BASE}/doc-a", json={ "name": "x", "_rev": rev, "items": [task_body(id="d"), task_body(id="d")] }), 422)
		self.assertIn("Duplicate id", [e["message"] for e in body["errors"]])

	def test_delete_document_needs_the_rev_and_may_remove_the_last_one(self):
		_error_shape(self, self.client.delete(f"{BASE}/doc-a"), 422)
		_error_shape(self, self.client.delete(f"{BASE}/doc-a", params={ "rev": "stale" }), 409)
		resp = self.client.delete(f"{BASE}/doc-a", params={ "rev": self.doc()["_rev"] })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.client.get(f"{BASE}/list").json()["timed"], [])
		_error_shape(self, self.client.get(f"{BASE}/doc-a"), 404)

	def test_two_files_with_one_id_are_a_conflict_not_a_guess(self):
		self.write_doc("doc-a", "Copy", [], file="copy.json")
		_error_shape(self, self.client.get(f"{BASE}/doc-a"), 409)

class TestTasks(ScheduleApiBase):
	def test_get_one_task(self):
		got = self.client.get(f"{BASE}/doc-a/items/a2").json()["task"]
		self.assertEqual((got["id"], got["title"], got["schedule"]), ("a2", "Two", "doc-a"))
		self.assertEqual(got["_rev"], self.rev_of_item("a2"))
		_error_shape(self, self.client.get(f"{BASE}/doc-a/items/zzz"), 404)

	def test_add_generates_the_id_and_defaults(self):
		resp = self.client.post(f"{BASE}/doc-a/items", json={ "trigger": SPECIFIC, "task": { "plugin_name": "slide-show", "content": { **CONTENT, "folder": "/y" } } })
		self.assertEqual(resp.status_code, 201, resp.text)
		task = resp.json()["task"]
		self.assertEqual((task["title"], task["enabled"]), ("", True))
		self.assertEqual([x["id"] for x in self.stored()["items"]][:2], ["a1", "a2"])
		self.assertEqual(len(self.stored()["items"]), 3)
		body = _error_shape(self, self.client.post(f"{BASE}/doc-a/items", json=task_body(id="mine")), 422)
		self.assertEqual(body["errors"][0]["path"], ["id"])

	def test_replace_a_task(self):
		rev = self.rev_of_item("a1")
		resp = self.client.put(f"{BASE}/doc-a/items/a1", json={ **task_body(title="Changed"), "_rev": rev })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.stored()["items"][0]["title"], "Changed")
		self.assertEqual(self.stored()["items"][1]["title"], "Two")
		self.assertEqual(resp.json()["task"]["id"], "a1")
		_error_shape(self, self.client.put(f"{BASE}/doc-a/items/a1", json={ **task_body(), "_rev": rev }), 409)
		_error_shape(self, self.client.put(f"{BASE}/doc-a/items/a1", json=task_body()), 409)

	def test_a_stale_rev_gets_the_current_one_and_other_tasks_do_not_conflict(self):
		rev_a1, rev_a2 = self.rev_of_item("a1"), self.rev_of_item("a2")
		resp = self.client.patch(f"{BASE}/doc-a/items/a2", json={ "title": "Two!", "_rev": rev_a2 })
		self.assertEqual(resp.status_code, 200, resp.text)
		# a1 was loaded before a2 changed: still current
		resp1 = self.client.patch(f"{BASE}/doc-a/items/a1", json={ "enabled": False, "_rev": rev_a1 })
		self.assertEqual(resp1.status_code, 200, resp1.text)
		body = _error_shape(self, self.client.patch(f"{BASE}/doc-a/items/a2", json={ "title": "x", "_rev": rev_a2 }), 409)
		self.assertEqual(body["rev"], resp.json()["rev"])

	def test_patch_merges_content_and_replaces_the_trigger(self):
		rev = self.rev_of_item("a1")
		new_trigger = { "on_startup": True, "day": { "type": "dayofmonth", "days": [-1] }, "time": { "type": "hourly", "minutes": [30] } }
		resp = self.client.patch(f"{BASE}/doc-a/items/a1", json={ "_rev": rev, "trigger": new_trigger, "task": { "content": { "slideMax": 7, "folder": None } } })
		self.assertEqual(resp.status_code, 422, resp.text)	# folder is required by the datasource: removing it is invalid
		resp = self.client.patch(f"{BASE}/doc-a/items/a1", json={ "_rev": rev, "trigger": new_trigger, "task": { "content": { "slideMax": 7 } } })
		self.assertEqual(resp.status_code, 200, resp.text)
		item = self.stored()["items"][0]
		self.assertEqual(item["trigger"], new_trigger)
		self.assertEqual(item["task"]["content"], { **CONTENT, "slideMax": 7 })
		self.assertEqual(item["task"]["plugin_name"], "slide-show")

	def test_patching_title_or_enabled_does_not_revalidate_the_content(self):
		# a task whose stored content is incomplete can still be renamed or paused; touching `task` checks it
		path = os.path.join(self.storage, "schedules", "doc-a.json")
		raw = self.stored()
		del raw["items"][0]["task"]["content"]["slideMinutes"]
		with open(path, "w", encoding="utf-8") as f:
			json.dump(raw, f)
		resp = self.client.patch(f"{BASE}/doc-a/items/a1", json={ "title": "Still renamable", "enabled": False, "_rev": self.rev_of_item("a1") })
		self.assertEqual(resp.status_code, 200, resp.text)
		_error_shape(self, self.client.patch(f"{BASE}/doc-a/items/a1", json={ "task": { "content": { "slideMax": 2 } }, "_rev": resp.json()["rev"] }), 422)

	def test_patch_cannot_remove_required_parts_or_change_the_id(self):
		rev = self.rev_of_item("a1")
		for patch in ({ "trigger": None }, { "task": None }, { "title": None }, { "enabled": None }, { "task": { "plugin_name": None } }, { "id": "other" }):
			_error_shape(self, self.client.patch(f"{BASE}/doc-a/items/a1", json={ "_rev": rev, **patch }), 422)
		self.assertEqual(self.stored()["items"][0]["title"], "One")

	def test_delete_a_task(self):
		rev = self.rev_of_item("a1")
		_error_shape(self, self.client.delete(f"{BASE}/doc-a/items/a1", params={ "rev": "stale" }), 409)
		resp = self.client.delete(f"{BASE}/doc-a/items/a1", params={ "rev": rev })
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual([x["id"] for x in self.stored()["items"]], ["a2"])
		_error_shape(self, self.client.delete(f"{BASE}/doc-a/items/a1", params={ "rev": rev }), 404)

	def test_validation_paths(self):
		def errors(**over):
			body = _error_shape(self, self.client.post(f"{BASE}/doc-a/items", json=task_body(**over)), 422)
			return {(tuple(e["path"]), e["message"]) for e in body["errors"]}
		bad_trigger = { "on_startup": False, "day": { "type": "dayofweek", "days": [9] }, "time": { "type": "specific", "hour": 1, "minute": 0 } }
		self.assertIn((("trigger",), "day.days (0=Sunday) has an invalid entry (expected 0 to 6)"), errors(trigger=bad_trigger))
		self.assertIn((("task", "plugin_name"), "Unknown plugin"), errors(task={ "plugin_name": "nope", "content": {} }))
		self.assertIn((("task", "content", "slideMinutes"), "Minimum 1"), errors(task={ "plugin_name": "slide-show", "content": { **CONTENT, "slideMinutes": 0 } }))
		self.assertIn((("task", "content", "dataSource"), "Not one of the allowed values"), errors(task={ "plugin_name": "slide-show", "content": { **CONTENT, "dataSource": "gone" } }))
		self.assertIn((("task", "content", "folder"), "Required"), errors(task={ "plugin_name": "slide-show", "content": { "dataSource": "image-folder", "slideMax": 1, "slideMinutes": 1 } }))
		self.assertIn((("surprise",), "Unknown property"), errors(surprise=1))
		self.assertIn((("task", "extra"), "Unknown property"), errors(task={ "plugin_name": "interstitial", "content": {}, "extra": 1 }))
		self.assertIn((("enabled",), "Expected true or false"), errors(enabled="yes"))
		self.assertEqual(len(self.stored()["items"]), 2)

	def test_the_file_keeps_what_the_api_did_not_touch(self):
		path = os.path.join(self.storage, "schedules", "doc-a.json")
		with open(path, encoding="utf-8") as f:
			raw = json.load(f)
		raw["items"][1]["title"] = "Two"
		raw["note"] = "kept"
		with open(path, "w", encoding="utf-8") as f:
			json.dump(raw, f)
		self.client.patch(f"{BASE}/doc-a/items/a1", json={ "title": "x", "_rev": self.rev_of_item("a1") })
		self.assertEqual(self.stored()["note"], "kept")
		self.assertEqual([n for n in os.listdir(os.path.join(self.storage, "schedules")) if n.startswith(".tmp-")], [])

	def test_changes_show_in_the_lists_and_in_render(self):
		self.client.patch(f"{BASE}/doc-a/items/a1", json={ "title": "Renamed task", "_rev": self.rev_of_item("a1") })
		doc = self.client.get("/api/schedule/tasks/render", params={ "start": "2026-01-05", "days": 1 }).json()
		self.assertEqual(next(x for x in doc["schedules"]["doc-a"]["items"] if x["id"] == "a1")["title"], "Renamed task")
		self.assertTrue(all(x["_rev"] for x in doc["schedules"]["doc-a"]["items"]))

	def test_concurrent_changes_to_different_tasks_both_land(self):
		revs = { "a1": self.rev_of_item("a1"), "a2": self.rev_of_item("a2") }
		results = {}
		def patch(ident):
			results[ident] = self.client.patch(f"{BASE}/doc-a/items/{ident}", json={ "title": f"T-{ident}", "_rev": revs[ident] }).status_code
		threads = [threading.Thread(target=patch, args=(i,)) for i in revs]
		for t in threads: t.start()
		for t in threads: t.join()
		self.assertEqual(results, { "a1": 200, "a2": 200 })
		self.assertEqual([x["title"] for x in self.stored()["items"]], ["T-a1", "T-a2"])

class TestPure(unittest.TestCase):
	def test_merge_patch_rfc7396(self):
		self.assertEqual(merge_patch({ "a": 1, "b": { "c": 2, "d": 3 } }, { "b": { "c": None, "e": 4 }, "f": [1] }), { "a": 1, "b": { "d": 3, "e": 4 }, "f": [1] })
		self.assertEqual(merge_patch({ "a": [1, 2] }, { "a": [3] }), { "a": [3] })

	def test_shape_checks_never_echo_values(self):
		errors = check_item_shape({ "title": 5, "trigger": "secret-value", "task": "secret-value", "zzz": "secret-value" })
		self.assertNotIn("secret-value", json.dumps(errors))

if __name__ == "__main__":
	unittest.main()
