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

def is_api(source: dict) -> bool:
	"""An API data source (`DataSourceApi`): data for other sources, drawn by none of its own."""
	return "api" in (source.get("features") or [])

class TestApiDataSources(unittest.TestCase):
	"""An API data source is data only: no layer, no media, no plugin offers it; its class answers `open_async` and draws nothing; another source uses it."""
	def test_an_api_source_has_no_layer_or_media_and_no_plugin_offers_it(self):
		apis = [s for s in SOURCES if is_api(s)]
		self.assertTrue(apis)
		for source in apis:
			with self.subTest(source["id"]):
				self.assertEqual((layers(source["features"]), media(source["features"])), (set(), set()))
				self.assertFalse(any(source in offered(p) for p in PLUGINS.values()))

	def test_its_class_is_data_only(self):
		import importlib
		from ..datasources.data_source import DataSourceApi
		for source in (s for s in SOURCES if is_api(s)):
			with self.subTest(source["id"]):
				kind = getattr(importlib.import_module(source["module"]), source["class"])
				self.assertTrue(issubclass(kind, DataSourceApi), "implements DataSourceApi")
				self.assertFalse(hasattr(kind, "render_async"), "an API data source renders nothing")

	def test_another_source_uses_it(self):
		# by name (`uses`), or by feature: a source's own `schema` field chooses it (the Generated Image's text and image parts)
		chosen = { f for s in SOURCES for lk in ((s.get("instanceSettings") or {}).get("schema", {}).get("lookups") or {}).values()
			if isinstance(lk, dict) and lk.get("schema") == "data-sources" for f in lk.get("features") or [] }
		used = { u for s in SOURCES for u in (s.get("uses") or []) } | { s["id"] for s in SOURCES if chosen & set(s.get("features") or []) }
		for source in (s for s in SOURCES if is_api(s)):
			with self.subTest(source["id"]):
				self.assertIn(source["id"], used, "no data source uses it")

class TestPluginsAndSourcesAgree(unittest.TestCase):
	"""
	A plugin is offered the data sources of the layer it works on (its lookup asks for `layer-*`), and it advertises the media it handles
	(`media-image`, `media-list`): what it offers must be something it knows how to handle.
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
			if is_api(source):
				continue
			with self.subTest(source["id"]):
				self.assertTrue(layers(source["features"]), "no layer-* feature")
				self.assertTrue(media(source["features"]), "no media-* feature")

	def test_every_source_is_offered_by_a_plugin_of_its_layer(self):
		for source in SOURCES:
			if is_api(source):
				continue
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

# the words a data source's `features` may use, in the order a descriptor lists them: what it needs, what it is, where it can be shown, what it makes.
# (The Data Source settings tab explains each in a tooltip: app/src/components/ItemInfo.vue.)
VOCABULARY = (
	"internet", "filesystem", "api-key", "paid-service",
	"api", "api-client", "ai-provider", "ai-text", "ai-image",
	"layer-background", "layer-foreground", "layer-priority", "layer-overlay",
	"media-image", "media-list",
)

class TestFeatureVocabulary(unittest.TestCase):
	"""The feature lists say the same thing the same way: a source that asks an API data source for its data says so (`api-client`) and does not also claim the internet."""
	def test_every_feature_is_a_known_word_listed_in_order_without_repeats(self):
		for source in SOURCES:
			with self.subTest(source["id"]):
				features = source["features"]
				self.assertEqual(len(features), len(set(features)))
				self.assertEqual([f for f in features if f not in VOCABULARY], [])
				self.assertEqual(features, sorted(features, key=VOCABULARY.index), "listed in the vocabulary's order")

	def test_api_client_is_what_asks_an_api_source(self):
		api_ids = { s["id"] for s in SOURCES if is_api(s) }
		for source in SOURCES:
			lookups = ((source.get("instanceSettings") or {}).get("schema", {}).get("lookups") or {}).values()
			chooses_parts = any(isinstance(lk, dict) and lk.get("schema") == "data-sources" and any(f.startswith("ai-") for f in lk.get("features") or []) for lk in lookups)
			asks = bool(set(source.get("uses") or []) & api_ids) or chooses_parts
			with self.subTest(source["id"]):
				self.assertEqual("api-client" in source["features"], asks, "`api-client` exactly when it uses an API source (or chooses AI parts)")
				if asks:
					self.assertNotIn("internet", source["features"], "it asks an API source: that one downloads")

	def test_what_only_an_api_source_is(self):
		for source in SOURCES:
			features = set(source["features"])
			with self.subTest(source["id"]):
				if features & {"ai-provider", "ai-text", "ai-image", "api-key"}:
					self.assertIn("api", features, "a key, a provider or an AI part is a data-only API source")
				# somewhere to show it and what it shows come together
				self.assertEqual(bool(layers(source["features"])), bool(media(source["features"])))
