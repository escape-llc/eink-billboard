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

def capabilities(features: list[str]) -> set[str]:
	"""What a provider supplies (`data-weather`, `data-ai-text`): a source that needs one says so in `requires`, and any provider of it will do."""
	return {f for f in features if f.startswith("data-")}

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
		# or by capability: a source requires what it supplies, and asks for whichever provider of it (`dsec.provide`)
		chosen |= { c for s in SOURCES for c in s.get("requires") or [] }
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
	"api", "api-client", "ai-provider", "data-weather", "data-calendar", "data-ai-text", "data-ai-image",
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

	def test_every_capability_has_its_contract(self):
		from ..datasources.contracts import CONTRACTS
		self.assertEqual({ f for f in VOCABULARY if f.startswith("data-") }, set(CONTRACTS))

	def test_api_client_is_what_asks_an_api_source(self):
		api_ids = { s["id"] for s in SOURCES if is_api(s) }
		for source in SOURCES:
			lookups = ((source.get("instanceSettings") or {}).get("schema", {}).get("lookups") or {}).values()
			chooses_parts = any(isinstance(lk, dict) and lk.get("schema") == "data-sources" and any(f.startswith("data-") for f in lk.get("features") or []) for lk in lookups)
			asks = bool(set(source.get("uses") or []) & api_ids) or chooses_parts or bool(source.get("requires"))
			with self.subTest(source["id"]):
				self.assertEqual("api-client" in source["features"], asks, "`api-client` exactly when it uses an API source (or chooses AI parts)")
				if asks:
					self.assertNotIn("internet", source["features"], "it asks an API source: that one downloads")

	def test_what_only_an_api_source_is(self):
		for source in SOURCES:
			features = set(source["features"])
			with self.subTest(source["id"]):
				if features & {"ai-provider", "api-key"} or capabilities(source["features"]):
					self.assertIn("api", features, "a key, a provider or a capability is a data-only API source")
				# somewhere to show it and what it shows come together
				self.assertEqual(bool(layers(source["features"])), bool(media(source["features"])))

# only a provider is used by id (`uses`): none is excepted since the calendar was split into a provider and its pages (#513)
USED_THOUGH_NOT_A_PROVIDER: set[str] = set()

def chosen_capabilities(source: dict) -> set[str]:
	"""The capabilities a source's own `schema` fields choose a provider of (the Generated Image's text and image parts)."""
	lookups = ((source.get("instanceSettings") or {}).get("schema", {}).get("lookups") or {}).values()
	return { f for lk in lookups if isinstance(lk, dict) and lk.get("schema") == "data-sources" for f in capabilities(lk.get("features") or []) }

def capability_problems(sources: list[dict]) -> list[str]:
	"""
	What breaks the rules of providers and data sources (#513), in words: a **provider** has `api` (data only, no layer: the other tests),
	a **data source** has a `layer-*`; a capability is a `data-*` feature, supplied only by providers; a source names the capabilities it
	needs in `requires`, each of which some provider supplies (it asks with `dsec.provide`, or a `schema` field chooses one); a prompt's `tokensFrom` names
	capabilities.
	"""
	by_id = { s["id"]: s for s in sources }
	providers = { c: [s["id"] for s in sources if is_api(s) and c in s.get("features", [])] for s in sources for c in capabilities(s.get("features") or []) }
	problems: list[str] = []
	for source in sources:
		sid, features, requires = source["id"], source.get("features") or [], source.get("requires") or []
		problems += [f"{sid}: unknown feature {f}" for f in features if f not in VOCABULARY]
		if is_api(source) == bool(layers(features)):
			problems.append(f"{sid}: neither a provider (api) nor a data source (layer-*), or both")
		if capabilities(features) and not is_api(source):
			problems.append(f"{sid}: supplies {sorted(capabilities(features))} but is not a provider (api)")
		problems += [f"{sid}: requires {c}, which is not a capability (data-*)" for c in requires if not c.startswith("data-")]
		problems += [f"{sid}: requires {c}, which no provider supplies" for c in requires if c.startswith("data-") and not providers.get(c)]
		problems += [f"{sid}: chooses a provider of {c} but does not require it" for c in sorted(chosen_capabilities(source) - set(requires))]
		props = ((source.get("instanceSettings") or {}).get("schema") or {}).get("properties") or []
		problems += [f"{sid}: {p['name']} takes its fields from {c}, which is not a capability" for p in props for c in p.get("tokensFrom") or [] if c not in VOCABULARY or not c.startswith("data-")]
		problems += [f"{sid}: {p['name']} takes its fields from {c}, which it does not require" for p in props for c in p.get("tokensFrom") or [] if c.startswith("data-") and c not in requires]
		problems += [f"{sid}: uses {u}, which is not a provider (api)" for u in source.get("uses") or []
			if u in by_id and not is_api(by_id[u]) and u not in USED_THOUGH_NOT_A_PROVIDER]
	return problems

