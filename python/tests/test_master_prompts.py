"""
The Master Prompts (`master-prompts`, a device-wide settings document): the system prompts of the generators were hard-coded and are now the user's to edit,
with the factory text shipped in the NVE and put back on request; and the fields (`{prompt}`) a prompt may use, which the schema lists and both the form and the
server check.
"""
import json
import os
import tempfile
import unittest

from ..datasources.ai.prompt import PROMPTS, SETTINGS, master_prompts, rewrite_request, with_canvas
from ..datasources.ai_image.ai_image import GeneratedImageAsync
from ..model.configuration_manager import ConfigurationManager
from ..utils.prompt_tokens import fill_tokens, token_names, unknown_token
from .test_openai_image import TASK, context, openai_requests, storage
from .test_web_api import WebApiTestBase

NVE_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "schemas", "master-prompts.json")

def shipped() -> dict:
	with open(NVE_SCHEMA, encoding="utf-8") as f:
		return json.load(f)

def save_prompts(cm: ConfigurationManager, document: dict) -> None:
	cob = cm.settings_manager().open(SETTINGS)
	rev, _ = cob.get()
	committed, _ = cob.save(rev, document)
	assert committed

class TestTheFields(unittest.TestCase):
	def test_a_text_names_its_fields_once_each(self):
		self.assertEqual(token_names("Draw {prompt} at {temp}, {temp}; {{literal}} { alone } {1} {a b}"), ["prompt", "temp"])
		self.assertEqual(token_names(""), [])

	def test_an_unknown_field_is_found(self):
		self.assertIsNone(unknown_token("{prompt} {temp}", ["prompt", "temp", "wind"]))
		self.assertEqual(unknown_token("{prompt} {colour} {wind}", ["prompt"]), "colour")
		self.assertEqual(unknown_token("{{prompt}}", []), None, "a doubled brace is a brace, not a field")

	def test_a_field_is_filled_and_a_missing_one_drops_out(self):
		self.assertEqual(fill_tokens('Original: "{prompt}"', { "prompt": "a cat" }), 'Original: "a cat"')
		self.assertEqual(fill_tokens("It is {temp} and {sky}.", { "temp": "18°C", "sky": None }), "It is 18°C and .")
		self.assertEqual(fill_tokens("{missing}!", {}), "!")
		self.assertEqual(fill_tokens("a {{literal}} and {x}", { "x": 1 }), "a {literal} and 1")

class TestTheShippedPrompts(unittest.TestCase):
	def test_the_nve_holds_every_prompt_and_the_schema_lists_the_fields_each_may_use(self):
		doc = shipped()
		names = [p["name"] for p in doc["schema"]["properties"]]
		self.assertEqual(names, list(PROMPTS))
		self.assertEqual(set(doc["default"]), set(PROMPTS))
		for prop in doc["schema"]["properties"]:
			with self.subTest(prop["name"]):
				self.assertEqual(prop["format"], "multiline")
				self.assertTrue(prop["required"] and prop["title"] and prop["description"])
				self.assertIsInstance(prop["tokens"], list, "a prompt says which fields it may use, even none")
				self.assertTrue(all(t["name"] and t["description"] for t in prop["tokens"]))
				# the factory text uses only the fields its prompt lists, and is a valid value of its own property
				self.assertIsNone(unknown_token(doc["default"][prop["name"]], [t["name"] for t in prop["tokens"]]))
				self.assertLessEqual(len(doc["default"][prop["name"]]), prop["maxLength"])
		self.assertEqual([t["name"] for t in next(p for p in doc["schema"]["properties"] if p["name"] == "rewriteRequest")["tokens"]], ["prompt"])

	def test_a_new_storage_is_seeded_with_them(self):
		cm = storage(None)
		_, seeded = cm.settings_manager().open(SETTINGS).get()
		self.assertEqual(seeded, shipped()["default"])
		self.assertEqual(cm.shipped_settings(SETTINGS), shipped()["default"])
		self.assertEqual(cm.shipped_settings("no-such-document"), {})

	def test_the_prompts_say_what_they_said_before_they_were_settings(self):
		prompts = master_prompts(storage(None))
		instructions, request = rewrite_request(prompts, "")
		self.assertTrue(instructions.startswith("You are a creative assistant generating extremely random and unique image prompts."))
		self.assertTrue(request.startswith("Give me a completely random image prompt"))
		instructions, request = rewrite_request(prompts, "a lighthouse")
		self.assertTrue(instructions.startswith("You are a creative assistant specializing in generating highly descriptive and unique prompts"))
		self.assertTrue(request.startswith('Original prompt: "a lighthouse"\nRewrite it to make it more detailed'))
		self.assertTrue(with_canvas(prompts, "a lighthouse").startswith("a lighthouse. The image should fully occupy the entire canvas"))
		self.assertTrue(with_canvas(prompts, "Is that a lighthouse?").startswith("Is that a lighthouse? The image should"))

