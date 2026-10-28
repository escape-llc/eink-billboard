"""
Service Alerts (#429 PR 3): the alerts of the routes that serve a stop (a call of the provider's own, kept longer, only when asked), and the alerts in force as an
overlay (taken off when there are none) or as a page. Against the fake internet's Transitland (test_transitland), with fixed clocks.
"""
import asyncio
import shutil
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from ..datasources.contracts.transit import Alert, TransitApi
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.transit_alerts import transit_alerts as alerts_module
from ..datasources.transit_alerts.transit_alerts import Alerts, TransitAlertsAsync, in_force, overlay_lines, page_params, until
from ..datasources.transitland_api import transitland_api as provider_module
from ..datasources.transitland_api.transitland_api import CREDIT, DATASOURCE_ID, TransitlandApi
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.inks import DRIVE
from ..model.service_container import ServiceContainer
from ..utils.image_utils import chrome_command
from .fake_internet import FakeInternet
from .test_datasource_fixes import STATIC, FakeRenderSession
from .test_transitland import MAIN, NOW, ProviderCase, board, storage
from .test_weather import FakeSettings
from .utils import test_output_path_for, use_transport

def context(cm: ConfigurationManager, orientation: str = "landscape", dimensions: tuple[int, int] = (800, 480), now: datetime = NOW) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("transit-alerts"))
	root.add_service(DataSourceManager, DataSourceManager({ DATASOURCE_ID: TransitlandApi(DATASOURCE_ID, "Transitland") }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, locale="en-US")))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, dimensions, now)

class TestTheRoutesAlerts(ProviderCase):
	def ask_routes(self, cm: ConfigurationManager, stop: str = "Home", now: datetime = NOW):
		dsec = context(cm, now=now)
		provider, own = dsec.provide(TransitApi)
		return asyncio.run(provider.open_async(own, { "stop": stop, "routeAlerts": True }))

	def routes_asked(self) -> int:
		return sum(1 for r in self.fake.requests if r.url.path.endswith("/routes"))

	def test_asked_for_they_are_added_each_once_naming_the_routes_they_were_seen_on(self):
		r = self.ask_routes(storage(self))
		by_header = { a.header: a for a in r.alerts }
		self.assertEqual(set(by_header), { "Elevator out of service", "Route 45X detoured", "Route 23 runs every 20 minutes this week" })
		self.assertEqual(by_header["Route 23 runs every 20 minutes this week"].routes, ("23",))
		self.assertEqual(by_header["Route 45X detoured"].routes, ("45X",), "the detour came with the departures and with the route: one alert")
		self.assertEqual(by_header["Elevator out of service"].routes, ("23",), "the stop's own alert, also on a trip of route 23")
		[request] = [q for q in self.fake.requests if q.url.path.endswith("/routes")]
		self.assertEqual((request.url.params["serves_stop_onestop_id"], request.headers["apikey"]), ("s-c23nb-mainst~3rd", "tl-good"))

	def test_not_asked_for_they_cost_nothing(self):
		r = self.ask(storage(self))
		self.assertEqual(self.routes_asked(), 0)
		self.assertNotIn("Route 23 runs every 20 minutes this week", [a.header for a in r.alerts])

	def test_they_are_kept_longer_than_the_departures(self):
		cm = storage(self)
		self.ask_routes(cm)
		self.ask_routes(cm, now=NOW + timedelta(minutes=20))
		self.assertEqual((self.departures_asked(), self.routes_asked()), (2, 1))
		self.ask_routes(cm, now=NOW + timedelta(minutes=31))
		self.assertEqual(self.routes_asked(), 2)

	def test_the_stops_route_filter_applies_and_a_stop_without_a_onestop_id_is_not_asked(self):
		r = self.ask_routes(storage(self, stops=[{ **MAIN, "routes": "7" }]))
		self.assertEqual([a.header for a in r.alerts], ["Elevator out of service"])
		self.assertEqual(self.routes_asked(), 1)
		# a stop known only as `<feed>:<stop_id>`: Transitland finds a stop's routes by its Onestop ID, so they are not asked for
		pine = self.ask_routes(storage(self, stops=[{ "name": "Pine", "stopKey": "f-c23-metro:77" }]), "Pine")
		self.assertEqual((self.routes_asked(), len(pine.departures)), (1, 5))

	def test_when_they_cannot_be_had_the_stops_own_are_shown(self):
		real = provider_module.fetch
		async def no_routes(client, path, params, key):
			if path == "/routes":
				raise RuntimeError("Transitland answered 503.")
			return await real(client, path, params, key)
		with patch.object(provider_module, "fetch", no_routes):
			r = self.ask_routes(storage(self))
		self.assertEqual(len(r.departures), 5)
		self.assertIn("Elevator out of service", [a.header for a in r.alerts])

	def test_the_provider_names_my_stops_in_their_order(self):
		dsec = context(storage(self))
		provider, own = dsec.provide(TransitApi)
		self.assertEqual(provider.stop_names(own), ["Home", "Ferry"])

