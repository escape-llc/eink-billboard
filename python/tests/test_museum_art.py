"""
Museum Art (#618): each museum's search, the public-domain check on every record, the kept answers, and the page.
The museums are the fake internet's (python/tests/fake_internet.py `_museums`), from fixtures in their shapes.
"""
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from ..datasources.museum_art import museum_art as museum_module
from ..datasources.museum_art import museums
from ..datasources.museum_art.museum_art import MuseumArtAsync, caption_of, chosen
from ..datasources.museum_art.museums import AIC_IIIF, MUSEUMS, ArtInstitute, museum_of
from ..model.configuration_manager import DatasourceConfigurationManager
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import chrome_command
from .fake_internet import FakeInternet
from .test_datasource_fixes import TZ_TOKYO, FakeRenderSession, make_dsec
from .utils import temp_configuration_manager, test_output_path_for, use_transport

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=TZ_TOKYO)

def source() -> MuseumArtAsync:
	return MuseumArtAsync("museum-art", "Museum Art")

class TestChoices(unittest.TestCase):
	def test_the_museum_is_one_of_three_and_unset_is_the_art_institute(self):
		self.assertIs(museum_of({}), MUSEUMS["aic"])
		self.assertIs(museum_of({ "museum": "met" }), MUSEUMS["met"])
		with self.assertRaises(PermanentError):
			museum_of({ "museum": "louvre" })

	def test_the_search_is_trimmed_and_the_department_is_the_mets_only(self):
		self.assertEqual(chosen({ "museum": "met", "search": "  van   gogh ", "department": "11" }), ("met", "van gogh", "11"))
		self.assertEqual(chosen({ "museum": "aic", "department": "11" }), ("aic", "", None))
		self.assertEqual(chosen({ "museum": "met", "department": "11; drop" }), ("met", "", None))

	def test_the_art_institute_filters_in_the_body(self):
		body = ArtInstitute.body("water lilies", 25)
		self.assertEqual(body["from"], 25)
		filters = body["query"]["bool"]["filter"]
		self.assertIn({ "term": { "is_public_domain": True } }, filters)
		self.assertIn({ "exists": { "field": "image_id" } }, filters)
		self.assertEqual(body["query"]["bool"]["must"][0]["multi_match"]["operator"], "and")
		self.assertEqual(ArtInstitute.body("", 0)["query"]["bool"]["must"], [])

	def test_the_caption_names_the_museum(self):
		self.assertEqual(caption_of({ "museum": "met", "title": "Sunflowers", "artist": "Vincent van Gogh", "date": "1887" }),
			{ "title": "Sunflowers", "artist": "Vincent van Gogh", "date": "1887", "museum": "The Met" })
		self.assertEqual(caption_of({})["title"], "Untitled")

