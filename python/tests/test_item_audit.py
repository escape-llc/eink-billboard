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
import re
import unittest
from collections import defaultdict
from typing import Any

from ..model.configuration_manager import ConfigurationManager
from ..web.documents import content_with_defaults

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
STORAGES = [os.path.join(ROOT, "tests", "fixtures", "storage"), os.path.join(REPO, "app", "e2e", "fixtures", "storage")]

# required, and the user supplies the value: a track or task of this source is not valid until they do
USER_SUPPLIED = {
	("source", "clock", "clockFace"), ("source", "clock", "primaryColor"), ("source", "clock", "secondaryColor"),
	("source", "countdown", "title"), ("source", "countdown", "targetDate"),
	("source", "image-folder", "folder"), ("source", "ai-image", "prompt"), ("source", "rss", "feed"),
	("source", "today", "customFormat"),
}
# one name, different shapes (each is one form at a time, and a change of plugin or data source resets the form's values):
SAME_NAME_DIFFERENT = {
	"fontSize": "the comic's is a size in points, the others a choice of sizes",
	"title": "the countdown needs one; for the rest it is an optional heading",
	"views": "the calendar's views and the weather's are different pages",
	"showAs": "the choices differ by layer: a playlist page, or a timer task's image",
	"slideMinutes": "the default differs: a playlist slot, or a priority image",
	"imageModel": "each provider's own image models (OpenAI, Google), chosen from its own list",
	"textModel": "each provider's own text models (OpenAI, Google), chosen from its own list",
}
TYPES: dict[str, Any] = { "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list }

def properties(info: dict) -> list[dict]:
	return [p for p in (info.get("instanceSettings") or {}).get("schema", {}).get("properties", []) if p.get("type") != "header"]

def choices(info: dict) -> dict[str, list[str]]:
	"""A data source's `schema` fields that choose other data sources (its parts): the field's name and the features its lookup asks for."""
	schema = (info.get("instanceSettings") or {}).get("schema", {})
	lookups = schema.get("lookups") or {}
	return { p["name"]: list((lookups.get(p.get("lookup")) or {}).get("features") or []) for p in schema.get("properties", []) if p.get("type") == "schema" }

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

class TestUses(unittest.TestCase):
	"""A data source that asks another says so in its descriptor (`uses`): the form can warn when the other is missing, and a cycle cannot be built."""
	def test_a_used_source_exists_is_not_itself_and_nothing_uses_in_a_circle(self):
		graph = { id_: list(info.get("uses") or []) for id_, info in DESCRIPTORS.sources.items() }
		for id_, used in graph.items():
			for other in used:
				self.assertIn(other, DESCRIPTORS.sources, f"{id_} uses {other}: no such data source")
				self.assertNotEqual(other, id_)
		def reaches(start: str, seen: set[str]) -> bool:
			for other in graph.get(start, []):
				if other in seen or reaches(other, seen | { other }):
					return True
			return False
		for id_ in graph:
			self.assertFalse(reaches(id_, { id_ }), f"{id_} uses itself through others")

	def test_a_source_whose_code_asks_another_declares_it(self):
		for id_, info in DESCRIPTORS.sources.items():
			path = os.path.join(ROOT, *info["module"].split(".")[1:]) + ".py"
			with open(path, encoding="utf-8") as f:
				# the code, not the docstrings that name the method
				code = re.sub(r'"""[\s\S]*?"""', "", f.read())
			asks = ".use(" in code or ".context_for(" in code
			# a source that chooses its parts (a `schema` field: the Generated Image's text and image sources) asks what the task chose, which no descriptor can name
			self.assertEqual(asks, bool(info.get("uses")) or bool(choices(info)), f"{id_}: `uses` in the descriptor must match whether the code asks another data source")

	def test_a_source_and_the_parts_it_can_choose_share_no_field_name(self):
		# every level's fields are in the one task content: a name in two levels would be one value for both
		for id_, info in DESCRIPTORS.sources.items():
			mine = { p["name"] for p in properties(info) }
			parts = { lookup: [s for s in DESCRIPTORS.sources.values() if set(features) & set(s.get("features") or [])] for lookup, features in choices(info).items() }
			for lookup, offered in parts.items():
				for part in offered:
					with self.subTest(source=id_, part=part["id"]):
						self.assertEqual(mine & { p["name"] for p in properties(part) }, set())
			# and the parts of one choice share none with the parts of another (a text part and an image part are in one task)
			kinds = list(parts.values())
			for n, these in enumerate(kinds):
				for those in kinds[n + 1:]:
					for a in these:
						for b in those:
							with self.subTest(source=id_, parts=(a["id"], b["id"])):
								self.assertEqual({ p["name"] for p in properties(a) } & { p["name"] for p in properties(b) }, set())

# a list source whose list is made fresh every slot (a view of now), so it is not kept; every other list is shown item by item until it is used up, then fetched again
NOT_KEPT = { "calendar": "its pages are views of now", "weather": "its pages are views of now" }

class TestKeptLists(unittest.TestCase):
	def test_every_list_source_is_kept_unless_it_is_a_view_of_now(self):
		lists = { id_ for id_, info in DESCRIPTORS.sources.items() if "media-list" in (info.get("features") or []) }
		kept = { id_ for id_ in lists if DESCRIPTORS.sources[id_].get("keepsList") is True }
		self.assertEqual(lists - kept, set(NOT_KEPT), "a list source is kept (`keepsList`), or listed in NOT_KEPT with the reason")
		self.assertEqual(kept, { "rss", "image-folder", "comic" })

	def test_a_kept_list_is_fetched_again_only_when_used_up_unless_the_task_says_otherwise(self):
		refresh = next(p for p in properties(DESCRIPTORS.plugins["slide-show"]) if p["name"] == "refreshHours")
		self.assertEqual(refresh["default"], 0)

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

class TestRunTimeDefaults(unittest.TestCase):
	"""An item that lacks a property runs at the descriptor's default, as the form would show and save it."""
	def _maps(self):
		return { k: { "info": v } for k, v in DESCRIPTORS.plugins.items() }, { k: { "info": v } for k, v in DESCRIPTORS.sources.items() }

	def test_a_missing_property_takes_the_descriptors_default_and_a_set_one_is_kept(self):
		plugins, sources = self._maps()
		filled = content_with_defaults(plugins, sources, "slide-show", { "dataSource": "comic-xkcd", "slideMinutes": 3 })
		slide = { p["name"]: p for p in properties(DESCRIPTORS.plugins["slide-show"]) }
		self.assertEqual(filled["refreshHours"], slide["refreshHours"]["default"])
		self.assertEqual(filled["slideMax"], slide["slideMax"]["default"])
		self.assertEqual(filled["slideMinutes"], 3)

	def test_nothing_is_added_that_has_no_default_or_is_hidden_or_the_item_is_unchanged(self):
		plugins, sources = self._maps()
		for kind, id_, info in DESCRIPTORS.all():
			if kind != "plugin":
				continue
			content = { "dataSource": "nothing" }
			filled = content_with_defaults(plugins, sources, id_, content)
			self.assertEqual(content, { "dataSource": "nothing" }, "the stored item is not changed")
			props = { p["name"]: p for p in properties(info) }
			for name in filled:
				if name not in content:
					self.assertIsNotNone(props[name].get("default"), f"{id_}.{name}")

	def test_an_item_that_is_complete_is_returned_as_it_is(self):
		plugins, sources = self._maps()
		full = { p["name"]: p.get("default") for p in properties(DESCRIPTORS.plugins["slide-show"]) }
		self.assertEqual(content_with_defaults(plugins, sources, "slide-show", dict(full)), full)

	def test_an_unknown_plugin_is_left_alone(self):
		self.assertEqual(content_with_defaults({}, {}, "nope", { "a": 1 }), { "a": 1 })

if __name__ == "__main__":
	unittest.main()