def alert(header: str, severity: str, key: str|None = None, routes: tuple[str, ...] = (), end: datetime|None = None) -> Alert:
	return Alert(key or header, header, f"About {header}.", severity, "detour", "construction", ((NOW - timedelta(hours=1), end),), None, routes)

class TestWhatIsInForce(unittest.TestCase):
	def test_each_alert_once_most_severe_first_naming_the_stops_it_was_seen_at(self):
		home, work = board(), board({ "name": "Work", "stopKey": "s-c23nb-mainst~3rd" })
		found = in_force([("Home", home), ("Work", work)], NOW, "any")
		self.assertEqual([(s.alert.header, s.stops) for s in found.found], [("Route 45X detoured", ("Home", "Work")), ("Elevator out of service", ("Home", "Work"))])
		self.assertEqual((found.credit, found.as_of, found.stops), (CREDIT, NOW, ("Home", "Work")))

	def test_the_severity_asked_for_is_the_least_shown(self):
		self.assertEqual([s.alert.header for s in in_force([("Home", board())], NOW, "severe").found], ["Route 45X detoured"])
		self.assertEqual(len(in_force([("Home", board())], NOW, "warning").found), 2)

	def test_an_alert_that_is_over_is_not_in_force(self):
		self.assertEqual([s.alert.header for s in in_force([("Home", board())], NOW + timedelta(hours=7), "any").found], ["Elevator out of service"])

	def test_until_says_when_the_period_in_force_ends(self):
		self.assertEqual(until(alert("A", "info", end=NOW + timedelta(hours=6)), NOW, False), "until 18:00")
		self.assertEqual(until(alert("A", "info", end=NOW + timedelta(hours=6)), NOW, True), "until 6:00 PM")
		self.assertEqual(until(alert("A", "info", end=NOW + timedelta(days=2)), NOW, False), "until Fri 12:00")
		self.assertEqual(until(alert("A", "info"), NOW, False), "")

class TestTheOverlay(unittest.TestCase):
	def test_a_line_per_alert_what_it_is_about_then_its_headline(self):
		found = in_force([("Home", board())], NOW, "any")
		# the first line carries the provider's name: its terms ask for the credit next to the data
		self.assertEqual(overlay_lines(found), [[("45X: ", "text-secondary-1"), ("Route 45X detoured", "text-primary"), (" · Transitland", "text-secondary-2")],
			[("23: ", "text-secondary-1"), ("Elevator out of service", "text-primary")]])

	def run_overlay(self, state: Alerts, clock_state: str = "unknown"):
		cm = storage(self)
		drawn: dict[str, Any] = {}
		def fake_render(stm, theme, size, lines, *rest):
			drawn["lines"], drawn["size"] = lines, size
			from PIL import Image
			return Image.new("RGBA", size)
		with patch.object(alerts_module, "render_overlay", fake_render), patch.object(alerts_module, "lines_that_fit", lambda *a, **k: 1), \
				patch.object(alerts_module.ClockSync, "state", return_value=clock_state):
			result = asyncio.run(TransitAlertsAsync("transit-alerts", "Service Alerts").render_async(context(cm, dimensions=(260, 60)), { "zone": "top-left" }, state))
		return result, drawn

	def test_in_a_zone_it_draws_what_fits_the_most_severe_first(self):
		result, drawn = self.run_overlay(in_force([("Home", board())], NOW, "any"))
		assert result is not None
		self.assertEqual((drawn["size"], drawn["lines"]), ((260, 60), [[("45X: ", "text-secondary-1"), ("Route 45X detoured", "text-primary"), (" · Transitland", "text-secondary-2")]]))
		self.assertEqual(result.title, "45X: Route 45X detoured · Transitland")

	def test_with_nothing_in_force_or_the_clock_not_set_the_overlay_comes_off(self):
		self.assertEqual(self.run_overlay(Alerts())[0], None)
		self.assertEqual(self.run_overlay(in_force([("Home", board())], NOW, "any"), "unsynced")[0], None)

