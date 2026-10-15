"""
Google's Gemini API for the Generated Image: the provider (an API data source holding the AI Studio key), its text and image parts, and the provider's
routes, against the fake internet's Google (python/tests/fake_internet.py): no key, no cost. And the point of the parts: GPT text with a Google picture.
"""
import atexit
import json
import logging
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import patch

import httpx

from ..datasources.ai_image.ai_image import GeneratedImageAsync
from ..datasources.data_source import DataSourceApi, DataSourceExecutionContext, DataSourceManager
from ..datasources.google_api import models
from ..datasources.google_api.google_api import GoogleApi
from ..datasources.google_api.models import FALLBACK, KEY, Vocabulary, image_models, model_ids, ratio_for, read_discovery, size_for, sizes_for, text_models
from ..datasources.google_image.google_image import GoogleImageAsync
from ..datasources.google_text.google_text import GoogleTextAsync
from ..datasources.openai_api.openai_api import OpenAIApi
from ..datasources.openai_text.openai_text import OpenAITextAsync
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .fake_internet import FakeInternet, GOOGLE_DISCOVERY, GOOGLE_MODELS, fixture_text
from .test_datasource_fixes import FakeSettings
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings

DISCOVERY = json.loads(fixture_text(GOOGLE_DISCOVERY))
ALL_MODELS = json.loads(fixture_text(GOOGLE_MODELS))
ALL_IDS = model_ids(ALL_MODELS)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
VOCABULARY = cast(Vocabulary, read_discovery(DISCOVERY))

def fake() -> FakeInternet:
	transport = AsyncHttpWorkerPool.default_transport
	assert isinstance(transport, FakeInternet), "the tests' Google is the fake internet's"
	return transport

def google_requests(path: str|None = None) -> list[httpx.Request]:
	return [r for r in fake().requests if r.url.host == "generativelanguage.googleapis.com" and (path is None or r.url.path.endswith(path))]

def bodies(suffix: str) -> list[dict]:
	return [json.loads(r.read() or b"{}") for r in google_requests(suffix)]

class TestWhatGoogleSays(unittest.TestCase):
	def test_the_vocabulary_is_read_from_the_discovery_document(self):
		self.assertEqual(VOCABULARY.ratios, ("1:1", "1:4", "4:1", "1:8", "8:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"))
		self.assertEqual((VOCABULARY.sizes, VOCABULARY.image_output, VOCABULARY.discovered), (("512", "1K", "2K", "4K"), True, True))
		# an enum, where the schema has one, is the list (and a new value shows up with no change here)
		changed = json.loads(json.dumps(DISCOVERY))
		changed["schemas"]["ImageConfig"]["properties"]["aspectRatio"] = { "type": "string", "enum": ["1:1", "7:3", "bogus"] }
		changed["schemas"]["ImageConfig"]["properties"]["imageSize"]["description"] = "Supported values are `1K`, `8K`."
		found = cast(Vocabulary, read_discovery(changed))
		self.assertEqual((found.ratios, found.sizes), (("1:1", "7:3"), ("1K",)))
		self.assertEqual(ratio_for(700, 300, found), "7:3")

	def test_a_document_that_does_not_say_what_a_picture_takes_is_not_used(self):
		for broken in ({}, { "schemas": {} }, { "schemas": { "ImageConfig": { "properties": {} } } }, "not a document", None):
			with self.subTest(broken=str(broken)[:30]):
				self.assertIsNone(read_discovery(broken))  # type: ignore[arg-type]
		self.assertFalse(FALLBACK.discovered)

	def test_the_ratio_is_the_nearest_to_the_panels_shape(self):
		self.assertEqual([ratio_for(*panel, VOCABULARY) for panel in ((800, 480), (480, 800), (600, 448), (1000, 1000), (4000, 100))],
			["16:9", "9:16", "4:3", "1:1", "8:1"])

	def test_quality_asks_for_a_size_clamped_to_what_the_model_takes(self):
		pro, lite, banana = "gemini-3-pro-image", "gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1"
		self.assertEqual([size_for(pro, q, VOCABULARY) for q in ("auto", "low", "high", "xhigh", "max", "bogus", None)], ["1K", "1K", "2K", "4K", "4K", "1K", "1K"])
		self.assertEqual({ size_for(lite, q, VOCABULARY) for q in ("auto", "high", "max") }, { "1K" })
		self.assertEqual((sizes_for(banana, VOCABULARY), sizes_for(pro, VOCABULARY)), (("1K", "2K", "4K"), ("512", "1K", "2K", "4K")))

	def test_the_lists_hold_only_what_each_field_can_use(self):
		self.assertEqual(image_models(ALL_IDS), ["gemini-3-pro-image", "gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-nano-banana-2.1", "gemini-3.1-flash-lite-image"])
		self.assertEqual(text_models(ALL_IDS), ["gemini-3.5-flash", "gemini-3.1-pro-preview"])
		# only the models that answer generateContent (no embeddings, no Imagen), and only ids that are safe in a path
		self.assertNotIn("imagen-4.0-generate-001", ALL_IDS)
		self.assertEqual(model_ids({ "models": [{ "baseModelId": "../../etc", "supportedGenerationMethods": ["generateContent"] },
			{ "name": "models/ok-1", "supportedGenerationMethods": ["generateContent"] }] }), ["ok-1"])

	def test_only_an_ai_studio_key_is_a_key(self):
		self.assertTrue(KEY.match("AQ.Ab12-cd_34.ef"))
		for other in ("AIzaSyA-1234567890", "sk-good", "", "AQ.", "AQ. x", "aq.lower"):
			self.assertIsNone(KEY.match(other), other)

