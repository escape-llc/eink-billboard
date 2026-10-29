"""
Transitland as a transit provider (#429 PR 1): the departures answer normalized into a `TransitReport`, the stops near a point, the kept answer that guards the
quota (its floor, its "as of", a refusal served from it, the routine share), and the routes (the key's and a stop's Test, the stop lookup). Against the fake
internet's Transitland, which answers fixtures written in the OpenAPI schema's shapes, by the key in the `apikey` header.
"""
import asyncio
import json
import unittest
from datetime import datetime, timedelta
from typing import Any, cast
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ..datasources import keeping
from ..datasources.contracts import CONTRACTS
from ..datasources.contracts.transit import CANCELLED, INTERVALS_ONLY, SCHEDULED, TransitApi, TransitReport
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.metering import METER, QuotaUsedUp
from ..datasources.transitland_api.transitland_api import CREDIT, DATASOURCE_ID, TransitlandApi, distance_text, looks_like_key, nearby_choices, parse_departures, stop_path, translated
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from .fake_internet import FakeInternet, fixture_text
from .test_weather import SEATTLE, FakeSettings
from .test_web_api import WebApiTestBase
from .utils import save_datasource_settings, temp_configuration_manager, use_transport

LA = ZoneInfo("America/Los_Angeles")
# the fixtures' moment: noon in Seattle, 19:00 UTC
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=LA)
MAIN = { "name": "Home", "stopKey": "s-c23nb-mainst~3rd", "walkMinutes": 5 }

def board(entry: dict[str, Any] = MAIN, name: str = "transitland-departures.json", fetched_at: datetime = NOW, language: str = "en-US") -> TransitReport:
	return parse_departures(json.loads(fixture_text(name)), entry, fetched_at, language, LA)

class TestTheAnswerNormalized(unittest.TestCase):
	def test_departures_are_soonest_first_with_the_live_time_when_there_is_one(self):
		r = board()
		self.assertEqual([(d.when.strftime("%H:%M"), d.route.label, d.headsign, d.live, d.status) for d in r.departures], [
			("12:02", "7", "Uptown", False, SCHEDULED),
			("12:07", "23", "Downtown", True, SCHEDULED),
			("12:12", "45X", "Airport", False, CANCELLED),
			("12:20", "23", "Downtown", False, SCHEDULED),
			("12:35", "45X", "Airport", False, SCHEDULED),
		])
		live = r.departures[1]
		self.assertEqual((live.scheduled.strftime("%H:%M"), live.delay, live.route.color, live.route.text_color), ("12:05", 120, "#0066cc", "#ffffff"))
		self.assertFalse(r.departures[2].running)
		self.assertIsNone(r.departures[0].route.color)

	def test_every_time_is_aware_and_in_the_stops_zone(self):
		r = board()
		self.assertEqual(r.stop.zone, "America/Los_Angeles")
		for d in r.departures:
			self.assertEqual(d.when.utcoffset(), timedelta(hours=-7))
		self.assertEqual((r.stop.name, r.stop.key, r.credit, r.walk_minutes), ("Main St & 3rd Ave", "s-c23nb-mainst~3rd", CREDIT, 5))

	def test_an_alert_is_kept_once_however_many_trips_carry_it_and_only_while_it_is_not_over(self):
		r = board()
		self.assertEqual(sorted((a.header, a.severity, a.effect) for a in r.alerts), [("Elevator out of service", "warning", "accessibility_issue"), ("Route 45X detoured", "severe", "detour")])
		elevator = next(a for a in r.alerts if a.header.startswith("Elevator"))
		self.assertEqual((elevator.description, elevator.url), ("Use the ramp on 3rd Ave.", "https://example.org/alerts/elevator"))
		# the detour ends at 18:00 (01:00 UTC): active at noon, not after
		self.assertEqual(len(r.active_alerts(NOW)), 2)
		self.assertEqual([a.header for a in r.active_alerts(NOW + timedelta(hours=7))], ["Elevator out of service"])

	def test_alert_text_follows_the_devices_language(self):
		self.assertIn("Ascensor fuera de servicio", [a.header for a in board(language="es-MX").alerts])
		texts = [{ "language": "fr", "text": "Bonjour" }, { "language": "en-GB", "text": "Hello" }]
		self.assertEqual(translated(texts, "fr-CA"), "Bonjour")
		self.assertEqual(translated(texts, "de-DE"), "Hello", "English when the language is not there")
		self.assertEqual(translated([{ "text": "Only" }], "de"), "Only")
		self.assertEqual(translated(None, "en"), "")

	def test_a_route_filter_keeps_only_its_routes_and_their_alerts(self):
		r = board({ **MAIN, "routes": "23, 7" })
		self.assertEqual({ d.route.label for d in r.departures }, { "23", "7" })
		self.assertEqual([a.header for a in r.alerts], ["Elevator out of service"], "the detour is on route 45X, which is left out")

	def test_a_station_shows_its_platforms_departures_in_the_devices_zone_when_it_names_none(self):
		r = board({ "name": "Central", "stopKey": "s-c23nc-central" }, "transitland-departures-station.json")
		self.assertEqual([(d.when.strftime("%H:%M"), d.platform) for d in r.departures], [("12:10", "2"), ("12:30", "1")])
		self.assertEqual(r.stop.zone, "America/Los_Angeles")

	def test_a_stop_that_publishes_intervals_says_so(self):
		self.assertEqual(board({ "name": "Ferry", "stopKey": "s-c23p0-ferry" }, "transitland-departures-intervals.json").notes, [INTERVALS_ONLY])
		self.assertEqual(board().notes, [])

	def test_an_answer_with_no_stop_is_not_one(self):
		with self.assertRaises(RuntimeError):
			parse_departures({ "stops": [] }, MAIN, NOW, "en", LA)

	def test_a_departure_across_a_daylight_saving_change_reads_in_the_new_offset(self):
		answer = json.loads(fixture_text("transitland-departures.json"))
		# 1 November 2026, 09:30 UTC: 01:30 PST, after the clocks went back at 02:00 PDT (09:00 UTC); 08:30 UTC is 01:30 PDT
		answer["stops"][0]["departures"] = [answer["stops"][0]["departures"][2], dict(answer["stops"][0]["departures"][2])]
		answer["stops"][0]["departures"][0] = { **answer["stops"][0]["departures"][0], "departure": { "scheduled_utc": "2026-11-01T08:30:00Z" } }
		answer["stops"][0]["departures"][1] = { **answer["stops"][0]["departures"][1], "departure": { "scheduled_utc": "2026-11-01T09:30:00Z" } }
		r = parse_departures(answer, MAIN, datetime(2026, 11, 1, 1, 0, tzinfo=LA), "en", LA)
		self.assertEqual([(d.when.strftime("%H:%M"), d.when.utcoffset()) for d in r.departures], [("01:30", timedelta(hours=-7)), ("01:30", timedelta(hours=-8))])