class TestThePage(unittest.TestCase):
	def setUp(self):
		use_transport(self, FakeInternet())

	def test_each_alert_with_its_severity_what_it_is_about_until_when_and_its_words(self):
		p = page_params(in_force([("Home", board())], NOW, "any"), NOW, {}, False)
		self.assertEqual([(a["word"], a["where"], a["until"], a["header"]) for a in p["alerts"]], [
			("Severe", "45X", "until 18:00", "Route 45X detoured"), ("Warning", "23", "", "Elevator out of service")])
		self.assertEqual((p["heading"], p["credit"], p["as_of"], p["message"]), ("Service Alerts", CREDIT, "12:00", ""))

	def test_with_none_it_says_so_and_with_the_clock_not_set_it_waits(self):
		self.assertEqual(page_params(Alerts(stops=("Home",)), NOW, {}, False)["message"], "No service alerts for Home.")
		self.assertEqual(page_params(in_force([("Home", board())], NOW, "any"), NOW, {}, False, "unsynced")["message"], "Waiting for the clock to be set.")

	def test_a_track_of_every_stop_draws_one_page(self):
		cm = storage(self)
		ds = TransitAlertsAsync("transit-alerts", "Service Alerts")
		[state] = asyncio.run(ds.open_async(context(cm), {}))
		self.assertEqual(state.stops, ("Home", "Ferry"))
		with patch.object(alerts_module, "RenderSession", FakeRenderSession):
			result = asyncio.run(ds.render_async(context(cm), { "title": "My Alerts" }, state))
		assert result is not None and FakeRenderSession.last is not None
		self.assertEqual((result.title, len(FakeRenderSession.last.params["alerts"])), ("My Alerts", 2))
		self.assertIsNone(asyncio.run(ds.render_async(context(cm), {}, None)))

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.TestCase):
	"""The page as Chromium draws it. The images are in .test-output/transit-alerts for a look."""
	def setUp(self):
		use_transport(self, FakeInternet())

	def test_the_page_is_drawn_at_each_panels_size_in_its_inks(self):
		folder = Path(test_output_path_for("transit-alerts"))
		cm = storage(self)
		ds = TransitAlertsAsync("transit-alerts", "Service Alerts")
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800)), ("landscape", (1600, 1200))):
			with self.subTest(orientation=orientation, size=size):
				dimensions = size if orientation == "landscape" else (size[1], size[0])
				dsec = context(cm, orientation, dimensions)
				[state] = asyncio.run(ds.open_async(dsec, { "routeAlerts": True }))
				result = asyncio.run(ds.render_async(dsec, {}, state))
				assert result is not None
				self.assertEqual(result.image.size, size)
				result.image.save(folder.joinpath(f"{orientation}-{size[0]}x{size[1]}.png"))
				colours = result.image.convert("RGB").getcolors(maxcolors=4096) or []
				self.assertGreater(len(colours), 1, "the page is not blank")
				if sys.platform == "linux":
					self.assertEqual({ c for _, c in colours } - set(DRIVE.values()), set(), "a page is made of inks only")

if __name__ == "__main__":
	unittest.main()