class TestWhatTheGeneratorsRead(unittest.IsolatedAsyncioTestCase):
	def test_what_the_user_saved_is_used_and_a_blank_or_missing_prompt_is_the_factory_text(self):
		cm = storage(None)
		save_prompts(cm, { "inventInstructions": "Be brief.", "rewriteRequest": "   ", "canvas": 3 })
		prompts = master_prompts(cm)
		factory = shipped()["default"]
		self.assertEqual(prompts["inventInstructions"], "Be brief.")
		self.assertEqual(prompts["rewriteRequest"], factory["rewriteRequest"])
		self.assertEqual(prompts["canvas"], factory["canvas"])
		self.assertEqual(prompts["rewriteInstructions"], factory["rewriteInstructions"])

	async def test_an_edited_prompt_reaches_the_text_model_and_the_image_model(self):
		cm = storage("sk-good")
		save_prompts(cm, { **shipped()["default"], "rewriteInstructions": "Write like a pirate.", "rewriteRequest": "Pirate this: {prompt}", "canvas": "Keep it flat." })
		master = GeneratedImageAsync("ai-image", "Generated Image")
		dsec = context(cm)
		task = { **TASK, "randomizePrompt": True }
		before = len(openai_requests("/v1/responses"))
		state = await master.open_async(dsec, task)
		result = await master.render_async(dsec, task, state[0])
		assert result is not None
		asked = openai_requests("/v1/responses")[before:]
		self.assertEqual((asked[0]["instructions"], asked[0]["input"]), ("Write like a pirate.", "Pirate this: a lighthouse"))
		self.assertTrue(openai_requests("/v1/images/generations")[-1]["prompt"].endswith(" Keep it flat."))

class TestTheSettingsRoutes(WebApiTestBase):
	URL = "/api/settings/master-prompts"

	def test_the_document_is_served_with_its_schema_and_the_fields_each_prompt_may_use(self):
		doc = self.client.get(self.URL).json()
		self.assertEqual({ k: doc[k] for k in PROMPTS }, shipped()["default"])
		schema = self.client.get("/api/schemas/master-prompts").json()
		request = next(p for p in schema["schema"]["properties"] if p["name"] == "rewriteRequest")
		self.assertEqual(request["tokens"], [{ "name": "prompt", "description": "The prompt written in the task." }])

	def test_the_factory_values_come_from_the_nve_whatever_is_stored(self):
		doc = self.client.get(self.URL).json()
		edited = { **doc, "canvas": "My own picture rules." }
		saved = self.client.put(self.URL, json=edited)
		self.assertEqual(saved.status_code, 200)
		self.assertEqual(self.client.get(self.URL).json()["canvas"], "My own picture rules.")
		defaults = self.client.get(f"{self.URL}/defaults")
		self.assertEqual(defaults.status_code, 200)
		self.assertEqual(defaults.json(), shipped()["default"], "the factory text, not the stored one, and no `_id` or `_rev`")
		self.assertEqual(self.client.get("/api/settings/nothing/defaults").status_code, 404)

	def test_an_unknown_field_is_refused_on_the_property_that_holds_it(self):
		doc = self.client.get(self.URL).json()
		for name, text, message in (("rewriteRequest", "Original: {prompt} and {colour}", "Unknown field {colour}"), ("canvas", "Use {prompt} here", "Unknown field {prompt}")):
			with self.subTest(name):
				answer = self.client.put(self.URL, json={ **doc, name: text })
				self.assertEqual(answer.status_code, 422)
				self.assertIn({ "path": [name], "message": message }, answer.json()["errors"])
		accepted = self.client.put(self.URL, json={ **doc, "rewriteRequest": "Original: {prompt} {{and}} braces" })
		self.assertEqual(accepted.status_code, 200)

	def test_a_prompt_cannot_be_empty_or_too_long(self):
		doc = self.client.get(self.URL).json()
		self.assertEqual(self.client.put(self.URL, json={ **doc, "canvas": "" }).status_code, 422)
		self.assertEqual(self.client.put(self.URL, json={ **doc, "canvas": "x" * 4001 }).status_code, 422)

class TestReadingWhenNothingIsStored(unittest.TestCase):
	def test_a_storage_without_the_document_still_has_the_prompts(self):
		with tempfile.TemporaryDirectory() as folder:
			cm = ConfigurationManager(storage_path=folder)
			cm.hard_reset()
			os.remove(os.path.join(folder, "settings", f"{SETTINGS}-settings.json"))
			self.assertEqual(master_prompts(cm), shipped()["default"])
