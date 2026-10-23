"""
OpenAI for the Generated Image: the provider (an API data source holding the key), its text and image parts, the master that renders, and the
provider's routes, against the fake internet's OpenAI (python/tests/fake_internet.py): the real SDK, no key, no cost.
"""
import atexit
import json
import logging
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from PIL import Image

from ..datasources.ai_image.ai_image import GeneratedImageAsync
from ..datasources.data_source import DataSourceApi, DataSourceExecutionContext, DataSourceManager
from ..datasources.openai_api import models
from ..datasources.openai_api.models import FAMILIES, family_of, image_models, quality_for, size_for, text_models
from ..datasources.openai_api.openai_api import OpenAIApi
from ..datasources.openai_image.openai_image import OpenAIImageAsync
from ..datasources.openai_text.openai_text import OpenAITextAsync
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .fake_internet import FakeInternet, OPENAI_MODELS, fixture_text
from .test_datasource_fixes import FakeSettings
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings

ALL_IDS = [m["id"] for m in json.loads(fixture_text(OPENAI_MODELS))["data"]]
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

def fake() -> FakeInternet:
	transport = AsyncHttpWorkerPool.default_transport
	assert isinstance(transport, FakeInternet), "the tests' OpenAI is the fake internet's"
	return transport

def openai_requests(path: str) -> list[dict]:
	return [json.loads(r.read() or b"{}") for r in fake().requests if r.url.host == "api.openai.com" and r.url.path == path]

class TestTheFamilies(unittest.TestCase):
	def test_a_model_is_found_by_its_prefix_snapshots_and_new_models_too(self):
		self.assertEqual(family_of("gpt-image-2.5-sunburst-2026-09-08").name, "gpt-image-2.5")  # type: ignore[union-attr]
		self.assertEqual(family_of("gpt-image-2-2026-04-21").name, "gpt-image-2")  # type: ignore[union-attr]
		self.assertEqual(family_of("gpt-image-1.5").name, "gpt-image")  # type: ignore[union-attr]
		self.assertEqual(family_of("chatgpt-image-latest").name, "gpt-image")  # type: ignore[union-attr]
		# a GPT image model not in the table yet gets what every GPT image model takes
		self.assertEqual(family_of("gpt-image-7").name, "gpt-image")  # type: ignore[union-attr]
		for other in ("dall-e-3", "dall-e-2", "gpt-5.6-luna", "whisper-1", ""):
			self.assertIsNone(family_of(other), other)
		self.assertTrue(models.is_retired("dall-e-3"))

	def test_a_quality_the_model_does_not_take_is_the_nearest_below(self):
		two, two_five = family_of("gpt-image-2"), family_of("gpt-image-2.5-flare")
		assert two is not None and two_five is not None
		self.assertEqual([quality_for(two, q) for q in ("auto", "low", "medium", "high", "xhigh", "max")], ["auto", "low", "medium", "high", "high", "high"])
		self.assertEqual([quality_for(two_five, q) for q in ("xhigh", "max")], ["xhigh", "max"])
		for unknown in (None, "", "hd", "standard"):
			self.assertEqual(quality_for(two, unknown), "auto")

	def test_a_free_size_has_the_panels_shape_within_the_rules(self):
		two = family_of("gpt-image-2")
		assert two is not None
		self.assertEqual(size_for(two, 800, 480), "1536x928")
		self.assertEqual(size_for(two, 480, 800), "928x1536")
		self.assertEqual(size_for(two, 1000, 1000), "1536x1536")
		# a panel narrower than 1:3 is drawn at 3:1 and gets a margin
		self.assertEqual(size_for(two, 4000, 100), "1536x512")
		for w, h in ((800, 480), (600, 448), (1600, 1200), (1872, 1404), (250, 122), (122, 250), (640, 400)):
			size = size_for(two, w, h)
			sw, sh = (int(v) for v in size.split("x"))
			with self.subTest(panel=(w, h), size=size):
				self.assertEqual((sw % 16, sh % 16), (0, 0))
				self.assertTrue(1 / 3 <= sw / sh <= 3)
				self.assertLessEqual(max(sw, sh), models.LONG_EDGE)

	def test_a_fixed_size_is_the_closest_shape(self):
		one = family_of("gpt-image-1.5")
		assert one is not None
		self.assertEqual([size_for(one, *p) for p in ((800, 480), (480, 800), (600, 560))], ["1536x1024", "1024x1536", "1024x1024"])

	def test_the_lists_hold_only_what_each_field_can_use(self):
		self.assertEqual(image_models(ALL_IDS), ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2", "gpt-image-2-2026-04-21",
			"gpt-image-1.5", "gpt-image-1-mini", "chatgpt-image-latest"])
		self.assertEqual(text_models(ALL_IDS), ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5-mini-2025-08-07"])
		self.assertEqual(len(FAMILIES), len({ f.name for f in FAMILIES }))

def sources() -> dict:
	return { "openai-api": OpenAIApi("openai-api", "OpenAI"), "openai-text": OpenAITextAsync("openai-text", "OpenAI Text"),
		"openai-image": OpenAIImageAsync("openai-image", "OpenAI Image") }

def storage(api_key: str|None, **settings) -> ConfigurationManager:
	folder = tempfile.mkdtemp(prefix="eink-openai-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	if api_key is not None:
		save_datasource_settings(cm, "openai-api", { "apiKey": api_key, "modelsCacheHours": 24, "staleDays": 30, **settings })
	return cm

def context(cm: ConfigurationManager, orientation="landscape", loaded: dict|None = None, now=NOW) -> DataSourceExecutionContext:
	"""The context the Generated Image gets: its own folder, the loaded data sources to choose its parts from."""
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("ai-image"))
	root.add_service(DataSourceManager, DataSourceManager(sources() if loaded is None else loaded))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({ "orientation": orientation })))
	return DataSourceExecutionContext(root, (800, 480), now)

