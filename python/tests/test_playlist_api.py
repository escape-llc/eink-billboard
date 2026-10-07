import json
import os
import unittest

from .test_schedule_api import CONTENT, ScheduleApiBase
from .test_web_api import _error_shape

BASE = "/api/schedule/playlist"

def track(ident: str|None = None, title: str = "T", **over) -> dict:
	body = { "title": title, "plugin_name": "slide-show", "content": dict(CONTENT) }
	if ident:
		body["id"] = ident
	body.update(over)
	return body

class TestPlaylistDocument(ScheduleApiBase):
	"""A playlist is a self-contained document: it is read and saved whole, tracks and their order included."""
	def setUp(self):
		super().setUp()
		path = os.path.join(self.storage, "schedules", "pl.json")
		with open(path, "w", encoding="utf-8") as f:
			json.dump({ "_schema": "urn:inky:storage:schedule:playlist:1", "id": "pl", "name": "Playlist", "items": [
				{ "type": "PlaylistSchedule", "id": "t1", "title": "One", "plugin_name": "slide-show", "content": dict(CONTENT) },
				{ "type": "PlaylistSchedule", "id": "t2", "title": "Two", "plugin_name": "slide-show", "content": dict(CONTENT) } ] }, f)

	def stored_pl(self) -> dict:
		with open(os.path.join(self.storage, "schedules", "pl.json"), encoding="utf-8") as f:
			return json.load(f)

	def doc_pl(self) -> dict:
		return self.client.get(f"{BASE}/pl").json()["schedule"]

	def test_list_and_get_have_revisions(self):
		listed = self.client.get(f"{BASE}/list").json()["playlists"]
		self.assertEqual([d["id"] for d in listed], ["pl"])
		doc = self.doc_pl()
		self.assertEqual(doc["_rev"], listed[0]["_rev"])
		self.assertEqual([x["id"] for x in doc["items"]], ["t1", "t2"])
		self.assertTrue(all(x["_rev"] for x in doc["items"]))

	def test_save_whole_changes_tracks_and_their_order(self):
		doc = self.doc_pl()
		items = [doc["items"][1], track(None, "New track"), { **doc["items"][0], "title": "One, renamed" }]
		resp = self.client.put(f"{BASE}/pl", json={ "name": "Playlist", "_rev": doc["_rev"], "items": items })
		self.assertEqual(resp.status_code, 200, resp.text)
		saved = self.stored_pl()
		self.assertEqual([x["title"] for x in saved["items"]], ["Two", "New track", "One, renamed"])
		self.assertEqual({x["type"] for x in saved["items"]}, {"PlaylistSchedule"})
		self.assertEqual(saved["items"][0]["id"], "t2")
		self.assertTrue(saved["items"][1]["id"])
		self.assertNotIn("_rev", saved["items"][0])
		self.assertEqual(resp.json()["schedule"]["_rev"], resp.json()["rev"])

	def test_a_stale_rev_is_a_conflict_with_the_current_one(self):
		doc = self.doc_pl()
		first = self.client.put(f"{BASE}/pl", json={ "name": "Renamed", "_rev": doc["_rev"], "items": doc["items"] })
		body = _error_shape(self, self.client.put(f"{BASE}/pl", json={ "name": "Mine", "_rev": doc["_rev"], "items": doc["items"] }), 409)
		self.assertEqual(body["rev"], first.json()["rev"])
		self.assertEqual(self.stored_pl()["name"], "Renamed")

	def test_validation_paths_are_in_the_document(self):
		doc = self.doc_pl()
		def errors(items):
			body = _error_shape(self, self.client.put(f"{BASE}/pl", json={ "name": "x", "_rev": doc["_rev"], "items": items }), 422)
			return {(tuple(e["path"]), e["message"]) for e in body["errors"]}
		self.assertIn((("items", "1", "plugin_name"), "Unknown plugin"), errors([track("a"), track("b", plugin_name="nope")]))
		self.assertIn((("items", "0", "content", "slideMinutes"), "Minimum 1"), errors([track("a", content={ **CONTENT, "slideMinutes": 0 })]))
		self.assertIn((("items", "0", "content", "folder"), "Required"), errors([track("a", content={ "dataSource": "image-folder", "slideMax": 1, "slideMinutes": 1 })]))
		self.assertIn((("items", "0", "surprise"), "Unknown property"), errors([track("a", surprise=1)]))
		self.assertIn((("items", "0", "type"), "Unknown track type"), errors([track("a", type="Other")]))
		self.assertIn((("items", "1", "id"), "Duplicate id"), errors([track("a"), track("a")]))
		self.assertEqual(len(self.stored_pl()["items"]), 2)

	def test_create_rename_delete(self):
		created = self.client.post(BASE, json={ "name": "Fresh", "items": [track(None, "First")] })
		self.assertEqual(created.status_code, 201, created.text)
		doc = created.json()["schedule"]
		self.assertTrue(doc["id"].startswith("playlist-"))
		self.assertTrue(os.path.isfile(os.path.join(self.storage, "schedules", f"{doc['id']}.json")))
		renamed = self.client.patch(f"{BASE}/{doc['id']}", json={ "name": "Renamed", "_rev": doc["_rev"] })
		self.assertEqual(renamed.status_code, 200, renamed.text)
		_error_shape(self, self.client.delete(f"{BASE}/{doc['id']}", params={ "rev": doc["_rev"] }), 409)
		self.assertEqual(self.client.delete(f"{BASE}/{doc['id']}", params={ "rev": renamed.json()["rev"] }).status_code, 200)
		_error_shape(self, self.client.get(f"{BASE}/{doc['id']}"), 404)

	def test_a_timer_task_document_is_not_a_playlist_and_the_other_way_round(self):
		_error_shape(self, self.client.get(f"{BASE}/doc-a"), 404)
		_error_shape(self, self.client.get(f"/api/schedule/timer/pl"), 404)

	def test_there_are_no_single_track_routes(self):
		self.assertEqual(self.client.get(f"{BASE}/pl/items/t1").status_code, 404)
		self.assertEqual(self.client.post(f"{BASE}/pl/items", json=track()).status_code, 404)

if __name__ == "__main__":
	unittest.main()
