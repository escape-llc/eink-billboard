"""
Next Departure (#429 PR 4): a line per route and destination with its next times that can still be caught, in the task's style (clock or leave-by, never a countdown), with
timetable and late times marked, and the overlay taken off when nothing is left or the clock is not set. Against the fake internet's Transitland (test_transitland).
"""
import asyncio
import shutil
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image

from ..datasources.transit_overlay import transit_overlay as overlay_module
from ..datasources.transit_overlay.transit_overlay import TransitOverlayAsync, lines_of, overlay_lines
from ..model.inks import DRIVE
from ..utils.image_utils import chrome_command
from .fake_internet import FakeInternet
from .test_transit_alerts import context
from .test_transitland import NOW, board, storage
from .utils import test_output_path_for, use_transport

def texts(params: dict[str, Any] | None = None, now=NOW, twelve_hour: bool = False) -> list[str]:
	return ["".join(text for text, _ in runs) for runs in overlay_lines(board(), now, params or {}, twelve_hour)]

class TestTheLines(unittest.TestCase):
	def test_a_line_per_route_and_destination_with_its_next_two_that_run(self):
		# 12:02 is gone with the five-minute walk; the 12:12 45X is cancelled, so the 45X's next is 12:35
		self.assertEqual(texts(), ["23 Downtown  12:07+2 · ~12:20 · Transitland", "45X Airport  ~12:35"])
		self.assertEqual([(l.route, len(l.departures)) for l in lines_of(board(), NOW, 1)], [("23", 1), ("45X", 1)])

	def test_as_time_passes_what_is_gone_drops_out(self):
		self.assertEqual(texts(now=NOW + timedelta(minutes=10)), ["23 Downtown  ~12:20 · Transitland", "45X Airport  ~12:35"])
		self.assertEqual(texts(now=NOW + timedelta(minutes=31)), [])

	def test_there_is_no_countdown_a_stored_one_reads_as_clock_times(self):
		# not a real-time display: "in 7 min" is wrong a minute after the refresh, 12:07 stays right
		self.assertEqual(texts({ "timeStyle": "countdown" }), texts())

	def test_leave_by_takes_the_walk_off(self):
		self.assertEqual(texts({ "timeStyle": "leave-by" }), ["23 Downtown  leave 12:02+2 · ~12:15 · Transitland", "45X Airport  leave ~12:30"])

	def test_times_per_line_and_twelve_hours(self):
		self.assertEqual(texts({ "perLine": 1 }, twelve_hour=True), ["23 Downtown  12:07+2 · Transitland", "45X Airport  ~12:35"])

	def test_the_route_is_the_accent_and_the_name_is_on_the_first_line(self):
		[first, second] = overlay_lines(board(), NOW, {}, False)
		self.assertEqual((first[0], first[-1]), (("23 ", "text-secondary-1"), (" · Transitland", "text-secondary-2")))
		self.assertEqual(len(second), 3)

class TestTheOverlay(unittest.TestCase):
	def setUp(self):
		use_transport(self, FakeInternet())

	def run_overlay(self, clock_state: str = "unknown", now=NOW):
		cm = storage(self)
		ds = TransitOverlayAsync("transit-overlay", "Next Departure")
		[report] = asyncio.run(ds.open_async(context(cm, now=now), { "stop": "Home" }))
		drawn: dict[str, Any] = {}
		def fake_render(stm, theme, size, lines, *rest):
			drawn["lines"], drawn["size"] = lines, size
			return Image.new("RGBA", size)
		with patch.object(overlay_module, "render_overlay", fake_render), patch.object(overlay_module, "lines_that_fit", lambda *a, **k: 1), \
				patch.object(overlay_module.ClockSync, "state", return_value=clock_state):
			result = asyncio.run(ds.render_async(context(cm, dimensions=(300, 60), now=now), { "stop": "Home", "zone": "bottom-left" }, report))
		return result, drawn

	def test_in_its_zone_it_draws_the_lines_that_fit(self):
		result, drawn = self.run_overlay()
		assert result is not None
		self.assertEqual((drawn["size"], len(drawn["lines"])), ((300, 60), 1))
		self.assertEqual(result.title, "23 Downtown  12:07+2 · ~12:20 · Transitland")

	def test_nothing_left_to_catch_or_a_clock_not_set_takes_it_off(self):
		self.assertIsNone(self.run_overlay(now=NOW + timedelta(minutes=31))[0])
		self.assertIsNone(self.run_overlay("unsynced")[0])
		self.assertIsNone(asyncio.run(TransitOverlayAsync("transit-overlay", "Next Departure").render_async(context(storage(self)), {}, None)))

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealOverlay(unittest.TestCase):
	"""The overlay as Chromium draws it, marks and all. The image is in .test-output/transit-overlay for a look."""
	def setUp(self):
		use_transport(self, FakeInternet())

	def test_it_is_drawn_in_its_zone_clear_or_in_the_inks(self):
		cm = storage(self)
		ds = TransitOverlayAsync("transit-overlay", "Next Departure")
		[report] = asyncio.run(ds.open_async(context(cm), { "stop": "Home" }))
		result = asyncio.run(ds.render_async(context(cm, dimensions=(400, 120)), { "stop": "Home", "zone": "bottom-left", "timeStyle": "leave-by" }, report))
		assert result is not None
		self.assertEqual(result.image.size, (400, 120))
		result.image.save(Path(test_output_path_for("transit-overlay")).joinpath("bottom-left-400x120.png"))
		pixels = result.image.convert("RGBA").getcolors(maxcolors=65536) or []
		self.assertGreater(len([c for _, c in pixels if c[3] == 255]), 0, "something is drawn")
		if sys.platform == "linux":
			# an overlay is clear or solid, in the inks (docs/panel-and-rendering.md): the compositor pastes it, and a half-clear pixel would be blended and dithered
			self.assertEqual({ c[3] for _, c in pixels } - { 0, 255 }, set())
			self.assertEqual({ c[:3] for _, c in pixels if c[3] == 255 } - set(DRIVE.values()), set())

if __name__ == "__main__":
	unittest.main()