def sources() -> dict:
	return { "google-ai": GoogleApi("google-ai", "Google AI"), "google-text": GoogleTextAsync("google-text", "Google Text"), "google-image": GoogleImageAsync("google-image", "Google Image"),
		"openai": OpenAIApi("openai", "OpenAI"), "openai-text": OpenAITextAsync("openai-text", "OpenAI Text") }

def storage(google_key: str|None = "AQ.good", openai_key: str|None = None, **settings) -> ConfigurationManager:
	folder = tempfile.mkdtemp(prefix="eink-google-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	if google_key is not None:
		save_datasource_settings(cm, "google-ai", { "apiKey": google_key, "modelsCacheHours": 24, "discoveryCacheHours": 168, "staleDays": 30, **settings })
	if openai_key is not None:
		save_datasource_settings(cm, "openai", { "apiKey": openai_key, "modelsCacheHours": 24, "staleDays": 30 })
	return cm

def context(cm: ConfigurationManager, orientation="landscape", loaded: dict|None = None, now=NOW) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("ai-image"))
	root.add_service(DataSourceManager, DataSourceManager(sources() if loaded is None else loaded))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({ "orientation": orientation })))
	return DataSourceExecutionContext(root, (800, 480), now)

TASK = { "prompt": "a lighthouse", "randomizePrompt": False, "textSource": "google-text", "imageSource": "google-image" }