class TestCapabilities(unittest.TestCase):
	"""Providers supply capabilities (`data-*`), data sources require them (#513): every rule holds for the descriptors, and each one catches a broken descriptor."""
	def test_the_descriptors_keep_every_rule(self):
		self.assertEqual(capability_problems(SOURCES), [])

	def test_the_weather_and_generators_require_what_they_ask_for(self):
		by_id = { s["id"]: s for s in SOURCES }
		self.assertIn("data-weather", by_id["openweathermap"]["features"])
		for sid in ("weather", "weather-overlay", "weather-image"):
			self.assertIn("data-weather", by_id[sid]["requires"])
		for sid in ("ai-image", "weather-image"):
			self.assertTrue({"data-ai-text", "data-ai-image"} <= set(by_id[sid]["requires"]))

	def test_a_broken_descriptor_fails_each_rule(self):
		import copy
		def broken(change) -> list[str]:
			sources = copy.deepcopy(SOURCES)
			change({ s["id"]: s for s in sources })
			return capability_problems(sources)
		def drop(source: dict, key: str, value: str):
			source[key] = [v for v in source[key] if v != value]
		def tokens_from(source: dict, value: list[str]):
			next(p for p in source["instanceSettings"]["schema"]["properties"] if p.get("tokensFrom"))["tokensFrom"] = value
		cases = [
			("unknown feature", lambda s: s["openweathermap"]["features"].append("data-wether"), "openweathermap: unknown feature data-wether"),
			("a page that is a provider", lambda s: s["weather"]["features"].append("api"), "weather: neither a provider"),
			("a capability on a page", lambda s: s["weather"]["features"].append("data-weather"), "weather: supplies ['data-weather'] but is not a provider"),
			("a requirement nobody supplies", lambda s: drop(s["openweathermap"], "features", "data-weather"), "weather: requires data-weather, which no provider supplies"),
			("a requirement that is no capability", lambda s: s["weather"]["requires"].append("internet"), "weather: requires internet, which is not a capability"),
			("a choice not required", lambda s: drop(s["ai-image"], "requires", "data-ai-text"), "ai-image: chooses a provider of data-ai-text but does not require it"),
			("a page used as a provider", lambda s: s["weather"].update(uses=["rss"]), "weather: uses rss, which is not a provider"),
			("prompt fields from a vendor", lambda s: tokens_from(s["weather-image"], ["openweathermap"]), "weather-image: weatherPrompt takes its fields from openweathermap, which is not a capability"),
			("prompt fields not required", lambda s: drop(s["weather-image"], "requires", "data-weather"), "weather-image: weatherPrompt takes its fields from data-weather, which it does not require"),
		]
		for name, change, expected in cases:
			with self.subTest(name):
				self.assertTrue(any(p.startswith(expected) for p in broken(change)), f"expected {expected!r} in {broken(change)}")

class TestProvidersAndContracts(unittest.TestCase):
	"""A provider implements its capability's contract, and a data source reads only contracts: it imports no provider's module but one it `uses` (a vendor tie)."""
	def test_every_provider_of_a_capability_implements_its_contract(self):
		import importlib
		from ..datasources.contracts import CONTRACTS
		for source in (s for s in SOURCES if is_api(s)):
			kind = getattr(importlib.import_module(source["module"]), source["class"])
			for capability in capabilities(source["features"]):
				with self.subTest(source["id"], capability=capability):
					self.assertTrue(issubclass(kind, CONTRACTS[capability]), f"{source['class']} supplies {capability}: it implements {CONTRACTS[capability].__name__}")

	def test_a_data_source_imports_no_providers_module_it_does_not_use(self):
		import re
		folders = { s["module"].split(".")[2]: s["id"] for s in SOURCES if is_api(s) }
		for source in (s for s in SOURCES if not is_api(s)):
			path = os.path.join(BASE, *source["module"].split(".")[1:]) + ".py"
			with open(path, encoding="utf-8") as f:
				imported = set(re.findall(r"^from \.\.(\w+)", f.read(), re.MULTILINE))
			with self.subTest(source["id"]):
				for folder in imported & set(folders):
					self.assertIn(folders[folder], source.get("uses") or [], f"imports the {folders[folder]} provider's module: read its contract (`contracts/`), or say `uses`")