TASK = { "prompt": "a lighthouse", "randomizePrompt": False, "textSource": "openai-text", "imageSource": "openai-image" }

class TestTheParts(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()
		self.master = GeneratedImageAsync("ai-image", "Generated Image")

	async def picture(self, dsec: DataSourceExecutionContext, **params) -> Image.Image:
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

	async def test_a_picture_in_the_panels_shape_with_the_settings_the_model_takes(self):
		image = await self.picture(context(storage("sk-good")), imageModel="gpt-image-2", quality="max", moderation="low")
		self.assertEqual(image.size, (800, 480))
		[asked] = openai_requests("/v1/images/generations")
		self.assertEqual({ k: asked[k] for k in ("model", "size", "quality", "moderation", "background", "output_format", "n") },
			{ "model": "gpt-image-2", "size": "1536x928", "quality": "high", "moderation": "low", "background": "opaque", "output_format": "png", "n": 1 })
		self.assertTrue(asked["prompt"].startswith("a lighthouse"))
		# the retired models' parameters are never sent, and no text was asked for
		self.assertNotIn("response_format", asked)
		self.assertEqual(openai_requests("/v1/responses"), [])

	async def test_portrait_and_an_older_model_with_a_fixed_size(self):
		image = await self.picture(context(storage("sk-good"), orientation="portrait"), imageModel="gpt-image-1.5", quality="xhigh")
		self.assertEqual(image.size, (480, 800))
		[asked] = openai_requests("/v1/images/generations")
		self.assertEqual((asked["size"], asked["quality"]), ("1024x1536", "high"))

	async def test_the_prompt_is_rewritten_by_the_text_part(self):
		await self.picture(context(storage("sk-good")), imageModel="gpt-image-2.5-flare", randomizePrompt=True, textModel="gpt-5.6-terra")
		[rewrite] = openai_requests("/v1/responses")
		self.assertEqual(rewrite["model"], "gpt-5.6-terra")
		self.assertIn("a lighthouse", rewrite["input"])
		self.assertNotIn("temperature", rewrite)
		[asked] = openai_requests("/v1/images/generations")
		self.assertTrue(asked["prompt"].startswith("A lighthouse drawn as a woodcut"))

	async def test_a_task_without_the_parts_fields_runs_at_their_defaults(self):
		await self.picture(context(storage("sk-good")), randomizePrompt=True)
		self.assertEqual(openai_requests("/v1/responses")[0]["model"], models.DEFAULT_TEXT_MODEL)
		[asked] = openai_requests("/v1/images/generations")
		self.assertEqual((asked["model"], asked["quality"], asked["moderation"]), (models.DEFAULT_IMAGE_MODEL, "auto", "auto"))

	async def test_what_cannot_work_says_so_in_our_words_and_is_permanent(self):
		cases = [
			(context(storage(None)), {}, "Enter the OpenAI API key"),
			(context(storage("sk-good")), { "imageModel": "dall-e-3" }, "OpenAI retired the image model dall-e-3"),
			(context(storage("sk-good")), { "imageModel": "whisper-1" }, "not an OpenAI image model"),
			(context(storage("sk-good")), { "imageSource": None }, "Choose the image source"),
			(context(storage("sk-good")), { "randomizePrompt": True, "textSource": "" }, "Choose the text source"),
			(context(storage("sk-good"), loaded={ "openai-api": OpenAIApi("openai-api", "OpenAI") }), {}, "The OpenAI Image data source is not available"),
			(context(storage("sk-good"), loaded={ "openai-image": OpenAIImageAsync("openai-image", "OpenAI Image") }), {}, "The OpenAI data source is not available"),
			# a source that is not an image part (the text part) cannot be chosen as one
			(context(storage("sk-good")), { "imageSource": "openai-text" }, "The OpenAI Text data source is not available"),
		]
		for dsec, params, words in cases:
			with self.subTest(params=params, words=words), self.assertRaises(PermanentError) as refused:
				await self.picture(dsec, **params)
			self.assertIn(words, str(refused.exception))
		self.assertEqual(openai_requests("/v1/images/generations"), [], "nothing was asked of OpenAI")

	async def test_openais_refusals_never_carry_its_text_or_the_key(self):
		cases = [
			("sk-proj-wrongKEY123", {}, "OpenAI refused the API key"),
			("sk-broke", {}, "no credit left"),
			("sk-good", { "imageModel": "gpt-image-3" }, "does not offer the model gpt-image-3"),
			("sk-good", { "randomizePrompt": True, "textModel": "gpt-9" }, "does not offer the model gpt-9"),
		]
		for key, params, words in cases:
			with self.subTest(key=key, params=params):
				with self.assertLogs("python.datasources.openai_api", level="DEBUG") as logs, self.assertRaises(PermanentError) as refused:
					await self.picture(context(storage(key)), **params)
				self.assertIn(words, str(refused.exception))
				everything = str(refused.exception) + "\n".join(logs.output)
				self.assertNotIn("wrongKEY123", everything)
				self.assertNotIn("Incorrect API key", everything, "OpenAI's own text never reaches a message or the log")

class TestTheModelList(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()

	async def models(self, dsec: DataSourceExecutionContext) -> list[str]:
		provider, provider_dsec = dsec.use("openai-api", OpenAIApi)
		return (await provider.open_async(provider_dsec, { "request": "models" }))["ids"]

	async def test_it_is_kept_and_shared_and_another_key_is_another_list(self):
		cm = storage("sk-good")
		self.assertEqual(await self.models(context(cm)), ALL_IDS)
		self.assertEqual(await self.models(context(cm, now=NOW + timedelta(hours=23))), ALL_IDS)
		self.assertEqual(len(openai_requests("/v1/models")), 1, "kept for a day")
		await self.models(context(cm, now=NOW + timedelta(hours=25)))
		self.assertEqual(len(openai_requests("/v1/models")), 2)
		save_datasource_settings(cm, "openai-api", { "apiKey": "sk-proj-another", "modelsCacheHours": 24 })
		with self.assertRaises(PermanentError):
			await self.models(context(cm, now=NOW + timedelta(hours=25)))
		# the key is not in what is kept
		for name in cm.datasource_manager("openai-api").list_files("cache-"):
			self.assertNotIn("sk-good", json.dumps(cm.datasource_manager("openai-api").file(name).get()[1]))

class TestTheRoutes(WebApiTestBase):
	BASE = "/api/datasource/openai-api"

	def setUp(self):
		super().setUp()
		logging.getLogger("python.datasources.openai_api").setLevel(logging.CRITICAL)

	def test_the_lookups_list_what_the_saved_key_may_use(self):
		self.write_datasource_settings("openai-api", { "apiKey": "sk-good" })
		images = self.client.get(f"{self.BASE}/lookups/image-models")
		self.assertEqual(images.status_code, 200)
		self.assertEqual([c["value"] for c in images.json()], image_models(ALL_IDS))
		self.assertTrue(all(c["name"] == c["value"] for c in images.json()))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/text-models").json()], text_models(ALL_IDS))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/qualities").json()], list(models.QUALITIES))

	def test_the_models_route_says_what_each_takes(self):
		self.write_datasource_settings("openai-api", { "apiKey": "sk-good" })
		body = self.client.get(f"{self.BASE}/models").json()
		by_id = { m["id"]: m for m in body["image"] }
		self.assertEqual(by_id["gpt-image-2.5-flare"]["qualities"], ["auto", "low", "medium", "high", "xhigh", "max"])
		self.assertEqual((by_id["gpt-image-2"]["size"], by_id["gpt-image-2"]["sizes"]), ("free", []))
		self.assertEqual((by_id["gpt-image-1.5"]["size"], by_id["gpt-image-1.5"]["sizes"]), ("fixed", ["1024x1024", "1536x1024", "1024x1536"]))
		self.assertEqual(body["text"], text_models(ALL_IDS))

	def test_without_a_working_key_the_answer_says_why_and_holds_no_key(self):
		self.assertEqual(self.client.get(f"{self.BASE}/lookups/image-models").json()["message"], "Enter the OpenAI API key in the OpenAI settings and save them first.")
		self.write_datasource_settings("openai-api", { "apiKey": "sk-proj-wrongKEY123" })
		refused = self.client.get(f"{self.BASE}/lookups/image-models")
		self.assertEqual((refused.status_code, refused.json()["success"]), (502, False))
		self.assertIn("OpenAI refused the API key", refused.json()["message"])
		self.assertNotIn("wrongKEY123", refused.text)

	def test_the_test_button_checks_the_key_typed_or_the_saved_one(self):
		answer = lambda value: self.client.post(f"{self.BASE}/test", json={ "value": value }).json()
		self.assertEqual(answer("sk-good")["ok"], True)
		self.assertIn("The key works: 7 image models (gpt-image-2.5-flare, gpt-image-2.5-sunburst, gpt-image-2, ...)", answer("sk-good")["message"])
		wrong = answer("sk-proj-wrongKEY123")
		self.assertEqual(wrong["ok"], False)
		self.assertNotIn("wrongKEY123", wrong["message"])
		self.assertEqual(answer("********"), { "ok": False, "message": "Enter an API key first." })
		self.write_datasource_settings("openai-api", { "apiKey": "sk-good" })
		self.assertEqual(answer("********")["ok"], True)
