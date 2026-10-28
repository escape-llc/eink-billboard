"""
The Departure Board (#429): what it draws from a `TransitReport` (clock times, live or timetable, the delay, what can still be caught, a cancelled trip struck out,
the "as of" rounded so an unchanged board draws the same, the alert's headline, the route's colour in the panel's inks, the clock guard), and the page as Chromium
draws it, at the sizes of the panels, with fixed clocks. The provider is the fake internet's Transitland (test_transitland).
"""
import asyncio
import shutil
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PIL import Image

from ..datasources.contracts.transit import TransitReport
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.transit import transit as transit_module
from ..datasources.transit.transit import WAITING_FOR_CLOCK, TransitAsync, as_of, chip, page_params
from ..datasources.transitland_api.transitland_api import CREDIT, DATASOURCE_ID, TransitlandApi
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.inks import DRIVE, nearest_ink
from ..model.service_container import ServiceContainer
from ..utils.image_utils import chrome_command
from .fake_internet import FakeInternet
from .test_datasource_fixes import STATIC, FakeRenderSession
from .test_transitland import LA, MAIN, NOW, board, storage
from .test_weather import FakeSettings
from .utils import test_output_path_for, use_transport

def params(report: TransitReport, now: datetime = NOW, twelve_hour: bool = False, clock_state: str = "unknown", **task: Any) -> dict:
	return page_params(report, now, task, twelve_hour, None, clock_state)

class TestWhatIsDrawn(unittest.TestCase):
	def test_clock_times_live_or_timetable_with_the_delay_and_what_can_still_be_caught(self):
		p = params(board())
		self.assertEqual([(r["time"], r["live"], r["delay"], r["route"], r["headsign"], r["cancelled"]) for r in p["rows"]], [
			("12:07", True, "+2", "23", "Downtown", False),
			("12:12", False, "", "45X", "Airport", True),
			("12:20", False, "", "23", "Downtown", False),
			("12:35", False, "", "45X", "Airport", False),
		])
		self.assertEqual((p["heading"], p["credit"], p["as_of"], p["any_live"], p["any_timetable"]), ("Main St & 3rd Ave", CREDIT, "12:00", True, True))

	def test_a_board_drawn_later_leaves_out_what_is_gone_and_still_says_when_it_was_asked(self):
		p = params(board(), now=NOW + timedelta(minutes=12))
		self.assertEqual([r["time"] for r in p["rows"]], ["12:20", "12:35"])
		self.assertEqual(p["as_of"], "12:00")

	def test_the_as_of_is_rounded_down_so_an_unchanged_board_draws_the_same(self):
		self.assertEqual(as_of(datetime(2026, 10, 7, 12, 34, 59, tzinfo=LA)), datetime(2026, 10, 7, 12, 30, tzinfo=LA))
		self.assertEqual(params(board(fetched_at=NOW + timedelta(minutes=3)))["as_of"], params(board(fetched_at=NOW + timedelta(minutes=4)))["as_of"])

	def test_twelve_hours_a_row_count_and_a_title(self):
		p = params(board(), twelve_hour=True, rows=2, title="To Work")
		self.assertEqual([r["time"] for r in p["rows"]], ["12:07", "12:12"])
		self.assertEqual(p["heading"], "To Work")
		self.assertEqual(params(board(), now=NOW + timedelta(hours=1), twelve_hour=True)["as_of"], "12:00")

	def test_the_most_severe_alert_is_the_headline_and_the_rest_are_counted(self):
		p = params(board())
		self.assertEqual((p["alerts"], p["more_alerts"]), (["Route 45X detoured"], 1))

	def test_with_nothing_to_catch_it_says_so_in_words(self):
		self.assertEqual(params(board(), now=NOW + timedelta(hours=2))["message"], "No more departures you can still catch soon.")
		# a stop that publishes intervals: its times are the timetable's pattern, so the board says what they are
		ferry = params(board({ "name": "Ferry", "stopKey": "s-c23p0-ferry" }, "transitland-departures-intervals.json"))
		self.assertEqual((len(ferry["rows"]), ferry["message"]), (2, ""))
		self.assertIn("intervals, not times", ferry["note"])
		self.assertEqual(params(board())["note"], "")

	def test_a_clock_not_set_is_a_page_that_waits_for_it(self):
		p = params(board(), clock_state="unsynced")
		self.assertEqual((p["rows"], p["message"], p["as_of"]), ([], WAITING_FOR_CLOCK, ""))

	def test_a_routes_colour_is_drawn_in_the_nearest_ink_never_the_pages(self):
		self.assertEqual(nearest_ink((0, 102, 204), "spectra6"), "blue")
		self.assertEqual(nearest_ink((204, 51, 0), "spectra6"), "red")
		self.assertEqual(chip("#0066cc", "spectra6", "white"), { "background": "#0000ff", "color": "#ffffff" })
		# a white route on a white page is the board's strong chip: another ink would be another colour, not the route's
		self.assertIsNone(chip("#ffffff", "spectra6", "white"))
		self.assertEqual(chip("#ffffff", "spectra6", "black"), { "background": "#ffffff", "color": "#000000" })
		self.assertIn(chip("#cc3300", "bw", "white")["background"], ("#000000", "#ffffff"))  # type: ignore[index]
		self.assertIsNone(chip(None, "spectra6", "white"))
		for p in (params(board())["rows"]):
			if p["chip"] is not None:
				self.assertIn(tuple(int(p["chip"]["background"][i:i + 2], 16) for i in (1, 3, 5)), DRIVE.values())

