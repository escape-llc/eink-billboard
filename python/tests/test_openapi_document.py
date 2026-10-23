"""
The web app's API types are generated from the committed OpenAPI document (app/src/api/openapi.json, #590): it must be the one the server describes, or a route
renamed or changed here would still type-check there. When this fails, run `cd app && npm run api` and commit both files it writes.
"""
import unittest

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
