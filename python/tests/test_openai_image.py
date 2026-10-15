"""
The OpenAI Image data source and its routes, against the fake internet's OpenAI (python/tests/fake_internet.py): the real SDK, no key, no cost.
"""
import json
import logging
import unittest
from datetime import datetime, timezone
from typing import Any, cast

from PIL import Image

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.openai_image import models
from ..datasources.openai_image.models import FAMILIES, family_of, image_models, quality_for, size_for, text_models
from ..datasources.openai_image.openai_image import OpenAIAsync
from ..model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .fake_internet import FakeInternet, OPENAI_MODELS, fixture_text
from .test_datasource_fixes import FakeDatasourceSettings, FakeSettings
from .test_web_api import WebApiTestBase

ALL_IDS = [m["id"] for m in json.loads(fixture_text(OPENAI_MODELS))["data"]]

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

def dsec(api_key: str|None, dimensions=(800, 480), orientation="landscape") -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, cast(Any, FakeDatasourceSettings({ "apiKey": api_key } if api_key else {})))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings({ "orientation": orientation })))
	return DataSourceExecutionContext(root, dimensions, datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))

class TestTheDataSource(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		fake().requests.clear()
		self.ds = OpenAIAsync("openai-image", "OpenAI Image")

	async def picture(self, context: DataSourceExecutionContext, **params) -> Image.Image:
		state = await self.ds.open_async(context, params)
		result = await self.ds.render_async(context, params, state[0])
		assert result is not None and result.image is not None
		return result.image

	async def test_a_picture_in_the_panels_shape_with_the_settings_the_model_takes(self):
		image = await self.picture(dsec("sk-good"), prompt="a lighthouse", imageModel="gpt-image-2", quality="max", moderation="low", randomizePrompt=False)
		self.assertEqual(image.size, (800, 480))
		[asked] = openai_requests("/v1/images/generations")
		self.assertEqual({ k: asked[k] for k in ("model", "size", "quality", "moderation", "background", "output_format", "n") },
			{ "model": "gpt-image-2", "size": "1536x928", "quality": "high", "moderation": "low", "background": "opaque", "output_format": "png", "n": 1 })
		self.assertTrue(asked["prompt"].startswith("a lighthouse"))
		# the retired models' parameters are never sent
		self.assertNotIn("response_format", asked)
		self.assertNotIn("style", asked)
		self.assertEqual(openai_requests("/v1/responses"), [])

	async def test_portrait_and_an_older_model_with_a_fixed_size(self):
		image = await self.picture(dsec("sk-good", orientation="portrait"), prompt="p", imageModel="gpt-image-1.5", quality="xhigh", randomizePrompt=False)
		self.assertEqual(image.size, (480, 800))
		[asked] = openai_requests("/v1/images/generations")
		self.assertEqual((asked["size"], asked["quality"]), ("1024x1536", "high"))

	async def test_the_prompt_is_rewritten_by_the_text_model_chosen(self):
		await self.picture(dsec("sk-good"), prompt="a lighthouse", imageModel="gpt-image-2.5-flare", randomizePrompt=True, promptModel="gpt-5.6-terra")
		[rewrite] = openai_requests("/v1/responses")
		self.assertEqual(rewrite["model"], "gpt-5.6-terra")
		self.assertIn("a lighthouse", rewrite["input"])
		self.assertNotIn("temperature", rewrite)
		[asked] = openai_requests("/v1/images/generations")
		self.assertTrue(asked["prompt"].startswith("A lighthouse drawn as a woodcut"))

	async def test_a_task_saved_before_this_runs_at_the_defaults(self):
		# an old task: no quality, no moderation, no prompt model; randomize on
		await self.picture(dsec("sk-good"), prompt="cats", imageModel="gpt-image-2", randomizePrompt=True)
		self.assertEqual(openai_requests("/v1/responses")[0]["model"], models.DEFAULT_TEXT_MODEL)
		self.assertEqual(openai_requests("/v1/images/generations")[0]["quality"], "auto")

	async def test_what_cannot_work_says_so_in_our_words_and_is_permanent(self):
		cases = [
			(dsec(None), { "imageModel": "gpt-image-2" }, "Enter the OpenAI API key"),
			(dsec("sk-good"), { "imageModel": "dall-e-3", "dalle3Quality": "hd" }, "OpenAI retired the image model dall-e-3"),
			(dsec("sk-good"), { "imageModel": "whisper-1" }, "not an image model"),
		]
		for context, params, words in cases:
			with self.subTest(params=params), self.assertRaises(PermanentError) as refused:
				await self.ds.open_async(context, { "prompt": "p", **params })
			self.assertIn(words, str(refused.exception))
		self.assertEqual(openai_requests("/v1/images/generations"), [], "nothing was asked of OpenAI")

	async def test_openais_refusals_never_carry_its_text_or_the_key(self):
		cases = [
			("sk-proj-wrongKEY123", { "imageModel": "gpt-image-2" }, PermanentError, "OpenAI refused the API key"),
			("sk-broke", { "imageModel": "gpt-image-2" }, PermanentError, "no credit left"),
			("sk-good", { "imageModel": "gpt-image-3" }, PermanentError, "does not offer the model gpt-image-3"),
			("sk-good", { "imageModel": "gpt-image-2", "randomizePrompt": True, "promptModel": "gpt-9" }, PermanentError, "does not offer the model gpt-9"),
		]
		for key, params, kind, words in cases:
			with self.subTest(key=key, params=params):
				with self.assertLogs("python.datasources.openai_image", level="DEBUG") as logs, self.assertRaises(kind) as refused:
					await self.picture(dsec(key), prompt="p", **{ "randomizePrompt": False, **params })
				self.assertIn(words, str(refused.exception))
				everything = str(refused.exception) + "\n".join(logs.output)
				self.assertNotIn("wrongKEY123", everything)
				self.assertNotIn("Incorrect API key", everything, "OpenAI's own text never reaches a message or the log")

class TestTheRoutes(WebApiTestBase):
	BASE = "/api/datasource/openai-image"

	def setUp(self):
		super().setUp()
		logging.getLogger("python.datasources.openai_image").setLevel(logging.CRITICAL)

	def test_the_lookups_list_what_the_saved_key_may_use(self):
		self.write_datasource_settings("openai-image", { "apiKey": "sk-good" })
		images = self.client.get(f"{self.BASE}/lookups/image-models")
		self.assertEqual(images.status_code, 200)
		self.assertEqual([c["value"] for c in images.json()], image_models(ALL_IDS))
		self.assertTrue(all(c["name"] == c["value"] for c in images.json()))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/text-models").json()], text_models(ALL_IDS))
		self.assertEqual([c["value"] for c in self.client.get(f"{self.BASE}/lookups/qualities").json()], list(models.QUALITIES))

	def test_the_models_route_says_what_each_takes(self):
		self.write_datasource_settings("openai-image", { "apiKey": "sk-good" })
		body = self.client.get(f"{self.BASE}/models").json()
		by_id = { m["id"]: m for m in body["image"] }
		self.assertEqual(by_id["gpt-image-2.5-flare"]["qualities"], ["auto", "low", "medium", "high", "xhigh", "max"])
		self.assertEqual((by_id["gpt-image-2"]["size"], by_id["gpt-image-2"]["sizes"]), ("free", []))
		self.assertEqual((by_id["gpt-image-1.5"]["size"], by_id["gpt-image-1.5"]["sizes"]), ("fixed", ["1024x1024", "1536x1024", "1024x1536"]))
		self.assertEqual(body["text"], text_models(ALL_IDS))

	def test_without_a_working_key_the_answer_says_why_and_holds_no_key(self):
		self.assertEqual(self.client.get(f"{self.BASE}/lookups/image-models").json()["message"], "Enter the OpenAI API key in the OpenAI Image settings and save them first.")
		self.write_datasource_settings("openai-image", { "apiKey": "sk-proj-wrongKEY123" })
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
		self.write_datasource_settings("openai-image", { "apiKey": "sk-good" })
		self.assertEqual(answer("********")["ok"], True)
