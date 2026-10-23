"""
A plugin's setting that only means something for one kind of data source (the Slide Show's list settings: a picture of the day has no list) is shown, validated and
kept only when the source the task chose is that kind: a predicate reads `<schema field>.keepsList` and `<schema field>.features`, derived from the chosen source
(`app/src/components/FormVisibility.ts` derives the same).
"""
import unittest

from ..model.configuration_manager import ConfigurationManager
from ..web.documents import content_with_defaults, plugin_content_errors
from ..web.visibility import derive, find_problems, hidden_names

SOURCES = {
	"feed": { "info": { "id": "feed", "features": ["layer-foreground", "media-list"], "keepsList": True } },
	"day": { "info": { "id": "day", "features": ["layer-background", "media-image"] } },
}
PROPS = [
	{ "name": "dataSource", "type": "schema", "lookup": "dataSource" },
	{ "name": "listMode", "type": "string", "visibleIf": { "field": "dataSource.keepsList", "const": True } },
	{ "name": "listy", "type": "string", "visibleIf": { "field": "dataSource.features", "contains": "media-list" } },
]

class TestDerived(unittest.TestCase):
	def test_the_values_come_from_the_source_the_field_chose(self):
		self.assertEqual({ k: v for k, v in derive(PROPS, { "dataSource": "feed" }, SOURCES).items() if "." in k },
			{ "dataSource.features": ["layer-foreground", "media-list"], "dataSource.keepsList": True })
		self.assertEqual(derive(PROPS, { "dataSource": "day" }, SOURCES)["dataSource.keepsList"], False)
		# nothing chosen, or not a source: no features, not kept
		for chosen in ({}, { "dataSource": None }, { "dataSource": "nothing" }, { "dataSource": 7 }):
			derived = derive(PROPS, chosen, SOURCES)
			self.assertEqual((derived["dataSource.features"], derived["dataSource.keepsList"]), ([], False), chosen)

	def test_a_setting_for_lists_is_hidden_for_a_source_without_one(self):
		self.assertEqual(hidden_names(PROPS, derive(PROPS, { "dataSource": "feed" }, SOURCES)), set())
		self.assertEqual(hidden_names(PROPS, derive(PROPS, { "dataSource": "day" }, SOURCES)), { "listMode", "listy" })
		self.assertEqual(hidden_names(PROPS, derive(PROPS, {}, SOURCES)), { "listMode", "listy" })

	def test_a_derived_name_is_not_an_unknown_field_but_a_made_up_one_is(self):
		self.assertEqual(find_problems(PROPS), [])
		bad = [{ "name": "a", "type": "string" }, { "name": "b", "type": "string", "visibleIf": { "field": "a.features", "contains": "x" } }]
		self.assertIn("unknown field 'a.features'", find_problems(bad)[0], "only a `schema` property has derived values")
		worse = [*PROPS, { "name": "c", "type": "string", "visibleIf": { "field": "dataSource.colour", "const": 1 } }]
		self.assertIn("unknown field 'dataSource.colour'", find_problems(worse)[0])

class TestTheSlideShow(unittest.TestCase):
	def setUp(self):
		items = ConfigurationManager()
		self.plugins = { i["info"]["id"]: i for i in items.enum_plugins() }
		self.sources = { i["info"]["id"]: i for i in items.enum_datasources() }

	def errors(self, content: dict) -> list:
		return plugin_content_errors(self.plugins, self.sources, "slide-show", content, [])

	def test_list_settings_are_checked_only_for_a_source_with_a_list(self):
		base = { "slideMax": 2, "slideMinutes": 1, "showAs": "auto" }
		paths = lambda content: [e["path"] for e in self.errors(content)]
		self.assertIn(["content", "listMode"], paths({ **base, "dataSource": "rss", "feed": "x", "listMode": "sideways" }))
		self.assertIn(["content", "refreshHours"], paths({ **base, "dataSource": "rss", "feed": "x", "listMode": "continue", "refreshHours": -5 }))
		# a picture of the day has no list: its stored list settings are not applicable, so not wrong
		stale = { **base, "dataSource": "nasa-apod", "listMode": "sideways", "refreshHours": -5 }
		self.assertEqual([p for p in paths(stale) if p[-1] in ("listMode", "refreshHours")], [])

	def test_the_defaults_of_a_list_setting_are_added_only_for_a_source_with_a_list(self):
		with_list = content_with_defaults(self.plugins, self.sources, "slide-show", { "dataSource": "comic" })
		without = content_with_defaults(self.plugins, self.sources, "slide-show", { "dataSource": "nasa-apod" })
		self.assertEqual((with_list["listMode"], with_list["refreshHours"]), ("continue", 0))
		self.assertTrue("listMode" not in without and "refreshHours" not in without)
		self.assertIn("slideMax", with_list, "a source of several pages has a count")
		self.assertNotIn("slideMax", without, "a source of one picture shows one slide")
