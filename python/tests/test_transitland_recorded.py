"""
Transitland's real answers (#429), recorded by `scripts.record_http_fixtures --transitland` into fixtures/http/recorded/ and read here with the provider's own
parsers: what they make of a real answer, where the hand-written fixtures (whose made-up stops and alerts the behaviour tests name) can only say what we
expected. Nothing here asserts a value of the day the answers were recorded (a stop's name, a time): only that each answer is read, and read whole.
The recordings are git-ignored (answers fetched with your own key are yours, not the repository's): skipped where there are none, as in CI.
"""
import json
import os
import re
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from ..datasources.transitland_api.transitland_api import add_route_alerts, nearby_choices, parse_departures, refusal, stop_key_of
from ..plugins.plugin_base import PermanentError
from .fake_internet import FIXTURES

RECORDED = os.path.join(FIXTURES, "recorded")
SEATTLE = (47.61, -122.33)
ZONE = ZoneInfo("America/Los_Angeles")

def recorded(name: str) -> dict:
	with open(os.path.join(RECORDED, name), encoding="utf-8") as f:
		return json.load(f)

@unittest.skipUnless(os.path.isfile(os.path.join(RECORDED, "transitland-notes.json")), "Transitland's answers are not recorded (scripts/record_http_fixtures.py --transitland)")
class TestRealAnswersAreRead(unittest.TestCase):
	def setUp(self):
		self.notes = recorded("transitland-notes.json")
		self.stop = self.notes["stop"]
		self.entry = { "name": "Recorded", "stopKey": self.stop["onestop_id"], "walkMinutes": 0 }

	def test_the_stops_near_a_point_are_choices_nearest_first(self):
		data = recorded("transitland-stops-near.json")
		choices = nearby_choices(data, *SEATTLE)
		self.assertTrue(choices, "a real answer near downtown Seattle gives choices")
		# every stop with a key and a position is a choice: none is lost to a field read wrongly
		placed = [s for s in data["stops"] if stop_key_of(s) and (s.get("geometry") or {}).get("coordinates")]
		self.assertEqual(len(choices), len(placed))
		self.assertTrue(all(c["value"] and re.search(r" \(\d+(\.\d)? k?m\)$", c["name"]) for c in choices), [c["name"] for c in choices])

	def test_a_search_finds_the_stop_by_its_name_and_a_key_is_that_stop(self):
		found = nearby_choices(recorded("transitland-stops-search.json"), *SEATTLE)
		self.assertIn(self.stop["onestop_id"], [c["value"] for c in found], "searching for a stop's own name finds it")
		[by_key] = recorded("transitland-stop-key.json")["stops"]
		self.assertEqual(stop_key_of(by_key), self.stop["onestop_id"])

	@unittest.skipUnless(os.path.isfile(os.path.join(RECORDED, "transitland-departures.json")), "no departures were recorded (recorded at night?)")
	def test_the_departures_are_read_soonest_first_each_with_its_route(self):
		data = recorded("transitland-departures.json")
		report = parse_departures(data, self.entry, datetime.now(ZONE), "en-US", ZONE)
		raw = sum(len(s.get("departures") or []) for s in data["stops"])
		self.assertTrue(report.departures, "the departures recorded are read")
		self.assertEqual(len(report.departures), raw, "every departure of the answer is read: none is dropped by a field read wrongly")
		whens = [d.when for d in report.departures]
		self.assertEqual(whens, sorted(whens))
		self.assertTrue(all(d.when.tzinfo is not None and d.route.label for d in report.departures))
		self.assertEqual(report.stop.key, self.stop["onestop_id"])
		# the alerts of the routes are added to it without a fault, each once
		add_route_alerts(report, recorded("transitland-routes.json"), self.entry, "en-US")
		self.assertEqual(len({ a.key for a in report.alerts }), len(report.alerts))

	def test_a_wrong_key_is_refused_with_a_status_we_say_in_our_words(self):
		wrong = self.notes["calls"]["wrong-key"]
		self.assertIn(wrong["status"], (401, 403))
		self.assertIsInstance(refusal(wrong["status"]), PermanentError)

if __name__ == "__main__":
	unittest.main()