class TestSearch(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)

	async def test_the_art_institute_shows_only_public_domain_works_with_a_picture(self):
		works = await source().open_async(make_dsec(ts=NOW), { "museum": "aic", "search": "monet" })
		self.assertEqual(sorted(w["title"] for w in works), ["Arrival of the Normandy Train, Gare Saint-Lazare", "Water Lilies"])
		self.assertIn(AIC_IIIF.format("3c27b499-af56-f0d5-93b5-a7f2f1ad5813"), [w["image"] for w in works])
		[asked] = self.fake.requests
		self.assertEqual((asked.method, asked.headers.get("AIC-User-Agent", "")[:14]), ("POST", "eink-billboard"))

	async def test_the_met_asks_for_each_work_and_skips_what_is_not_public_domain(self):
		works = await source().open_async(make_dsec(ts=NOW), { "museum": "met", "search": "van gogh", "department": "11" })
		self.assertEqual(sorted(w["title"] for w in works), ["Sunflowers", "Wheat Field with Cypresses"])
		search = self.fake.requests[0]
		self.assertEqual(search.url.path, "/public/collection/v1.1/search")
		self.assertEqual((search.url.params["isPublicDomain"], search.url.params["hasImages"], search.url.params["departmentId"]), ("true", "true", "11"))
		# the search, then one call per object
		self.assertEqual(len(self.fake.requests), 1 + 4)

	async def test_cleveland_answers_whole_records_and_only_cc0_is_shown(self):
		works = await source().open_async(make_dsec(ts=NOW), { "museum": "cleveland", "search": "monet" })
		self.assertEqual(sorted(w["title"] for w in works), ["The Red Kerchief", "Water Lilies (Agapanthus)"])
		self.assertEqual(works[0]["artist"], "Claude Monet (French, 1840–1926)")
		self.assertEqual(self.fake.requests[0].url.params["cc0"], "1")

	async def test_a_search_with_no_match_says_so(self):
		for museum in MUSEUMS:
			with self.subTest(museum=museum):
				with self.assertRaisesRegex(PermanentError, "no public-domain works with a picture that match “nothing”"):
					await source().open_async(make_dsec(ts=NOW), { "museum": museum, "search": "nothing" })

	async def test_a_museum_that_refuses_is_our_words_with_its_status(self):
		use_transport(self, httpx.MockTransport(lambda request: httpx.Response(503, text="the museum's own words with https://example.test/secret")))
		with self.assertRaises(RuntimeError) as caught:
			await source().open_async(make_dsec(ts=NOW), { "museum": "aic" })
		self.assertEqual(str(caught.exception), "'Museum Art' could not search Art Institute of Chicago (Art Institute of Chicago answered 503).")

	async def test_a_museum_that_cannot_be_reached_says_so(self):
		def refuse(request: httpx.Request) -> httpx.Response:
			raise httpx.ConnectError("no route to https://example.test/secret", request=request)
		use_transport(self, httpx.MockTransport(refuse))
		with self.assertRaisesRegex(RuntimeError, r"^'Museum Art' could not reach The Met \(ConnectError\)\.$"):
			await source().open_async(make_dsec(ts=NOW), { "museum": "met" })

	async def test_a_random_page_stays_within_what_the_museum_pages_to(self):
		offsets = []
		async def page(client, ask, query, department, offset):
			offsets.append(offset)
			return { "total": 62119, "items": [] }
		aic = MUSEUMS["aic"]
		with patch.object(aic, "page", page), patch.object(museums.random, "randrange", lambda n: n - 1):
			await aic.search(httpx.AsyncClient(), lambda key, fetch: fetch(), "", None)
		# the deepest page the Art Institute allows: from + limit <= 1,000
		self.assertEqual(offsets, [0, 1000 - museums.PAGE])

	async def test_a_small_search_asks_once(self):
		await source().open_async(make_dsec(ts=NOW), { "museum": "cleveland" })
		self.assertEqual(len(self.fake.requests), 1)

