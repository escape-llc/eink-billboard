"""
Alert Takeover (#429 PR 5): a Priority Update that takes the panel for a new alert in force, once per activation, and answers None otherwise. The page is
Service Alerts' own (`test_transit_alerts` draws it in Chromium); here it is faked.
"""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from ..datasources.contracts.transit import Alert
from ..datasources.transit_alerts import transit_alerts as alerts_module
from ..datasources.transit_alerts.transit_alerts import Alerts, Seen, in_force
from ..datasources.transit_takeover.transit_takeover import TransitTakeoverAsync, activation, wanted
from .fake_internet import FakeInternet
from .test_datasource_fixes import FakeRenderSession
from .test_transit_alerts import context
from .test_transitland import NOW, board, storage
from .utils import use_transport

def alert(key: str, start: datetime|None, end: datetime|None = None, effect: str = "detour") -> Alert:
	return Alert(key, f"Alert {key}", "", "severe", effect, "construction", ((start, end),))

class TestAnActivation(unittest.TestCase):
	def test_it_is_the_alert_and_the_start_of_its_period_in_force(self):
		periods = ((NOW - timedelta(hours=1), NOW + timedelta(hours=1)), (NOW + timedelta(hours=5), None))
		a = Alert("A", "A", "", "severe", "detour", "", periods)
		self.assertEqual(activation(a, NOW), f"A@{(NOW - timedelta(hours=1)).isoformat()}")
		# the alert back in a later period is another activation
		self.assertEqual(activation(a, NOW + timedelta(hours=6)), f"A@{(NOW + timedelta(hours=5)).isoformat()}")
		self.assertEqual(activation(alert("B", None), NOW), "B@open")
		self.assertEqual(activation(Alert("C", "C", "", "severe", "detour", ""), NOW), "C@open")

class TestWhatIsWanted(unittest.TestCase):
	def test_the_effects_chosen_and_the_severity_both_apply(self):
		found = in_force([("Home", board())], NOW, "warning")
		self.assertEqual([s.alert.effect for s in found.found], ["detour", "accessibility_issue"])
		self.assertEqual([s.alert.effect for s in wanted(found, ["accessibility_issue"]).found], ["accessibility_issue"])
		self.assertEqual(wanted(found, []).found, found.found)
		self.assertEqual([s.alert.header for s in in_force([("Home", board())], NOW, "severe").found], ["Route 45X detoured"])

class TestTheTakeover(unittest.TestCase):
	def setUp(self):
		use_transport(self, FakeInternet())
		self.cm = storage(self)
		self.ds = TransitTakeoverAsync("transit-takeover", "Alert Takeover")

	def run_task(self, state, now: datetime = NOW, clock_state: str = "unknown", params: dict|None = None):
		FakeRenderSession.last = None
		with patch.object(alerts_module, "RenderSession", FakeRenderSession), patch("python.datasources.transit_takeover.transit_takeover.ClockSync.state", return_value=clock_state):
			return asyncio.run(self.ds.render_async(context(self.cm, now=now), params or {}, state))

	def test_a_new_severe_alert_takes_the_panel_once(self):
		state = asyncio.run(self.ds.open_async(context(self.cm), {}))
		self.assertIsInstance(state, list)
		result = self.run_task(state)
		assert result is not None and FakeRenderSession.last is not None
		self.assertEqual(result.title, "Service Alert")
		self.assertEqual([a["header"] for a in FakeRenderSession.last.params["alerts"]], ["Route 45X detoured"])
		# the task runs again while it is in force: nothing more
		self.assertIsNone(self.run_task(state, NOW + timedelta(minutes=15)))
		self.assertIsNone(FakeRenderSession.last)

	def test_only_the_new_ones_are_drawn_and_a_new_period_is_shown_again(self):
		old, new = Seen(alert("A", NOW - timedelta(hours=1), NOW + timedelta(hours=2)), ("Home",)), Seen(alert("B", NOW), ("Home",))
		self.assertIsNotNone(self.run_task(Alerts([old], NOW, "credit", ("Home",))))
		self.assertIsNotNone(self.run_task(Alerts([old, new], NOW, "credit", ("Home",)), NOW + timedelta(minutes=15)))
		assert FakeRenderSession.last is not None
		self.assertEqual([a["header"] for a in FakeRenderSession.last.params["alerts"]], ["Alert B"])
		again = Seen(alert("A", NOW + timedelta(hours=4)), ("Home",))
		self.assertIsNotNone(self.run_task(Alerts([again], NOW, "credit", ("Home",)), NOW + timedelta(hours=5)))

	def test_one_not_seen_for_a_day_is_forgotten(self):
		seen = Alerts([Seen(alert("A", None), ("Home",))], NOW, "credit", ("Home",))
		self.assertIsNotNone(self.run_task(seen))
		self.assertIsNone(self.run_task(Alerts([], NOW, "credit", ("Home",)), NOW + timedelta(hours=1)))
		self.assertEqual(len(self.ds.shown), 1)
		self.assertIsNone(self.run_task(Alerts([], NOW, "credit", ("Home",)), NOW + timedelta(days=1, hours=1)))
		self.assertEqual(self.ds.shown, {})

	def test_nothing_wanted_or_the_clock_not_set_is_no_takeover(self):
		self.assertIsNone(self.run_task([Alerts(stops=("Home",))]))
		self.assertIsNone(self.run_task(None))
		state = asyncio.run(self.ds.open_async(context(self.cm), {}))
		self.assertIsNone(self.run_task(state, clock_state="unsynced"))
		# not shown while the clock was unsure, so it is still new
		self.assertIsNotNone(self.run_task(state))

	def test_the_effects_chosen_are_asked_for(self):
		[state] = asyncio.run(self.ds.open_async(context(self.cm), { "severity": "warning", "effects": ["accessibility_issue"] }))
		self.assertEqual([s.alert.header for s in state.found], ["Elevator out of service"])
		self.assertEqual(asyncio.run(self.ds.open_async(context(self.cm), { "stops": ["Ferry"], "effects": ["no_service"] }))[0].found, [])

if __name__ == "__main__":
	unittest.main()
