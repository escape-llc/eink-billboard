"""
The Credits page (#534): every credit is in one list, kept complete by these checks. Whoever downloads declares whose data it is, every font we ship is credited
(here and in NOTICE), and the two credits drawn on the panel are their descriptors' words.
"""
import glob
import json
import os
import unittest

from ..datasources.open_meteo.open_meteo import CREDIT as OPEN_METEO
from ..datasources.openweathermap.openweathermap import CREDIT as OPENWEATHERMAP
from ..datasources.thunderforest_map.thunderforest_map import ATTRIBUTION
from ..model.configuration_manager import FONT_FAMILIES
from ..web.credits import FONT_AUTHORS, SOFTWARE, USERS_OWN
from .test_web_api import WebApiTestBase

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

def descriptors() -> dict[str, dict]:
	found = {}
	for path in glob.glob(os.path.join(ROOT, "python", "datasources", "*", "datasource-info.json")):
		with open(path, encoding="utf-8") as f:
			info = json.load(f)
		found[info["id"]] = info
	return found

class TestEveryCreditIsDeclared(unittest.TestCase):
	def test_whoever_downloads_says_whose_data_it_is(self):
		for id, info in descriptors().items():
			with self.subTest(id):
				downloads = "internet" in info.get("features", [])
				if downloads and id not in USERS_OWN:
					self.assertIn("credit", info, "a source that downloads declares a credit, or is listed in USERS_OWN with the reason")
				if id in USERS_OWN:
					self.assertTrue(downloads, "only a source that downloads is excused")
					self.assertNotIn("credit", info)

	def test_a_credit_is_text_with_an_optional_licence_and_an_https_address(self):
		for id, info in descriptors().items():
			credit = info.get("credit")
			if credit is None:
				continue
			with self.subTest(id):
				self.assertLessEqual(set(credit), { "text", "license", "url" })
				self.assertTrue(isinstance(credit["text"], str) and credit["text"])
				if "url" in credit:
					self.assertTrue(credit["url"].startswith("https://"))

	def test_the_panels_credits_are_the_descriptors_words(self):
		found = descriptors()
		self.assertEqual(found["open-meteo"]["credit"]["text"], OPEN_METEO)
		self.assertEqual(found["openweathermap"]["credit"]["text"], OPENWEATHERMAP)
		self.assertEqual(found["thunderforest"]["credit"]["text"], ATTRIBUTION)

	def test_every_font_we_ship_is_credited_here_and_in_notice(self):
		self.assertEqual(set(FONT_AUTHORS), set(FONT_FAMILIES))
		with open(os.path.join(ROOT, "NOTICE"), encoding="utf-8") as f:
			notice = " ".join(f.read().split())
		for family, by in FONT_AUTHORS.items():
			self.assertIn(by, notice, family)

	def test_the_software_list_has_what_notice_names(self):
		names = { s["name"] for s in SOFTWARE }
		self.assertLessEqual({ "Material Symbols", "Waveshare e-Paper drivers" }, names)
		for item in SOFTWARE:
			self.assertTrue(item["by"] and item["license"] and item.get("url", "https://").startswith("https://"), item["name"])

class TestCreditsRoute(WebApiTestBase):
	def test_the_page_gets_the_data_the_fonts_and_the_software(self):
		body = self.client.get("/api/credits").json()
		data = { d["id"]: d for d in body["data"] }
		self.assertEqual(data["open-meteo"]["text"], OPEN_METEO)
		self.assertEqual(data["open-meteo"]["name"], "Open-Meteo")
		self.assertTrue(data["open-meteo"]["provider"])
		self.assertFalse(data["apod"]["provider"])
		self.assertNotIn("calendar", data)
		self.assertEqual([d["name"].casefold() for d in body["data"]], sorted(d["name"].casefold() for d in body["data"]))
		self.assertEqual({ f["name"] for f in body["fonts"] }, set(FONT_FAMILIES))
		self.assertIn("Leaflet", { s["name"] for s in body["software"] })