class TestWhatCanBeCaught(unittest.TestCase):
	def test_departures_already_gone_counting_the_walk_are_dropped_as_time_passes(self):
		r = board()
		self.assertEqual([d.when.strftime("%H:%M") for d in r.catchable(NOW)], ["12:07", "12:12", "12:20", "12:35"], "12:02 is gone with a five-minute walk")
		self.assertEqual([d.when.strftime("%H:%M") for d in r.catchable(NOW + timedelta(minutes=10))], ["12:20", "12:35"])
		self.assertEqual(r.catchable(NOW + timedelta(hours=1)), [])

	def test_a_cancelled_departure_stays_to_be_struck_out(self):
		self.assertIn(CANCELLED, [d.status for d in board().catchable(NOW)])

class TestTheStopsNearby(unittest.TestCase):
	def test_nearest_first_told_apart_and_asked_for_again_by_their_key(self):
		choices = nearby_choices(json.loads(fixture_text("transitland-stops-near.json")), 47.6105, -122.3305)
		self.assertEqual([c["value"] for c in choices], ["s-c23nb-mainst~3rd", "s-c23nb-mainst~3rd~sb", "f-c23-metro:77", "s-c23nc-central"])
		self.assertEqual(choices[0]["name"], "Main St & 3rd Ave, Northbound (0 m)")
		self.assertRegex(choices[1]["name"], r"^Main St & 3rd Ave, Southbound \(\d+ m\)$")
		self.assertNotIn("No Position", " ".join(c["name"] for c in choices))

	def test_a_distance_reads_as_a_walk_and_without_a_point_there_is_none(self):
		self.assertEqual([distance_text(m) for m in (0, 999.4, 1000, 5240, 12600)], ["0 m", "999 m", "1.0 km", "5.2 km", "13 km"])
		choices = nearby_choices(json.loads(fixture_text("transitland-stops-near.json")), None, None)
		# no point: no distance, in the order of the names, and a stop with no position is still one to choose
		self.assertEqual([c["name"] for c in choices][:2], ["Central Station", "Main St & 3rd Ave, Northbound"])
		self.assertIn("No Position", " ".join(c["name"] for c in choices))

	def test_a_key_is_told_from_a_name(self):
		self.assertEqual([looks_like_key(t) for t in ("s-c23nb-mainst~3rd", "f-c23-metro:77", "Main St", "Central", "s-c23 x")], [True, True, False, False, False])

	def test_a_stop_key_cannot_reach_another_path(self):
		self.assertEqual(stop_path("s-c23nb-mainst~3rd"), "/stops/s-c23nb-mainst~3rd")
		self.assertEqual(stop_path("f-c23-metro:77"), "/stops/f-c23-metro:77")
		self.assertEqual(stop_path("../operators?x=1"), "/stops/..%2Foperators%3Fx%3D1")

