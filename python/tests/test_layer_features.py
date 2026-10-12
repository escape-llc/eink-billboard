import glob
import json
import os
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..")

def load(kind: str, name: str) -> list[dict]:
	found = []
	for path in sorted(glob.glob(os.path.join(BASE, kind, "*", name))):
		with open(path, encoding="utf-8") as f:
			found.append(json.load(f))
	return found

PLUGINS = { p["id"]: p for p in load("plugins", "plugin-info.json") }
SOURCES = load("datasources", "datasource-info.json")

def offered(plugin: dict) -> list[dict]:
	"""The data sources the plugin's form offers: the ones that have one of the lookup's features (the same rule as the form and the server)."""
	wanted = plugin["instanceSettings"]["schema"]["lookups"]["dataSource"]["features"]
	return [s for s in SOURCES if set(wanted) & set(s.get("features") or [])]

def layers(features: list[str]) -> set[str]:
	return {f for f in features if f.startswith("layer-")}

def media(features: list[str]) -> set[str]:
	return {f for f in features if f.startswith("media-")}

class TestPluginsAndSourcesAgree(unittest.TestCase):
	"""
	A plugin is offered the data sources of the layer it works on (its lookup asks for `layer-*`), and it advertises the media it handles
	(`media-image`, `media-list`, `media-overlay`): what it offers must be something it knows how to handle.
	"""
	def test_each_plugin_asks_for_its_own_layers(self):
		self.assertEqual(PLUGINS["overlay"]["instanceSettings"]["schema"]["lookups"]["dataSource"]["features"], ["layer-overlay"])
		self.assertEqual(PLUGINS["interstitial"]["instanceSettings"]["schema"]["lookups"]["dataSource"]["features"], ["layer-priority"])
		self.assertEqual(sorted(PLUGINS["slide-show"]["instanceSettings"]["schema"]["lookups"]["dataSource"]["features"]), ["layer-background", "layer-foreground"])

	def test_a_plugin_asks_only_for_layers_it_advertises(self):
		for plugin in PLUGINS.values():
			wanted = set(plugin["instanceSettings"]["schema"]["lookups"]["dataSource"]["features"])
			with self.subTest(plugin["id"]):
				self.assertTrue(wanted <= layers(plugin["features"]), f"{plugin['id']} asks for {wanted} but advertises {layers(plugin['features'])}")

	def test_every_offered_source_has_media_the_plugin_handles(self):
		for plugin in PLUGINS.values():
			handled = media(plugin["features"])
			self.assertTrue(handled, f"{plugin['id']} advertises no media it handles")
			for source in offered(plugin):
				with self.subTest(f"{plugin['id']} offers {source['id']}"):
					self.assertTrue(media(source["features"]) & handled, f"{source['id']} offers {media(source['features'])}, {plugin['id']} handles {handled}")

	def test_every_source_declares_a_layer_and_its_media(self):
		for source in SOURCES:
			with self.subTest(source["id"]):
				self.assertTrue(layers(source["features"]), "no layer-* feature")
				self.assertTrue(media(source["features"]), "no media-* feature")

	def test_every_source_is_offered_by_a_plugin_of_its_layer(self):
		for source in SOURCES:
			with self.subTest(source["id"]):
				self.assertTrue(any(source in offered(p) for p in PLUGINS.values()), "no plugin offers it")

	def test_a_background_only_source_is_never_offered_to_a_timer_task(self):
		for plugin in PLUGINS.values():
			if layers(plugin["features"]) & {"layer-priority", "layer-overlay"}:
				for source in offered(plugin):
					with self.subTest(f"{plugin['id']} offers {source['id']}"):
						self.assertNotEqual(layers(source["features"]), {"layer-background"})

	def test_the_today_source_is_an_overlay_source_only(self):
		today = next(s for s in SOURCES if s["id"] == "today")
		self.assertIn("layer-overlay", today["features"])
		self.assertEqual(layers(today["features"]), {"layer-overlay"})
