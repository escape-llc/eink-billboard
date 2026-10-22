"""
`dsec.provide(Contract)` (#513): a data source that needs a capability gets a provider of it, whichever is loaded, in a fixed order: the device's
provider when it is set up, the only one set up, the device's provider anyway, the only one there is; else a message that names the capability.
"""
import unittest
from typing import Any, Mapping, cast

from ..datasources.contracts import CONTRACTS, tokens_of
from ..datasources.contracts.ai import AiTextApi
from ..datasources.contracts.weather import TOKENS, WeatherApi
from ..datasources.data_source import DataSource, DataSourceExecutionContext, DataSourceManager
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from .test_weather import NOW, FakeSettings, weather_settings

class FakeWeather(WeatherApi):
	"""A weather provider whose readiness the test decides."""
	def __init__(self, id: str, ready: bool):
		super().__init__(id, id.capitalize())
		self.ready = ready
	def configured(self, dsec: DataSourceExecutionContext) -> bool:
		return self.ready

def context(*sources: DataSource, cm: ConfigurationManager|None = None, **system: Any) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm or weather_settings())
	root.add_service(DataSourceManager, DataSourceManager({ s.id: s for s in sources }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(**system)))
	return DataSourceExecutionContext(root, (800, 480), NOW)

def chosen(*sources: DataSource, **system: Any) -> str:
	provider, _ = context(*sources, **system).provide(WeatherApi)
	return provider.id

class TestTheOrder(unittest.TestCase):
	def test_the_devices_provider_when_it_is_set_up(self):
		self.assertEqual(chosen(FakeWeather("a", True), FakeWeather("b", True), weatherProvider="b"), "b")

	def test_the_only_one_set_up_when_the_device_names_none(self):
		self.assertEqual(chosen(FakeWeather("a", False), FakeWeather("b", True)), "b")

	def test_the_only_one_set_up_when_the_devices_provider_is_not(self):
		self.assertEqual(chosen(FakeWeather("a", True), FakeWeather("b", False), weatherProvider="b"), "a")

	def test_the_devices_provider_when_none_is_set_up_so_it_says_what_to_set(self):
		self.assertEqual(chosen(FakeWeather("a", False), FakeWeather("b", False), weatherProvider="b"), "b")

	def test_the_only_one_there_is_set_up_or_not(self):
		self.assertEqual(chosen(FakeWeather("a", False)), "a")

	def test_a_device_provider_that_is_not_loaded_is_no_choice(self):
		self.assertEqual(chosen(FakeWeather("a", True), FakeWeather("b", False), weatherProvider="gone"), "a")

	def test_only_providers_of_the_contract_count(self):
		other = AiTextApi("text", "Text")
		self.assertEqual(chosen(FakeWeather("a", False), other), "a")

	def test_the_context_is_the_providers_own(self):
		cm = weather_settings()
		provider, dsec = context(FakeWeather("a", True), cm=cm).provide(WeatherApi)
		from ..model.configuration_manager import DatasourceConfigurationManager
		self.assertEqual(dsec.provider.required(DatasourceConfigurationManager).datasource_id, provider.id)

class TestNoChoice(unittest.TestCase):
	def test_none_installed(self):
		with self.assertRaisesRegex(PermanentError, "No weather provider is installed"):
			context().provide(WeatherApi)

	def test_several_and_none_set_up_names_them(self):
		with self.assertRaisesRegex(PermanentError, r"No weather provider is set up\. Set one up in its settings: A, B\."):
			context(FakeWeather("a", False), FakeWeather("b", False)).provide(WeatherApi)

	def test_several_set_up_and_none_chosen(self):
		with self.assertRaisesRegex(PermanentError, "Several weather providers are set up. Choose the device's weather provider in the System settings"):
			context(FakeWeather("a", True), FakeWeather("b", True)).provide(WeatherApi)

	def test_only_a_contract_can_be_provided(self):
		with self.assertRaises(TypeError):
			context(FakeWeather("a", True)).provide(cast(Any, DataSource))

class TestOpenWeatherMapIsAWeatherProvider(unittest.TestCase):
	def test_it_is_set_up_when_its_key_is_set(self):
		from ..datasources.openweathermap.openweathermap import OpenWeatherMapApi
		owm = OpenWeatherMapApi("openweathermap", "OpenWeatherMap")
		for key, ready in (("k-123", True), ("", False), (None, False), ("   ", False)):
			with self.subTest(key=key):
				dsec = context(owm, cm=weather_settings({ "apiKey": key }))
				self.assertEqual(owm.configured(dsec.context_for(owm)), ready)

class TestContracts(unittest.TestCase):
	def test_each_capability_has_its_contract(self):
		self.assertEqual(set(CONTRACTS), { "data-weather", "data-calendar", "data-ai-text", "data-ai-image" })
		for capability, contract in CONTRACTS.items():
			self.assertEqual(contract.capability, capability)
			self.assertTrue(contract.noun)

	def test_the_weathers_fields_are_the_contracts(self):
		self.assertEqual([t["name"] for t in tokens_of("data-weather")], [t["name"] for t in TOKENS])
		self.assertEqual(tokens_of("data-tides"), [])

	def test_a_prompt_field_list_resolves_through_the_contract(self):
		"""`tokensFrom: ["data-weather"]` on the Weather Visualizer reads the contract's list, not a provider's descriptor."""
		info = next(i for i in ConfigurationManager().enum_datasources() if cast(Mapping, i["info"])["id"] == "weather-image")["info"]
		prompt = next(p for p in cast(Any, info)["instanceSettings"]["schema"]["properties"] if p.get("tokensFrom"))
		self.assertEqual(prompt["tokensFrom"], ["data-weather"])
		self.assertEqual(prompt["tokens"], tokens_of("data-weather"))