def storage(test: unittest.TestCase, **settings: Any) -> ConfigurationManager:
	cm = temp_configuration_manager(test)
	save_datasource_settings(cm, DATASOURCE_ID, { "apiKey": "tl-good", "stops": [MAIN, { "name": "Ferry", "stopKey": "s-c23p0-ferry" }], "departuresCacheMinutes": 15,
		"lookupCacheHours": 24, "staleDays": 30, "radius": 800, "monthlyQuota": None, "routineShare": 80, **settings })
	return cm

def context(cm: ConfigurationManager, now: datetime = NOW, **system: Any) -> DataSourceExecutionContext:
	provider = TransitlandApi(DATASOURCE_ID, "Transitland")
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("transit"))
	root.add_service(DataSourceManager, DataSourceManager({ DATASOURCE_ID: provider }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings("landscape", locale="en-US", **system)))
	return DataSourceExecutionContext(root, (800, 480), now)

class ProviderCase(unittest.TestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)
		METER.reset()
		self.addCleanup(METER.reset)
		keeping._last_prune.clear()

	def ask(self, cm: ConfigurationManager, stop: str = "Home", now: datetime = NOW) -> TransitReport:
		dsec = context(cm, now)
		provider, own = dsec.provide(TransitApi)
		return asyncio.run(provider.open_async(own, { "stop": stop }))

	def departures_asked(self) -> int:
		return sum(1 for r in self.fake.requests if r.url.path.endswith("/departures"))

class TestTheProvider(ProviderCase):
	def test_it_is_the_transit_contracts_provider_and_asks_with_the_key_in_the_header_only(self):
		self.assertIs(CONTRACTS["data-transit"], TransitApi)
		r = self.ask(storage(self))
		self.assertEqual(len(r.departures), 5)
		[request] = self.fake.requests
		self.assertEqual(request.headers["apikey"], "tl-good")
		self.assertNotIn("tl-good", str(request.url))
		self.assertEqual((request.url.params["include_alerts"], request.url.params["next"]), ("true", "5400"))

	def test_an_answer_is_kept_for_every_task_and_shown_as_of_when_it_was_asked(self):
		cm = storage(self)
		first = self.ask(cm)
		later = self.ask(cm, now=NOW + timedelta(minutes=10))
		self.assertEqual(self.departures_asked(), 1)
		self.assertEqual(later.fetched_at, first.fetched_at)
		self.assertEqual(later.fetched_at, NOW)
		self.ask(cm, now=NOW + timedelta(minutes=16))
		self.assertEqual(self.departures_asked(), 2)

	def test_the_kept_time_has_a_floor_however_the_file_says(self):
		cm = storage(self, departuresCacheMinutes=0)
		self.ask(cm)
		self.ask(cm, now=NOW + timedelta(minutes=14))
		self.assertEqual(self.departures_asked(), 1)

	def test_a_refusal_serves_the_kept_answer_and_with_none_kept_it_is_the_failure(self):
		cm = storage(self)
		self.ask(cm)
		save_datasource_settings(cm, DATASOURCE_ID, { **cm.datasource_manager(DATASOURCE_ID).open().get()[1], "apiKey": "tl-busy" })
		kept = self.ask(cm, now=NOW + timedelta(hours=2))
		self.assertEqual(kept.fetched_at, NOW, "the old answer, as of when it was asked")
		with self.assertRaises(RuntimeError) as caught:
			self.ask(cm, "Ferry", now=NOW + timedelta(hours=2))
		self.assertIn("too many requests", str(caught.exception))

	def test_a_refused_key_an_unknown_stop_and_a_missing_key_say_what_to_fix(self):
		with self.assertRaises(PermanentError) as caught:
			self.ask(storage(self, apiKey="tl-wrong"))
		self.assertIn("refused the API key", str(caught.exception))
		self.assertNotIn("tl-wrong", str(caught.exception))
		with self.assertRaises(PermanentError) as caught:
			self.ask(storage(self), "Work")
		self.assertIn("'Work' is not one of My Stops", str(caught.exception))
		with self.assertRaises(PermanentError) as caught:
			self.ask(storage(self, stops=[{ "name": "Gone", "stopKey": "s-nowhere" }]), "Gone")
		self.assertIn("does not know this stop", str(caught.exception))
		with self.assertRaises(PermanentError) as caught:
			self.ask(storage(self, apiKey=None))
		self.assertIn("API key is not set", str(caught.exception))

	def test_it_is_set_up_once_its_key_is(self):
		self.assertTrue(TransitlandApi(DATASOURCE_ID, "Transitland").configured(context(storage(self)).context_for(TransitlandApi(DATASOURCE_ID, "Transitland"))))
		dsec = context(storage(self, apiKey=" "))
		provider = TransitlandApi(DATASOURCE_ID, "Transitland")
		self.assertFalse(provider.configured(dsec.context_for(provider)))

	def test_past_the_routine_share_the_boards_show_what_was_kept(self):
		cm = storage(self)
		self.ask(cm)
		with patch.object(METER, "share", return_value=0.85):
			kept = self.ask(cm, now=NOW + timedelta(hours=1))
			self.assertEqual((self.departures_asked(), kept.fetched_at), (1, NOW))
			with self.assertRaises(QuotaUsedUp) as caught:
				self.ask(cm, "Ferry")
			self.assertIn("80% of the monthly quota", str(caught.exception))
		with patch.object(METER, "share", return_value=0.5):
			self.ask(cm, "Ferry")
		self.assertEqual(self.departures_asked(), 2)