def context(cm: ConfigurationManager, orientation: str = "landscape", dimensions: tuple[int, int] = (800, 480), now: datetime = NOW) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
	root.add_service(DatasourceConfigurationManager, cm.datasource_manager("transit"))
	root.add_service(DataSourceManager, DataSourceManager({ DATASOURCE_ID: TransitlandApi(DATASOURCE_ID, "Transitland") }))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, locale="en-US")))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, dimensions, now)

class TestTheSource(unittest.TestCase):
	def setUp(self):
		use_transport(self, FakeInternet())

	def test_it_asks_the_devices_transit_provider_for_the_tasks_stop_and_draws_one_page(self):
		cm = storage(self)
		ds = TransitAsync("transit", "Departure Board")
		[report] = asyncio.run(ds.open_async(context(cm), { "stop": "Home" }))
		self.assertEqual(report.stop.key, MAIN["stopKey"])
		with patch.object(transit_module, "RenderSession", FakeRenderSession):
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				result = asyncio.run(ds.render_async(context(cm, orientation), { "stop": "Home", "fontSize": "large" }, report))
				assert result is not None and FakeRenderSession.last is not None
				self.assertEqual((result.image.size, result.title), (size, "Main St & 3rd Ave"))
				self.assertEqual(FakeRenderSession.last.params["font_scale"], 1.2)
		self.assertIsNone(asyncio.run(ds.render_async(context(cm), {}, None)))

	def test_a_clock_not_set_reaches_the_page(self):
		cm = storage(self)
		ds = TransitAsync("transit", "Departure Board")
		[report] = asyncio.run(ds.open_async(context(cm), { "stop": "Home" }))
		with patch.object(transit_module, "RenderSession", FakeRenderSession), patch.object(transit_module.ClockSync, "state", return_value="unsynced"):
			asyncio.run(ds.render_async(context(cm), { "stop": "Home" }, report))
		assert FakeRenderSession.last is not None
		self.assertEqual(FakeRenderSession.last.params["message"], WAITING_FOR_CLOCK)

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.TestCase):
	"""The board as Chromium draws it. The images are in .test-output/transit for a look."""
	def setUp(self):
		use_transport(self, FakeInternet())

	def test_the_board_is_drawn_at_each_panels_size_in_its_inks(self):
		folder = Path(test_output_path_for("transit"))
		cm = storage(self)
		ds = TransitAsync("transit", "Departure Board")
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800)), ("landscape", (1600, 1200))):
			with self.subTest(orientation=orientation, size=size):
				dimensions = size if orientation == "landscape" else (size[1], size[0])
				dsec = context(cm, orientation, dimensions)
				[report] = asyncio.run(ds.open_async(dsec, { "stop": "Home" }))
				result = asyncio.run(ds.render_async(dsec, { "stop": "Home" }, report))
				assert result is not None
				self.assertEqual(result.image.size, size)
				result.image.save(folder.joinpath(f"{orientation}-{size[0]}x{size[1]}.png"))
				colours = result.image.convert("RGB").getcolors(maxcolors=4096) or []
				self.assertGreater(len(colours), 1, "the page is not blank")
				if sys.platform == "linux":
					# fontconfig draws the text without antialiasing on Linux only (docs/panel-and-rendering.md): there, every pixel is one of the inks
					inks = set(DRIVE.values())
					self.assertEqual({ c for _, c in colours } - inks, set(), "a page is made of inks only")
				self.assertIsInstance(result.image, Image.Image)

if __name__ == "__main__":
	unittest.main()