class TestKept(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)
		cm = temp_configuration_manager(self)
		self.dsec = make_dsec(ts=NOW)
		self.dsec.provider.add_service(DatasourceConfigurationManager, cm.datasource_manager("museum-art"))  # type: ignore[attr-defined]

	async def test_a_search_and_the_mets_works_are_kept(self):
		await source().open_async(self.dsec, { "museum": "met" })
		first = len(self.fake.requests)
		await source().open_async(self.dsec, { "museum": "met" })
		self.assertEqual(len(self.fake.requests), first, "the second list is made from kept answers")

	async def test_a_picture_is_kept(self):
		[work, *_] = await source().open_async(self.dsec, { "museum": "cleveland" })
		with patch.object(museum_module, "RenderSession", FakeRenderSession):
			await source().render_async(self.dsec, { "museum": "cleveland" }, work)
			before = len(self.fake.requests)
			await source().render_async(self.dsec, { "museum": "cleveland" }, work)
		self.assertEqual(len(self.fake.requests), before)

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		use_transport(self, FakeInternet())

	async def test_a_work_is_drawn_at_the_target_size_with_its_caption(self):
		works = await source().open_async(make_dsec(ts=NOW), { "museum": "met" })
		with patch.object(museum_module, "RenderSession", FakeRenderSession):
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				result = await source().render_async(make_dsec(orientation, ts=NOW), { "museum": "met" }, works[0])
				assert result is not None and FakeRenderSession.last is not None
				self.assertEqual(result.image.size, size)
				self.assertEqual(FakeRenderSession.last.params["museum"], "The Met")
				self.assertTrue(FakeRenderSession.last.params["picture"].startswith("data:image/jpeg;base64,"))

	async def test_without_the_caption_the_picture_is_not_rendered_again(self):
		works = await source().open_async(make_dsec(ts=NOW), { "museum": "aic" })
		FakeRenderSession.last = None
		with patch.object(museum_module, "RenderSession", FakeRenderSession):
			result = await source().render_async(make_dsec(ts=NOW), { "museum": "aic", "showCaption": False }, works[0])
		assert result is not None
		self.assertEqual(result.image.size, (800, 480))
		self.assertIsNone(FakeRenderSession.last)

	async def test_a_picture_that_does_not_load_is_our_words(self):
		use_transport(self, httpx.MockTransport(lambda request: httpx.Response(200, content=b"not a picture", headers={ "Content-Type": "image/jpeg" })))
		with self.assertRaisesRegex(RuntimeError, "cannot be read"):
			await source().render_async(make_dsec(ts=NOW), {}, { "museum": "aic", "image": "https://www.artic.edu/iiif/2/x/full/843,/0/default.jpg" })

	async def test_anything_but_a_work_is_nothing_to_show(self):
		self.assertIsNone(await source().render_async(make_dsec(ts=NOW), {}, None))
		self.assertIsNone(await source().render_async(make_dsec(ts=NOW), {}, { "title": "no picture" }))

	def test_the_fixtures_hold_a_work_in_copyright_and_one_without_a_picture(self):
		# so the checks above are checks: each museum's answer has something that must not be shown
		from .fake_internet import fixture_text
		aic = json.loads(fixture_text("museum-aic-search.json"))["data"]
		self.assertTrue(any(i["is_public_domain"] is False for i in aic) and any(i["image_id"] is None for i in aic))
		met = json.loads(fixture_text("museum-met-objects.json")).values()
		self.assertTrue(any(r["isPublicDomain"] is False for r in met) and any(r["isPublicDomain"] and not r["primaryImageSmall"] for r in met))
		cma = json.loads(fixture_text("museum-cleveland-search.json"))["data"]
		self.assertTrue(any(i["share_license_status"] != "CC0" for i in cma))

	async def test_the_mets_old_search_is_gone(self):
		# the fake answers as The Met does since 2026-10-01: a client that still asked v1 would be refused
		client = httpx.AsyncClient(transport=FakeInternet())
		response = await client.get("https://collectionapi.metmuseum.org/public/collection/v1/search?q=x")
		self.assertEqual(response.status_code, 410)
		self.assertEqual(museums.MET_SEARCH, "https://collectionapi.metmuseum.org/public/collection/v1.1/search")

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The page as Chromium draws it. The images are in .test-output/museum_art for a look."""
	def setUp(self):
		use_transport(self, FakeInternet())

	async def test_a_work_with_its_caption(self):
		folder = Path(test_output_path_for("museum_art"))
		for museum in MUSEUMS:
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				with self.subTest(museum=museum, orientation=orientation):
					works = await source().open_async(make_dsec(orientation, ts=NOW), { "museum": museum })
					result = await source().render_async(make_dsec(orientation, ts=NOW), { "museum": museum }, works[0])
					assert result is not None
					self.assertEqual(result.image.size, size)
					result.image.save(folder.joinpath(f"{museum}-{orientation}.png"))

if __name__ == "__main__":
	unittest.main()
