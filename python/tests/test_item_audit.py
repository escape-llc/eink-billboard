"""
The properties of playlist and timer items, audited against the descriptors: what a plugin and a data source declare (`instanceSettings`), and the stored items that
fill them in (the test storage and the browser tests' storage). The conventions here are the ones the form depends on:

- every property says what it is (`title`, and `description` unless it is a lookup of other things) and carries a `default` key (null where the user must supply it);
- a required property without a default is deliberate: it is listed here, so a new one is a decision, not an accident;
- one name means one thing: the form keeps a field's state by its name, so two properties of the same name must not differ (type, choices) unless it is listed with the reason;
- a stored item has no property the schema does not define (it would be listed as no longer used and left out on save) and lacks no required one.
"""
import json
import os
import unittest
from collections import defaultdict
from typing import Any

from ..model.configuration_manager import ConfigurationManager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
STORAGES = [os.path.join(ROOT, "tests", "fixtures", "storage"), os.path.join(REPO, "app", "e2e", "fixtures", "storage")]

# required, and the user supplies the value: a track or task of this source is not valid until they do
USER_SUPPLIED = {
	("source", "clock", "clockFace"), ("source", "clock", "primaryColor"), ("source", "clock", "secondaryColor"),
	("source", "countdown", "title"), ("source", "countdown", "targetDate"),
	("source", "image-folder", "folder"), ("source", "openai-image", "prompt"), ("source", "rss", "feed"),
	("source", "today", "customFormat"),
}
# one name, different shapes (each is one form at a time, and a change of plugin or data source resets the form's values):
SAME_NAME_DIFFERENT = {
	"fontSize": "the comic's is a size in points, the others a choice of sizes",
	"title": "the countdown needs one; for the rest it is an optional heading",
	"views": "the calendar's views and the weather's are different pages",
	"showAs": "the choices differ by layer: a playlist page, or a timer task's image",
	"slideMinutes": "the default differs: a playlist slot, or a priority image",
}
TYPES: dict[str, Any] = { "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list }

def properties(info: dict) -> list[dict]:
	return [p for p in (info.get("instanceSettings") or {}).get("schema", {}).get("properties", []) if p.get("type") != "header"]

class Descriptors:
	def __init__(self):
		cm = ConfigurationManager()
		self.plugins = { p["info"]["id"]: p["info"] for p in cm.enum_plugins() }
		self.sources = { d["info"]["id"]: d["info"] for d in cm.enum_datasources() }
	def all(self):
		for id_, info in self.plugins.items():
			yield "plugin", id_, info
		for id_, info in self.sources.items():
			yield "source", id_, info

DESCRIPTORS = Descriptors()

class TestDescriptors(unittest.TestCase):
	def test_every_property_says_what_it_is_and_carries_a_default(self):
		problems = []
		for kind, id_, info in DESCRIPTORS.all():
			for p in properties(info):
				where = f"{kind} {id_}.{p['name']}"
				if not p.get("title"):
					problems.append(f"{where}: no title")
				if p.get("type") != "schema" and not p.get("description"):
					problems.append(f"{where}: no description")
				if "default" not in p:
					problems.append(f"{where}: no `default` (null where the user supplies it)")
		self.assertEqual(problems, [])

	def test_a_required_property_without_a_default_is_listed_here(self):
		found = { (kind, id_, p["name"]) for kind, id_, info in DESCRIPTORS.all() for p in properties(info)
			if p.get("required") and p.get("default") is None and p.get("type") != "schema" }
		self.assertEqual(found - USER_SUPPLIED, set(), "a new property the user must fill in: add it to USER_SUPPLIED on purpose")
		self.assertEqual(USER_SUPPLIED - found, set(), "no longer required without a default: remove it from USER_SUPPLIED")

	def test_one_name_means_one_thing(self):
		shapes: dict[str, set[tuple]] = defaultdict(set)
		for kind, id_, info in DESCRIPTORS.all():
			for p in properties(info):
				shapes[p["name"]].add((p.get("type"), json.dumps(p.get("enum")), json.dumps((p.get("items") or {}).get("enum")), p.get("required"), json.dumps(p.get("default")), p.get("lookup")))
		differing = { name for name, s in shapes.items() if len(s) > 1 }
		self.assertEqual(differing - set(SAME_NAME_DIFFERENT), set(), "two properties of one name differ: rename one, or list it in SAME_NAME_DIFFERENT with the reason")
		self.assertEqual(set(SAME_NAME_DIFFERENT) - differing, set(), "no longer different: remove it from SAME_NAME_DIFFERENT")

	def test_a_plugin_and_its_data_sources_share_no_property_name(self):
		for pid, plugin in DESCRIPTORS.plugins.items():
			mine = { p["name"] for p in properties(plugin) }
			for sid, source in DESCRIPTORS.sources.items():
				self.assertEqual(mine & { p["name"] for p in properties(source) }, set(), f"{pid} and {sid} are shown in one form and name the same property")

class TestStoredItems(unittest.TestCase):
	def _items(self):
		for storage in STORAGES:
			folder = os.path.join(storage, "schedules")
			for name in sorted(os.listdir(folder)):
				with open(os.path.join(folder, name), encoding="utf-8") as f:
					doc = json.load(f)
				for item in doc.get("items", []):
					content = item.get("content") if "content" in item else (item.get("task") or {}).get("content")
					plugin = item.get("plugin_name") if "content" in item else (item.get("task") or {}).get("plugin_name")
					yield f"{os.path.relpath(os.path.join(folder, name), REPO)} '{item.get('title')}'", plugin, content or {}

	def _schema(self, plugin_id: str, content: dict) -> dict[str, dict]:
		names = {}
		for info in (DESCRIPTORS.plugins.get(plugin_id), DESCRIPTORS.sources.get(str(content.get("dataSource")))):
			for p in properties(info or {}):
				names[p["name"]] = p
		return names

	def test_there_are_items_to_audit(self):
		self.assertGreater(len(list(self._items())), 8)

	def test_an_item_has_no_property_the_schema_does_not_define(self):
		unknown = [f"{where}: {name}" for where, plugin, content in self._items() for name in content if name not in self._schema(plugin, content)]
		self.assertEqual(unknown, [])

	def test_an_item_lacks_no_required_property_and_its_values_have_the_declared_type(self):
		problems = []
		for where, plugin, content in self._items():
			for name, p in self._schema(plugin, content).items():
				if name not in content:
					if p.get("required") and p.get("default") is None and "visibleIf" not in p:
						problems.append(f"{where}: lacks required {name}")
				elif content[name] is not None and p.get("type") in TYPES and not isinstance(content[name], TYPES[p["type"]]):
					problems.append(f"{where}: {name} is {type(content[name]).__name__}, declared {p['type']}")
		self.assertEqual(problems, [])

if __name__ == "__main__":
	unittest.main()