class TestTheParts(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()
		self.master = GeneratedImageAsync("ai-image", "Generated Image")

	async def picture(self, dsec: DataSourceExecutionContext, **params):
		task = { **TASK, **params }
		state = await self.master.open_async(dsec, task)
		result = await self.master.render_async(dsec, task, state[0])
		assert result is not None and result.image is not None
		return result.image

	def test_the_provider_and_the_parts_are_data_only(self):
		for source in sources().values():
			with self.subTest(source.id):
				self.assertIsInstance(source, DataSourceApi)
				self.assertFalse(hasattr(source, "render_async"))

	async def test_a_picture_at_the_ratio_nearest_the_panels_and_the_size_the_quality_asks(self):
		image = await self.picture(context(storage()), imageModel="gemini-3-pro-image", quality="high")
		self.assertEqual(image.size, (800, 480))
		[asked] = bodies(":generateContent")
		self.assertEqual(asked["generationConfig"], { "responseModalities": ["IMAGE"], "imageConfig": { "aspectRatio": "16:9", "imageSize": "2K" } })
		self.assertTrue(asked["contents"][0]["parts"][0]["text"].startswith("a lighthouse"))
		[request] = google_requests(":generateContent")
		self.assertTrue(request.url.path.endswith("/models/gemini-3-pro-image:generateContent"))

	async def test_portrait_and_a_model_that_takes_one_size(self):
		image = await self.picture(context(storage(), orientation="portrait"), imageModel="gemini-3.1-flash-lite-image", quality="max")
		self.assertEqual(image.size, (480, 800))
		[asked] = bodies(":generateContent")
		self.assertEqual(asked["generationConfig"]["imageConfig"], { "aspectRatio": "9:16", "imageSize": "1K" })

	async def test_the_prompt_is_rewritten_by_the_text_part(self):
		await self.picture(context(storage()), randomizePrompt=True, textModel="gemini-3.1-pro-preview")
		text, drawing = google_requests(":generateContent")
		self.assertTrue(text.url.path.endswith("/models/gemini-3.1-pro-preview:generateContent"))
		first, second = bodies(":generateContent")
		self.assertIn("a lighthouse", first["contents"][0]["parts"][0]["text"])
		self.assertIn("systemInstruction", first)
		self.assertNotIn("responseModalities", first.get("generationConfig", {}))
		self.assertTrue(second["contents"][0]["parts"][0]["text"].startswith("A lighthouse drawn as a woodcut"))

	async def test_a_task_without_the_parts_fields_runs_at_their_defaults(self):
		await self.picture(context(storage()), randomizePrompt=True)
		rewrite, drawing = google_requests(":generateContent")
		self.assertTrue(rewrite.url.path.endswith(f"/models/{models.DEFAULT_TEXT_MODEL}:generateContent"))
		self.assertTrue(drawing.url.path.endswith(f"/models/{models.DEFAULT_IMAGE_MODEL}:generateContent"))
		self.assertEqual(bodies(":generateContent")[1]["generationConfig"]["imageConfig"]["imageSize"], "1K")

	async def test_the_key_is_in_the_header_only(self):
		await self.picture(context(storage()), randomizePrompt=True)
		requests = google_requests(":generateContent")
		self.assertTrue(requests)
		for request in requests:
			self.assertEqual(request.headers.get("x-goog-api-key"), "AQ.good")
			self.assertNotIn("key", request.url.params)
			self.assertNotIn("AQ.good", str(request.url))
			self.assertIsNone(request.headers.get("Authorization"))

	async def test_what_cannot_work_says_so_in_our_words_and_is_permanent(self):
		cases = [
			(context(storage(None)), {}, "Enter the Google AI Studio API key"),
			# an older standard key is not an AI Studio key: nothing is asked of Google
			(context(storage("AIzaSyA-1234567890")), {}, "not a Google AI Studio key"),
			(context(storage()), { "imageModel": "gemini-3.5-flash" }, "not a Gemini image model"),
			(context(storage()), { "imageModel": "../../models" }, "not a Google model name"),
			(context(storage()), { "imageSource": "" }, "Choose the image source"),
			(context(storage(), loaded={ "google-ai": GoogleApi("google-ai", "Google AI") }), {}, "Google-image data source is not available"),
			(context(storage(), loaded={ "google-image": GoogleImageAsync("google-image", "Google Image") }), {}, "Google-ai data source is not available"),
		]
		for dsec, params, words in cases:
			with self.subTest(params=params, words=words), self.assertRaises(PermanentError) as refused:
				await self.picture(dsec, **params)
			self.assertIn(words, str(refused.exception))
		self.assertEqual(google_requests(":generateContent"), [], "nothing was asked of Google")

	async def test_googles_refusals_never_carry_its_text_or_the_key(self):
		cases = [
			("AQ.wrong-key-1234", {}, PermanentError, "Google refused the API key"),
			("AQ.broke", {}, PermanentError, "key type"),
			("AQ.busy", {}, RuntimeError, "quota"),
			("AQ.good", { "imageModel": "gemini-9-image" }, PermanentError, "does not offer the model gemini-9-image"),
		]
		for key, params, kind, words in cases:
			with self.subTest(key=key, params=params):
				with self.assertLogs("python.datasources", level="DEBUG") as logs, self.assertRaises(kind) as refused:
					logging.getLogger("python.datasources").info("start")
					await self.picture(context(storage(key)), **params)
				self.assertIn(words, str(refused.exception))
				if kind is RuntimeError:
					self.assertNotIsInstance(refused.exception, PermanentError)
				everything = str(refused.exception) + "\n".join(logs.output)
				self.assertNotIn("wrong-key-1234", everything)
				self.assertNotIn("Google's own text", everything, "Google's own text never reaches a message or the log")
				self.assertNotIn("AQ.leaked", everything)

class TestTheMixedMaster(unittest.IsolatedAsyncioTestCase):
	"""The point of the parts: GPT text with a Google picture."""
	async def test_openai_text_and_a_google_picture(self):
		fake().requests.clear()
		master = GeneratedImageAsync("ai-image", "Generated Image")
		dsec = context(storage("AQ.good", "sk-good"))
		task = { "prompt": "a lighthouse", "randomizePrompt": True, "textSource": "openai-text", "imageSource": "google-image", "textModel": "gpt-5.6-terra", "imageModel": "gemini-3.1-flash-image", "quality": "auto" }
		state = await master.open_async(dsec, task)
		result = await master.render_async(dsec, task, state[0])
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))
		self.assertEqual(result.title, "Generated Image: A lighthouse drawn as a woodcut by Hokusai, in a storm of paper cranes")
		openai = [r for r in fake().requests if r.url.host == "api.openai.com" and r.url.path == "/v1/responses"]
		self.assertEqual(json.loads(openai[0].read())["model"], "gpt-5.6-terra")
		[drawing] = google_requests(":generateContent")
		self.assertTrue(drawing.url.path.endswith("/models/gemini-3.1-flash-image:generateContent"))
		# each provider got only its own key
		self.assertEqual(openai[0].headers["Authorization"], "Bearer sk-good")
		self.assertEqual(drawing.headers["x-goog-api-key"], "AQ.good")
		self.assertEqual([r for r in fake().requests if r.url.host == "api.openai.com" and r.url.path == "/v1/images/generations"], [])