class TestTheBudget(ProviderCase):
	"""The cache floor bounds the calls, however often the tasks fire (#429's "Done when")."""
	def test_a_month_of_a_weekday_window_with_a_task_every_five_minutes_stays_well_within_the_free_plan(self):
		cm = storage(self)
		day = datetime(2026, 11, 2, 7, 0, tzinfo=LA)
		weekdays = [day + timedelta(days=n) for n in range(30) if (day + timedelta(days=n)).weekday() < 5]
		for moment in weekdays:
			for minute in range(0, 120, 5):
				self.ask(cm, now=moment + timedelta(minutes=minute))
		# two hours a weekday, a call per 15 minutes: 8 a day
		self.assertEqual(self.departures_asked(), len(weekdays) * 8)
		self.assertLess(self.departures_asked(), 0.8 * 5000)

	def test_shown_all_day_every_two_minutes_a_stop_is_one_call_a_quarter_hour(self):
		cm = storage(self)
		for minute in range(0, 24 * 60, 2):
			self.ask(cm, now=NOW + timedelta(minutes=minute))
		# a task every two minutes finds the answer past its 15 minutes at the 16th: a call every 16 minutes
		self.assertEqual(self.departures_asked(), 24 * 60 // 16)
		self.assertLess(self.departures_asked() * 31, 5000, "a stop shown around the clock all month fits the free plan")

class TestTheRoutes(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.fake = FakeInternet()
		use_transport(self, self.fake)
		METER.reset()
		self.addCleanup(METER.reset)
		keeping._last_prune.clear()

	def settings(self, **values: Any) -> None:
		cob = self.cm.datasource_manager(DATASOURCE_ID).open()
		rev, doc = cob.get()
		self.assertTrue(cob.save(rev, { **(doc or {}), "apiKey": "tl-good", **values })[0])

	def location(self, where: dict|None) -> None:
		cob = self.cm.settings_manager().open("system")
		rev, doc = cob.get()
		self.assertTrue(cob.save(rev, { **(doc or {}), "location": where })[0])

	def test_the_key_test_asks_with_the_key_typed_or_the_saved_one(self):
		self.assertEqual(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test", json={ "value": "tl-good" }).json(), { "ok": True, "message": "Transitland accepts this key." })
		answer = self.client.post(f"/api/datasource/{DATASOURCE_ID}/test", json={ "value": "tl-nope" }).json()
		self.assertEqual(answer, { "ok": False, "message": "Transitland refused this key." })
		self.assertEqual(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test", json={ "value": "" }).json()["message"], "Enter an API key first.")
		self.settings()
		self.assertTrue(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test", json={ "value": None }).json()["ok"])

	def test_a_stops_test_says_its_name(self):
		self.assertEqual(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test-stop", json={ "value": "s-c23nb-mainst~3rd" }).json()["message"], "Save the Transitland API key first.")
		self.settings()
		self.assertEqual(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test-stop", json={ "value": "s-c23nb-mainst~3rd" }).json(),
			{ "ok": True, "message": "Transitland knows this stop: Main St & 3rd Ave." })
		self.assertEqual(self.client.post(f"/api/datasource/{DATASOURCE_ID}/test-stop", json={ "value": "s-nowhere" }).json(), { "ok": False, "message": "Transitland does not know this stop." })

	def test_the_stop_lookup_lists_the_stops_near_the_device_and_keeps_them(self):
		self.location(None)
		answer = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops")
		self.assertEqual(answer.status_code, 409)
		self.assertIn("Set the device's location first", answer.text)
		self.location(SEATTLE)
		self.assertIn("API key", self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops").text)
		self.settings()
		first = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops")
		self.assertEqual(first.status_code, 200)
		self.assertEqual(first.json()[0]["value"], "s-c23nb-mainst~3rd")
		self.assertEqual(self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops").json(), first.json())
		self.assertEqual(sum(1 for r in self.fake.requests if r.url.path.endswith("/stops")), 1, "opening the form again spends no call")
		radius = next(r for r in self.fake.requests if r.url.path.endswith("/stops")).url.params["radius"]
		self.assertEqual(radius, "800")

	def stops_asked(self) -> list[Any]:
		return [r.url.params for r in self.fake.requests if r.url.path.endswith("/stops")]

	def test_the_stop_finder_searches_by_name_within_ten_kilometres_and_keeps_the_answer(self):
		self.location(SEATTLE)
		self.settings()
		found = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "harbor" })
		self.assertEqual(found.status_code, 200)
		[harbor] = found.json()
		self.assertEqual(harbor["value"], "s-c23p3-harborferry")
		self.assertRegex(harbor["name"], r"^Harbor Ferry Terminal, Pier 2 \(\d\.\d km\)$")
		[asked] = self.stops_asked()
		self.assertEqual((asked["search"], asked["radius"]), ("harbor", "10000"))
		# the same search again, in another case, spends no call
		self.assertEqual(self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": " Harbor " }).json(), [harbor])
		self.assertEqual(len(self.stops_asked()), 1)
		# a name that is several stops: each, nearest first
		self.assertEqual([c["value"] for c in self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "central" }).json()],
			["s-c23nc-central", "s-c23pd-centralave~5th"])
		# an empty search is the stops near the device
		self.assertEqual(self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "" }).json()[0]["value"], "s-c23nb-mainst~3rd")

	def test_a_key_asked_for_is_that_stop_named_so_a_stored_choice_shows_its_name(self):
		self.location(SEATTLE)
		self.settings()
		answer = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "s-c23p3-harborferry" }).json()
		self.assertEqual([c["value"] for c in answer], ["s-c23p3-harborferry"])
		self.assertEqual(self.stops_asked()[0]["stop_key"], "s-c23p3-harborferry")
		self.assertEqual(self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "f-c23-metro:77" }).json()[0]["value"], "f-c23-metro:77")
		self.assertEqual(self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "s-nowhere" }).json(), [])

	def test_with_no_location_a_search_still_finds_stops_with_no_distance(self):
		self.location(None)
		self.settings()
		answer = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops", params={ "q": "harbor" })
		self.assertEqual(answer.json(), [{ "name": "Harbor Ferry Terminal, Pier 2", "value": "s-c23p3-harborferry" }])
		self.assertNotIn("radius", self.stops_asked()[0])
		self.assertIn("Or search for a stop by its name", self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops").text)

	def test_a_refusal_of_the_lookup_is_our_words(self):
		self.location(SEATTLE)
		self.settings(apiKey="tl-wrong")
		answer = self.client.get(f"/api/datasource/{DATASOURCE_ID}/lookups/stops")
		self.assertEqual(answer.status_code, 502)
		self.assertIn("refused the API key", answer.text)
		self.assertNotIn("tl-wrong", answer.text)

if __name__ == "__main__":
	unittest.main()
