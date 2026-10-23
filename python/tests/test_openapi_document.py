"""
The web app's API types are generated from the committed OpenAPI document (app/src/api/openapi.json, #590): it must be the one the server describes, or a route
renamed or changed here would still type-check there. When this fails, run `cd app && npm run api` and commit both files it writes.
"""
import unittest

from scripts.export_openapi import DOCUMENT, as_text, openapi_document

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

if __name__ == "__main__":
	unittest.main()