class Counting(httpx.MockTransport):
	"""The fake internet with the discovery document replaced (or refused), to see what the provider does with it."""
	def __init__(self, discovery: dict|None):
		self.discovery = discovery
		self.real = fake()
		super().__init__(self._handle)
	def _handle(self, request: httpx.Request) -> httpx.Response:
		if request.url.path == "/$discovery/rest":
			if self.discovery is None:
				raise httpx.ConnectError("offline", request=request)
			return httpx.Response(200, json=self.discovery)
		return self.real._handle(request)

class TestDiscoveryAndTheModelList(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()

	async def ask(self, dsec: DataSourceExecutionContext, **params):
		provider, provider_dsec = dsec.use("google-ai", GoogleApi)
		return await provider.open_async(provider_dsec, params)

	async def test_the_model_list_is_paged_kept_and_shared_and_another_key_is_another_list(self):
		cm = storage()
		self.assertEqual((await self.ask(context(cm), request="models"))["ids"], ALL_IDS)
		self.assertEqual(len(google_requests("/models")), 2, "two pages")
		await self.ask(context(cm, now=NOW + timedelta(hours=23)), request="models")
		self.assertEqual(len(google_requests("/models")), 2, "kept for a day")
		await self.ask(context(cm, now=NOW + timedelta(hours=25)), request="models")
		self.assertEqual(len(google_requests("/models")), 4)
		save_datasource_settings(cm, "google-ai", { "apiKey": "AQ.another-key", "modelsCacheHours": 24, "discoveryCacheHours": 168 })
		with self.assertRaises(PermanentError):
			await self.ask(context(cm, now=NOW + timedelta(hours=25)), request="models")
		for name in cm.datasource_manager("google-ai").list_files("cache-"):
			self.assertNotIn("AQ.good", json.dumps(cm.datasource_manager("google-ai").file(name).get()[1]))

	async def test_the_discovery_document_is_kept_and_needs_no_key(self):
		cm = storage(None)
		save_datasource_settings(cm, "google-ai", { "apiKey": None, "modelsCacheHours": 24, "discoveryCacheHours": 168, "staleDays": 30 })
		found = await self.ask(context(cm), request="discovery")
		await self.ask(context(cm, now=NOW + timedelta(hours=100)), request="discovery")
		self.assertEqual((found.ratios, found.discovered), (VOCABULARY.ratios, True))
		[asked] = google_requests("/$discovery/rest")
		self.assertIsNone(asked.headers.get("x-goog-api-key"))
		self.assertEqual(len(google_requests("/$discovery/rest")), 1)

	async def test_a_change_in_the_description_reaches_the_choices(self):
		changed = json.loads(json.dumps(DISCOVERY))
		changed["schemas"]["ImageConfig"]["properties"]["aspectRatio"]["description"] += " Also `7:3`."
		with patch.object(AsyncHttpWorkerPool, "default_transport", Counting(changed)):
			found = await self.ask(context(storage()), request="discovery")
		self.assertIn("7:3", found.ratios)

	async def test_when_the_description_cannot_be_had_todays_values_are_used(self):
		with patch.object(AsyncHttpWorkerPool, "default_transport", Counting(None)):
			with self.assertLogs("python.datasources.google_api.google_api", level="WARNING"):
				found = await self.ask(context(storage()), request="discovery")
			image = await GeneratedImageAsync("ai-image", "Generated Image").render_async(context(storage()), TASK, { "prompt": "p" })
		self.assertEqual((found.ratios, found.discovered), (FALLBACK.ratios, False))
		assert image is not None

class TestTheRoutes(WebApiTestBase):
	BASE = "/api/datasource/google-ai"

	def setUp(self):
		super().setUp()
		logging.getLogger("python.datasources.google_api").setLevel(logging.CRITICAL)

	def save_key(self, key="AQ.good"):
		self.write_datasource_settings("google-ai", { "apiKey": key, "modelsCacheHours": 24, "discoveryCacheHours": 168, "staleDays": 30 })

	def test_the_lookups_list_what_the_saved_key_may_use(self):
		self.save_key()
		images = self.client.get(f"{self.BASE}/lookups/image-models")
		self.assertEqual(images.status_code, 200)
		self.assertEqual([c["value"] for c in images.json()], image_models(ALL_IDS))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/text-models").json()], text_models(ALL_IDS))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/qualities").json()], list(models.QUALITY_NAMES))

	def test_the_models_route_says_what_each_takes_from_the_discovery_document(self):
		self.save_key()
		body = self.client.get(f"{self.BASE}/models").json()
		by_id = { m["id"]: m for m in body["image"] }
		self.assertEqual(by_id["gemini-3-pro-image"]["sizes"], ["512", "1K", "2K", "4K"])
		self.assertEqual(by_id["gemini-3.1-flash-lite-image"]["sizes"], ["1K"])
		self.assertEqual(by_id["gemini-nano-banana-2.1"]["sizes"], ["1K", "2K", "4K"])
		self.assertEqual(by_id["gemini-3-pro-image"]["ratios"], list(VOCABULARY.ratios))
		self.assertTrue(by_id["gemini-3-pro-image"]["discovered"])
		self.assertEqual(body["text"], text_models(ALL_IDS))

	def test_without_a_working_key_the_answer_says_why_and_holds_no_key(self):
		self.assertEqual(self.client.get(f"{self.BASE}/lookups/image-models").status_code, 409)
		self.assertIn("Save the settings first", self.client.get(f"{self.BASE}/lookups/image-models").json()["message"])
		self.save_key("AQ.wrong-key-1234")
		refused = self.client.get(f"{self.BASE}/lookups/image-models")
		self.assertEqual((refused.status_code, refused.json()["success"]), (502, False))
		self.assertIn("Google refused the API key", refused.json()["message"])
		self.assertNotIn("wrong-key-1234", refused.text)

	def test_the_test_button_checks_the_key_typed_or_the_saved_one(self):
		answer = lambda value: self.client.post(f"{self.BASE}/test", json={ "value": value }).json()
		good = answer("AQ.good")
		self.assertEqual(good["ok"], True)
		self.assertIn("The key works: 5 image models (gemini-3-pro-image, gemini-2.5-flash-image, gemini-3.1-flash-image, ...)", good["message"])
		for typed, words in (("AQ.wrong-key-1234", "refused the API key"), ("AQ.broke", "key type"), ("AIzaSyA-1234567890", "not a Google AI Studio key")):
			with self.subTest(typed=typed):
				reply = answer(typed)
				self.assertEqual(reply["ok"], False)
				self.assertIn(words, reply["message"])
				self.assertNotIn(typed, reply["message"])
		self.assertEqual(answer("********")["ok"], False)
		self.save_key()
		self.assertEqual(answer("********")["ok"], True)
		# a key that is not an AI Studio key is refused before Google is asked
		asked = len(google_requests())
		answer("AIzaSyA-1234567890")
		self.assertEqual(len(google_requests()), asked)

	def test_the_settings_refuse_an_older_key_and_the_mask_passes(self):
		url = "/api/datasources/google-ai/settings"
		# the factory seeding stored the defaults already: a save carries the revision it read
		seeded = self.client.get(url).json()
		refused = self.client.put(url, json={ **seeded, "apiKey": "AIzaSyA-1234567890" })
		self.assertEqual(refused.status_code, 422)
		self.assertEqual(refused.json()["errors"][0], { "path": ["apiKey"], "message": "Not in the expected format" })
		self.assertEqual(self.client.put(url, json={ **seeded, "apiKey": "AQ.good" }).status_code, 200)
		doc = self.client.get(url).json()
		self.assertEqual(doc["apiKey"], "********")
		# the mask stands for the stored key: it is not checked against the pattern
		self.assertEqual(self.client.put(url, json=doc).status_code, 200)
