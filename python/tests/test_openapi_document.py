"""
The web app's API types are generated from the committed OpenAPI document (app/src/api/openapi.json, #590): it must be the one the server describes, or a route
renamed or changed here would still type-check there. When this fails, run `cd app && npm run api` and commit both files it writes.
"""
import glob
import json
import os
import re
import unittest
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient

from scripts.export_openapi import DOCUMENT, as_text, openapi_document
from ..web.openapi import Answer, answers

class TestOpenApiDocument(unittest.TestCase):
	def test_the_committed_document_is_the_servers(self):
		with open(DOCUMENT, encoding="utf-8") as f:
			committed = f.read()
		self.assertEqual(committed, as_text(openapi_document()), "app/src/api/openapi.json is stale: run `cd app && npm run api` and commit the result")

	def test_it_holds_the_core_and_the_data_sources_routes(self):
		paths = openapi_document()["paths"]
		self.assertIn("/api/system", paths)
		self.assertIn("/api/access", paths)
		# a data source's own router (descriptor "router") is part of the API too
		self.assertTrue(any(p.startswith("/api/datasource/") for p in paths))

ROOT = os.path.dirname(os.path.dirname(__file__))

def _descriptors() -> Iterator[tuple[str, Any]]:
	"""Every descriptor and every shipped settings schema, by file name: what names an address of the API for the form to call."""
	for path in sorted(glob.glob(os.path.join(ROOT, "**", "*-info.json"), recursive=True) + glob.glob(os.path.join(ROOT, "storage", "schemas", "*.json"))):
		with open(path, encoding="utf-8") as f:
			yield os.path.relpath(path, ROOT), json.load(f)

def _addresses(node: Any) -> Iterator[tuple[str, str]]:
	"""(kind, address) for each address a descriptor names: a Test button's (`test.url`), a row action's (`action.url`), a URL lookup's (in `lookups`)."""
	if isinstance(node, list):
		for item in node:
			yield from _addresses(item)
	elif isinstance(node, dict):
		for key, value in node.items():
			if key in ("test", "action") and isinstance(value, dict) and isinstance(value.get("url"), str):
				yield key, value["url"]
			elif key == "lookups" and isinstance(value, dict):
				for lookup in value.values():
					if isinstance(lookup, dict) and isinstance(lookup.get("url"), str):
						yield "lookup", lookup["url"]
			yield from _addresses(value)

class TestDescriptorAddresses(unittest.TestCase):
	"""
	The form calls the addresses a descriptor names (a Test, a row action, a URL lookup) by address, so the web app cannot type them by path (#590): each must be a route of the
	document that declares the answer the form reads (TestUrlButton: `TestAnswer`; RowAction: `RowStep` for each step; a lookup: a list of choices,
	each a `name` and a `value` that are strings).
	"""
	paths: dict[str, Any]
	schemas: dict[str, Any]

	@classmethod
	def setUpClass(cls):
		document = openapi_document()
		cls.paths, cls.schemas = document["paths"], document["components"]["schemas"]

	def operation(self, address: str, method: str) -> dict:
		for template, operations in self.paths.items():
			# a path parameter (escaped `\{name\}`) stands for one segment
			if re.fullmatch(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)), address) and method in operations:
				return operations[method]
		self.fail(f"{method.upper()} {address} is not a route of the API")

	def answer(self, address: str, method: str) -> dict:
		return self.operation(address, method)["responses"]["200"]["content"]["application/json"]["schema"]

	def test_every_address_a_descriptor_names_answers_what_the_form_reads(self):
		found = { "test": 0, "action": 0, "lookup": 0 }
		for name, descriptor in _descriptors():
			for kind, address in _addresses(descriptor):
				found[kind] += 1
				with self.subTest(file=name, address=address):
					if kind == "test":
						self.assertEqual(self.answer(address, "post").get("$ref"), "#/components/schemas/TestAnswer")
					elif kind == "action":
						for step in ("start", "continue", "poll"):
							self.assertEqual(self.answer(f"{address}/{step}", "post").get("$ref"), "#/components/schemas/RowStep", step)
					else:
						schema = self.answer(address, "get")
						self.assertEqual(schema.get("type"), "array")
						item = self.schemas[schema["items"]["$ref"].rsplit("/", 1)[-1]]
						self.assertEqual({ field: item["properties"][field]["type"] for field in ("name", "value") }, { "name": "string", "value": "string" })
						self.assertLessEqual({ "name", "value" }, set(item.get("required", [])))
		# the walk finds them: a descriptor that moved its addresses elsewhere would make this test pass with nothing checked
		self.assertTrue(all(found.values()), found)

class Reading(Answer):
	name: str
	value: int | None = None

class TestAnswers(unittest.TestCase):
	"""An answer model names every field: one the code adds and the model lacks fails the route, and one the code leaves out stays out."""
	def client(self, answer: dict) -> TestClient:
		app = FastAPI()
		@app.get("/x", **answers(Reading))
		def route():
			return answer
		return TestClient(app)

	def test_a_field_the_model_does_not_name_fails_instead_of_vanishing(self):
		with self.assertRaises(ResponseValidationError):
			self.client({ "name": "a", "extra": 1 }).get("/x")

	def test_a_field_left_out_is_absent_not_null(self):
		self.assertEqual(self.client({ "name": "a" }).get("/x").json(), { "name": "a" })
		self.assertEqual(self.client({ "name": "a", "value": None }).get("/x").json(), { "name": "a", "value": None })

if __name__ == "__main__":
	unittest.main()
