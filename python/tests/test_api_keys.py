"""
API keys have one shape (`widget: "api-key"`): a string that is write-only and required, with a Test route of its own data source and a link to where a key is got. The form lays them out
alike (the Test joined to the input, the link under it, then the feedback); this keeps the descriptors alike. The Test routes of OpenWeatherMap and Comic Vine ask the (fake) service with
the key typed or the saved one, and answer in our words.
"""
import unittest

from ..web.documents import SECRET_MASK
from .test_web_api import WebApiTestBase

def key_properties(cm) -> list[tuple[str, dict]]:
	"""Every settings property of a data source or a plugin that is an API key, by owner."""
	found = []
	for kind, items in (("datasource", cm.enum_datasources()), ("plugin", cm.enum_plugins())):
		for item in items:
			settings = item["info"].get("settings")
			for prop in ((settings or {}).get("schema") or {}).get("properties") or []:
				if prop.get("widget") == "api-key" or prop.get("name") == "apiKey":
					found.append((f"{kind} {item['info']['id']}", prop))
	return found

class TestTheDescriptorsAreAlike(WebApiTestBase):
	def test_every_api_key_is_one_shape(self):
		found = key_properties(self.cm)
		self.assertGreaterEqual(len(found), 4)
		for owner, prop in found:
			with self.subTest(owner):
				self.assertEqual(prop.get("widget"), "api-key", "a property named apiKey says so")
				self.assertEqual(prop["type"], "string")
				self.assertIs(prop.get("writeOnly"), True)
				self.assertIs(prop.get("required"), True)
				self.assertTrue(str(prop.get("test", {}).get("url", "")).startswith("/api/datasource/"), "it has a Test of its own data source")
				self.assertTrue(str(prop.get("link", {}).get("url", "")).startswith("https://"), "it says where a key is got")

	def test_every_test_route_exists_and_answers_a_missing_key_in_words(self):
		for owner, prop in key_properties(self.cm):
			with self.subTest(owner):
				resp = self.client.post(prop["test"]["url"], json={ "value": "" })
				self.assertEqual(resp.status_code, 200, resp.text)
				answer = resp.json()
				self.assertEqual(sorted(answer), ["message", "ok"])
				self.assertIs(answer["ok"], False)

class TestOpenWeatherMapKey(WebApiTestBase):
	URL = "/api/datasource/openweathermap-api/test"

	def ask(self, value) -> dict:
		resp = self.client.post(self.URL, json={ "value": value })
		self.assertEqual(resp.status_code, 200, resp.text)
		return resp.json()

	def test_a_good_key_a_refused_key_and_a_busy_service(self):
		self.assertEqual(self.ask("good-key"), { "ok": True, "message": "OpenWeatherMap accepts this key." })
		refused = self.ask("wrong-key")
		self.assertFalse(refused["ok"])
		self.assertIn("refused this key", refused["message"])
		busy = self.ask("busy-key")
		self.assertFalse(busy["ok"])
		self.assertIn("too many requests", busy["message"])

	def test_the_saved_key_is_used_when_the_field_shows_the_mask_or_nothing(self):
		self.write_datasource_settings("openweathermap-api", { "apiKey": "good-key" })
		self.assertTrue(self.ask(SECRET_MASK)["ok"])
		self.assertTrue(self.ask(None)["ok"])
		self.write_datasource_settings("openweathermap-api", { "apiKey": "wrong-key" })
		self.assertFalse(self.ask(SECRET_MASK)["ok"])

	def test_nothing_typed_and_nothing_saved_is_a_no(self):
		for value in ("", "   ", None, 7, SECRET_MASK):
			self.assertEqual(self.ask(value), { "ok": False, "message": "Enter an API key first." }, repr(value))

	def test_the_key_is_not_in_the_answer(self):
		for key in ("good-key", "wrong-key", "busy-key"):
			self.assertNotIn(key, str(self.ask(key)))

	def test_the_settings_need_the_key(self):
		self.write_datasource_settings("openweathermap-api", { "apiKey": "good-key" })
		doc = self.client.get("/api/datasources/openweathermap-api/settings").json()
		resp = self.client.put("/api/datasources/openweathermap-api/settings", json={ **doc, "apiKey": None })
		self.assertEqual(resp.status_code, 422)
		self.assertIn(["apiKey"], [e["path"] for e in resp.json()["errors"]])

class TestComicVineKey(WebApiTestBase):
	URL = "/api/datasource/comicvine-api/test-key"

	def ask(self, value) -> dict:
		resp = self.client.post(self.URL, json={ "value": value })
		self.assertEqual(resp.status_code, 200, resp.text)
		return resp.json()

	def test_a_good_key_a_refused_key_and_a_busy_service(self):
		self.assertEqual(self.ask("cv-good"), { "ok": True, "message": "Comic Vine accepts this key." })
		self.assertIn("refused the API key", self.ask("wrong")["message"])
		self.assertIn("too many requests", self.ask("cv-busy")["message"])

	def test_the_saved_key_is_used_when_the_field_shows_the_mask(self):
		self.write_datasource_settings("comicvine-api", { "apiKey": "cv-good" })
		self.assertTrue(self.ask(SECRET_MASK)["ok"])

	def test_nothing_typed_and_nothing_saved_is_a_no_and_the_series_test_is_still_its_own_route(self):
		self.assertEqual(self.ask(""), { "ok": False, "message": "Enter an API key first." })
		self.assertEqual(self.client.post("/api/datasource/comicvine-api/test", json={ "value": "" }).json(), { "ok": False, "message": "Enter a series to search for." })

	def test_the_key_is_not_in_the_answer(self):
		for key in ("cv-good", "wrong", "cv-busy"):
			self.assertNotIn(key, str(self.ask(key)))

if __name__ == "__main__":
	unittest.main()
