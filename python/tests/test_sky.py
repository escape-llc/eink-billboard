"""
The sun and the moon (#619): the times against a JPL ephemeris, the edge cases astral leaves to us, and the Sun and Moon page and overlay.

The reference times were computed with Skyfield 1.x and the JPL ephemeris `de421.bsp` (`almanac.sunrise_sunset`, `almanac.risings_and_settings`,
`almanac.moon_phases`, and the moon's apparent altitude and azimuth), on 2026-10-24; they are kept here so the test needs neither Skyfield nor the network.
astral agrees to within half a minute for the sun and about a degree for the moon's place; the tolerances say so.
"""
import shutil
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.sky import draw
from ..datasources.sky.sky import (PHASE_CYCLE, TWILIGHTS, Place, depression_of, device_place, lit_share, moon_at, moon_day, next_phase, phase_name,
	sky_of, sun_day)
from ..datasources.sun_moon import sun_moon as sun_moon_module
from ..datasources.sun_moon.sun_moon import Page, SunMoonAsync, change, chosen_views, clock, duration, page_params
from ..datasources.sun_moon_overlay import sun_moon_overlay as overlay_module
from ..datasources.sun_moon_overlay.sun_moon_overlay import SunMoonOverlayAsync, chosen_view, view_lines
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import chrome_command
from .test_datasource_fixes import STATIC, FakeRenderSession, _Cob
from .utils import storage_path, test_output_path_for

NEW_YORK = Place(40.7128, -74.0060)
LONDON = Place(51.5074, -0.1278)
SYDNEY = Place(-33.8688, 151.2093)
REYKJAVIK = Place(64.1466, -21.9426)
TROMSO = Place(69.6492, 18.9553)

# (place, zone, day, sunrise, sunset): Skyfield with de421, local time
SUN_TIMES = (
	(NEW_YORK, "America/New_York", date(2026, 6, 21), "05:25:01", "20:30:44"),
	(LONDON, "Europe/London", date(2026, 12, 21), "08:03:44", "15:53:23"),
	(SYDNEY, "Australia/Sydney", date(2026, 10, 24), "06:03:37", "19:15:45"),
)
# the new and full moons of October and November 2026 (UTC)
MOONS = ((date(2026, 10, 10), "New Moon"), (date(2026, 10, 26), "Full Moon"), (date(2026, 11, 9), "New Moon"), (date(2026, 11, 24), "Full Moon"))

def at(day: date, hms: str, zone: str) -> datetime:
	h, m, s = (int(x) for x in hms.split(":"))
	return datetime(day.year, day.month, day.day, h, m, s, tzinfo=ZoneInfo(zone))

class TestSun(unittest.TestCase):
	def test_sunrise_and_sunset_agree_with_the_ephemeris_to_the_minute(self):
		for place, zone, day, rise, set_ in SUN_TIMES:
			with self.subTest(place=place, day=day):
				sun = sun_day(place, day, ZoneInfo(zone))
				assert sun.sunrise is not None and sun.sunset is not None
				self.assertLess(abs((sun.sunrise - at(day, rise, zone)).total_seconds()), 60)
				self.assertLess(abs((sun.sunset - at(day, set_, zone)).total_seconds()), 60)
				self.assertIsNone(sun.polar)

	def test_the_day_is_ordered_and_its_length_is_sunset_less_sunrise(self):
		sun = sun_day(NEW_YORK, date(2026, 6, 21), ZoneInfo("America/New_York"))
		assert sun.dawn and sun.sunrise and sun.sunset and sun.dusk and sun.length
		self.assertLess(sun.dawn, sun.sunrise)
		self.assertLess(sun.sunrise, sun.noon)
		self.assertLess(sun.noon, sun.sunset)
		self.assertLess(sun.sunset, sun.dusk)
		self.assertEqual(sun.length, sun.sunset - sun.sunrise)
		self.assertEqual(duration(sun.length), "15h 05m")

	def test_a_polar_day_has_no_sunrise_or_sunset_and_is_24_hours_long(self):
		# Tromsø's midnight sun: astral raises for every time, and only the wording says why
		sun = sun_day(TROMSO, date(2026, 6, 21), ZoneInfo("Europe/Oslo"))
		self.assertEqual(sun.polar, "day")
		self.assertIsNone(sun.sunrise)
		self.assertIsNone(sun.sunset)
		self.assertEqual(sun.length, timedelta(hours=24))
		self.assertGreater(sun.noon_elevation, 0)

	def test_a_polar_night_has_no_sunrise_or_sunset_and_no_daylight(self):
		sun = sun_day(TROMSO, date(2026, 12, 21), ZoneInfo("Europe/Oslo"))
		self.assertEqual(sun.polar, "night")
		self.assertEqual(sun.length, timedelta(0))
		# civil twilight still happens around noon
		self.assertIsNotNone(sun.dawn)
		self.assertIsNotNone(sun.dusk)

	def test_a_sunset_after_midnight_is_the_days_own(self):
		# Reykjavík at midsummer: the ephemeris has the sun set at 00:03 and rise at 02:55; astral's sunset(21 June) is the 00:02 that ends the 20th
		zone = ZoneInfo("Atlantic/Reykjavik")
		sun = sun_day(REYKJAVIK, date(2026, 6, 21), zone)
		assert sun.sunrise is not None and sun.sunset is not None and sun.length is not None
		self.assertEqual(sun.sunset.date(), date(2026, 6, 22))
		self.assertLess(abs((sun.sunrise - at(date(2026, 6, 21), "02:55:12", "Atlantic/Reykjavik")).total_seconds()), 120)
		self.assertGreater(sun.length, timedelta(hours=21))
		self.assertEqual(clock(sun.sunset, False, sun.noon), "00:02 (+1)")
		# a white night: the sun never goes 6° down, so there is no civil dawn or dusk
		self.assertIsNone(sun.dawn)
		self.assertIsNone(sun.dusk)

	def test_the_twilight_setting_moves_dawn_and_dusk(self):
		zone = ZoneInfo("Europe/London")
		civil = sun_day(LONDON, date(2026, 12, 21), zone, depression_of("civil"))
		dark = sun_day(LONDON, date(2026, 12, 21), zone, depression_of("astronomical"))
		assert civil.dawn and dark.dawn and civil.dusk and dark.dusk
		self.assertLess(dark.dawn, civil.dawn)
		self.assertGreater(dark.dusk, civil.dusk)
		self.assertEqual(depression_of(None), TWILIGHTS["civil"])
		with self.assertRaises(PermanentError):
			depression_of("dim")

class TestMoon(unittest.TestCase):
	def test_the_phase_is_named_at_the_new_and_full_moons(self):
		for day, name in MOONS:
			with self.subTest(day=day):
				self.assertEqual(phase_name(moon_day(NEW_YORK, day, ZoneInfo("America/New_York")).phase), name)

	def test_the_next_full_and_new_moons_are_the_ephemeris_days(self):
		self.assertEqual(next_phase(date(2026, 10, 24), 14.0), date(2026, 10, 26))
		self.assertEqual(next_phase(date(2026, 10, 24), 0.0), date(2026, 11, 9))
		self.assertEqual(next_phase(date(2026, 10, 27), 14.0), date(2026, 11, 24))
		self.assertEqual(next_phase(date(2026, 10, 1), 0.0), date(2026, 10, 10))
		# on the day itself
		self.assertEqual(next_phase(date(2026, 10, 26), 14.0), date(2026, 10, 26))

	def test_the_names_go_round_in_order(self):
		names = [phase_name(p) for p in (0.2, 3, 7, 10, 14, 17, 21, 24, 27.5)]
		self.assertEqual(names, ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent", "New Moon"])

	def test_the_lit_share_is_none_at_new_and_all_at_full(self):
		self.assertAlmostEqual(lit_share(0), 0)
		self.assertAlmostEqual(lit_share(PHASE_CYCLE / 2), 1)
		self.assertAlmostEqual(lit_share(PHASE_CYCLE / 4), 0.5)

	def test_moonrise_and_moonset_agree_with_the_ephemeris(self):
		# New York, 24 October 2026: the moon sets at 05:26 and rises at 17:00
		m = moon_day(NEW_YORK, date(2026, 10, 24), ZoneInfo("America/New_York"))
		assert m.moonrise is not None and m.moonset is not None
		self.assertLess(abs((m.moonrise - at(date(2026, 10, 24), "17:00:00", "America/New_York")).total_seconds()), 180)
		self.assertLess(abs((m.moonset - at(date(2026, 10, 24), "05:26:00", "America/New_York")).total_seconds()), 180)
		self.assertTrue(m.waxing)

	def test_a_day_without_a_moonrise_has_none(self):
		zone = ZoneInfo("America/New_York")
		days = [moon_day(NEW_YORK, date(2026, 10, 1) + timedelta(days=n), zone) for n in range(31)]
		self.assertTrue(any(d.moonrise is None for d in days), "a month has a day the moon does not rise")
		self.assertTrue(all(d.moonrise is not None or d.moonset is not None for d in days))

	def test_the_moons_place_is_read_in_utc_whatever_the_zone(self):
		# Skyfield: at 21:00 New York time the moon is 42.9° up, bearing 120.1°; astral alone reads 21:00 as UTC and puts it at the horizon
		local = datetime(2026, 10, 24, 21, 0, tzinfo=ZoneInfo("America/New_York"))
		for when in (local, local.astimezone(timezone.utc), local.astimezone(ZoneInfo("Asia/Tokyo"))):
			with self.subTest(zone=when.tzinfo):
				p = moon_at(NEW_YORK, when)
				self.assertLess(abs(p.elevation - 42.9), 1.5)
				self.assertLess(abs(p.azimuth - 120.1), 1.5)

class TestLocation(unittest.TestCase):
	def test_the_location_is_the_system_settings(self):
		self.assertEqual(device_place({ "location": { "latitude": 1.5, "longitude": -2 } }), Place(1.5, -2.0))

	def test_no_location_says_where_to_set_it(self):
		for system in (None, {}, { "location": None }, { "location": { "latitude": "x", "longitude": 0 } }, { "location": { "latitude": 91, "longitude": 0 } }):
			with self.subTest(system=system):
				with self.assertRaises(PermanentError) as caught:
					device_place(system)
				self.assertIn("System settings", str(caught.exception))

class TestDrawing(unittest.TestCase):
	def test_the_moon_is_lit_on_the_right_when_waxing_in_the_north(self):
		# the left-hand mirror is the waning moon in the north, and the waxing one in the south
		self.assertNotIn("matrix", draw.moon_svg(5, southern=False))
		self.assertIn("matrix", draw.moon_svg(20, southern=False))
		self.assertIn("matrix", draw.moon_svg(5, southern=True))
		self.assertNotIn("matrix", draw.moon_svg(20, southern=True))

	def test_the_arc_faces_the_equator(self):
		# the north's sun crosses the south, in the middle of the drawing; the south's crosses the north
		self.assertAlmostEqual(draw._x(180, 180), draw.ARC_W / 2)
		self.assertAlmostEqual(draw._x(0, 0), draw.ARC_W / 2)
		# facing south, the east is on the left; facing north, on the right
		self.assertLess(draw._x(90, 180), draw.ARC_W / 2)
		self.assertGreater(draw._x(90, 0), draw.ARC_W / 2)

	def test_the_arc_draws_both_paths_and_where_each_is_now_when_it_is_up(self):
		zone = ZoneInfo("America/New_York")
		# 14:00: the sun is up, the moon (rising at 17:00) is not
		svg = draw.arc_svg(sky_of(NEW_YORK, datetime(2026, 10, 24, 14, 0, tzinfo=zone)), "07:21", "18:04")
		for part in ("arc-sun ", "arc-moon ", "arc-sun-now", "arc-horizon", ">S<", ">07:21<", ">18:04<"):
			self.assertIn(part, svg)
		self.assertNotIn("arc-moon-now", svg)
		self.assertIn('d="M', svg.split('class="arc-sun text-secondary-1" ')[1][:10])
		# 21:00: the other way round
		svg = draw.arc_svg(sky_of(NEW_YORK, datetime(2026, 10, 24, 21, 0, tzinfo=zone)), "07:21", "18:04")
		self.assertIn("arc-moon-now", svg)
		self.assertNotIn("arc-sun-now", svg)

	def test_the_moons_path_has_no_break_where_the_moon_is(self):
		# a calendar day's path breaks at midnight, when this gibbous moon is high: the path around now has its ends far below the horizon
		sky = sky_of(NEW_YORK, datetime(2026, 10, 24, 21, 0, tzinfo=ZoneInfo("America/New_York")))
		self.assertLess(sky.moon_path[0][1].elevation, 0)
		self.assertLess(sky.moon_path[-1][1].elevation, 0)

	def test_a_tall_page_has_a_taller_drawing(self):
		sky = sky_of(NEW_YORK, NOW)
		self.assertIn('viewBox="0 0 1000 520"', draw.arc_svg(sky, "", ""))
		self.assertIn('viewBox="0 0 640 860"', draw.arc_svg(sky, "", "", tall=True))

	def test_a_polar_day_path_wraps_and_is_cut_at_the_edge(self):
		sky = sky_of(TROMSO, datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")))
		up, down = draw._paths(sky.sun_path, 180.0, draw.Frame(draw.ARC_W, 520.0, 50.0))
		self.assertEqual(down, "", "the sun never goes down")
		for segment in up.split("M")[1:]:
			x0, x1 = float(segment.split(" ")[0]), float(segment.split("L")[1].split(" ")[0])
			self.assertLess(abs(x1 - x0), draw.ARC_W / 2)

class FakeSettings:
	THEME = { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 }
	def __init__(self, orientation: str = "landscape", **system):
		self.docs = { "display": { "orientation": orientation }, "system": { "timeFormat": "24h", "timezoneName": "America/New_York",
			"location": { "latitude": 40.7128, "longitude": -74.006 }, **system }, "theme": self.THEME }
	def open(self, name: str):
		return _Cob(self.docs.get(name))

NOW = datetime(2026, 10, 24, 14, 0, tzinfo=ZoneInfo("America/New_York"))

def make_context(orientation: str = "landscape", now: datetime = NOW, dimensions=(800, 480), **system) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(ConfigurationManager, ConfigurationManager(storage_path=storage_path()))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, **system)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, dimensions, now)

class TestPage(unittest.IsolatedAsyncioTestCase):
	def test_views_come_in_page_order_and_none_is_today(self):
		self.assertEqual(chosen_views({}), ["today"])
		self.assertEqual(chosen_views({ "views": [] }), ["today"])
		self.assertEqual(chosen_views({ "views": ["arc", "today"] }), ["today", "arc"])
		with self.assertRaises(PermanentError):
			chosen_views({ "views": ["stars"] })

	def test_the_change_on_yesterday(self):
		self.assertEqual(change(timedelta(hours=10, minutes=2), timedelta(hours=10)), "+2m on yesterday")
		self.assertEqual(change(timedelta(hours=10), timedelta(hours=10, minutes=3)), "-3m on yesterday")
		self.assertEqual(change(timedelta(hours=10), timedelta(hours=10)), "same as yesterday")
		self.assertEqual(change(timedelta(hours=10), timedelta(hours=10), short=True), "+0m")
		self.assertEqual(change(None, timedelta(hours=10)), "")

	def test_the_clock_is_the_devices(self):
		when = datetime(2026, 10, 24, 18, 5, tzinfo=ZoneInfo("America/New_York"))
		self.assertEqual(clock(when, False), "18:05")
		self.assertEqual(clock(when, True), "6:05 PM")
		self.assertEqual(clock(None, True), "")

	async def test_one_page_per_view_drawn_at_the_target_size(self):
		ds = SunMoonAsync("sun-moon", "Sun and Moon")
		pages = await ds.open_async(make_context(), { "views": ["today", "arc"] })
		self.assertEqual([p.view for p in pages], ["today", "arc"])
		with patch.object(sun_moon_module, "RenderSession", FakeRenderSession):
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				for page in pages:
					result = await ds.render_async(make_context(orientation=orientation), {}, page)
					assert result is not None and FakeRenderSession.last is not None
					self.assertEqual(result.image.size, size)
					self.assertEqual(FakeRenderSession.last.params["view"], page.view)
					self.assertEqual("arc_svg" in FakeRenderSession.last.params, page.view == "arc")

	async def test_the_page_says_what_today_is(self):
		pages = await SunMoonAsync("sun-moon", "Sun and Moon").open_async(make_context(), { "views": ["today"] })
		params = page_params(pages[0], {})
		self.assertEqual(params["heading"], "Sun and Moon")
		self.assertEqual(params["date"], "Saturday, October 24")
		self.assertEqual(params["moon_name"], "Waxing Gibbous")
		self.assertEqual(params["next_full"], "Mon Oct 26")
		self.assertRegex(params["sunrise"], r"^0\d:\d\d$")
		self.assertRegex(params["change"], r"^-\dm on yesterday$")
		self.assertEqual(params["polar"], "")

	async def test_the_arc_says_when_a_moon_that_is_down_rises(self):
		pages = await SunMoonAsync("sun-moon", "Sun and Moon").open_async(make_context(), { "views": ["arc"] })
		self.assertEqual(page_params(pages[0], {})["moon_line"], "Waxing Gibbous, rises 17:00")
		later = await SunMoonAsync("sun-moon", "Sun and Moon").open_async(make_context(now=NOW.replace(hour=21)), { "views": ["arc"] })
		self.assertEqual(page_params(later[0], {})["moon_line"], "Waxing Gibbous, 96% lit")
		tall = await SunMoonAsync("sun-moon", "Sun and Moon").open_async(make_context("portrait"), { "views": ["arc"] })
		self.assertTrue(tall[0].tall)

	async def test_a_polar_day_says_so_on_the_page(self):
		ctx = make_context(now=datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")), location={ "latitude": 69.6492, "longitude": 18.9553 })
		pages = await SunMoonAsync("sun-moon", "Sun and Moon").open_async(ctx, {})
		params = page_params(pages[0], {})
		self.assertEqual(params["polar"], "The sun does not set today")
		self.assertEqual(params["length"], "24h 00m")
		self.assertEqual(page_params(Page("arc", pages[0].sky, False), {})["polar_short"], "Sun up all day")

	async def test_no_location_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			await SunMoonAsync("sun-moon", "Sun and Moon").open_async(make_context(location=None), {})
		with self.assertRaises(PermanentError):
			await SunMoonOverlayAsync("sun-moon-overlay", "Sun and Moon Overlay").open_async(make_context(location=None), {})

	async def test_anything_but_a_page_is_nothing_to_show(self):
		self.assertIsNone(await SunMoonAsync("sun-moon", "Sun and Moon").render_async(make_context(), {}, None))
		self.assertIsNone(await SunMoonOverlayAsync("sun-moon-overlay", "Sun and Moon Overlay").render_async(make_context(), {}, None))

class TestOverlay(unittest.IsolatedAsyncioTestCase):
	def test_a_view_is_one_of_three_and_unset_is_sun(self):
		self.assertEqual(chosen_view({}), "sun")
		self.assertEqual(chosen_view({ "view": "moon" }), "moon")
		with self.assertRaises(PermanentError):
			chosen_view({ "view": "stars" })

	def test_each_view_says_its_line(self):
		sky = sky_of(NEW_YORK, NOW)
		lines, icon, title = view_lines("sun", sky, False)
		self.assertRegex(title, r"^0\d:\d\d – 1\d:\d\d$")
		self.assertIsNotNone(icon)
		_, _, title = view_lines("daylight", sky, False)
		self.assertRegex(title, r"^\d+h \d\dm -\dm$")
		_, icon, title = view_lines("moon", sky, False)
		self.assertEqual(title, "Waxing Gibbous 96%")
		assert icon is not None
		self.assertIn("<circle", icon)
		polar = sky_of(TROMSO, datetime(2026, 12, 21, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")))
		self.assertEqual(view_lines("sun", polar, False)[2], "Sun down all day")

	async def test_the_overlay_is_drawn_at_the_zones_size(self):
		ds = SunMoonOverlayAsync("sun-moon-overlay", "Sun and Moon Overlay")
		calls = []
		def fake_render(stm, theme, dimensions, lines, *rest):
			calls.append((dimensions, lines))
			return Image.new("RGBA", dimensions)
		with patch.object(overlay_module, "render_overlay", fake_render):
			for view in ("sun", "daylight", "moon"):
				ctx = make_context(dimensions=(400, 80))
				state = await ds.open_async(ctx, { "view": view })
				result = await ds.render_async(ctx, { "view": view }, state)
				assert result is not None
				self.assertEqual(result.image.size, (400, 80))
		self.assertEqual(len(calls), 3)

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The pages and overlays as Chromium draws them. The images are in .test-output/sun_moon for a look."""
	async def test_pages_are_drawn_at_the_display_size(self):
		folder = Path(test_output_path_for("sun_moon"))
		ds = SunMoonAsync("sun-moon", "Sun and Moon")
		places = (("new-york", NOW, {}), ("new-york-night", NOW.replace(hour=21), {}), ("sydney", datetime(2026, 10, 24, 18, 0, tzinfo=ZoneInfo("Australia/Sydney")), { "location": { "latitude": -33.8688, "longitude": 151.2093 } }),
			("tromso", datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")), { "location": { "latitude": 69.6492, "longitude": 18.9553 } }),
			# the longest big times: a 12-hour clock and a sunset after midnight ("12:04 AM (+1)") are made smaller to fit, not cut
			("reykjavik-12h", datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Atlantic/Reykjavik")), { "location": { "latitude": 64.1466, "longitude": -21.9426 }, "timeFormat": "12h" }))
		for name, now, system in places:
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				pages = await ds.open_async(make_context(orientation, now, **system), { "views": ["today", "arc"] })
				for page in pages:
					with self.subTest(place=name, orientation=orientation, view=page.view):
						result = await ds.render_async(make_context(orientation, now, **system), {}, page)
						assert result is not None
						self.assertEqual(result.image.size, size)
						result.image.save(folder.joinpath(f"{name}-{orientation}-{page.view}.png"))
						self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")

	async def test_overlays_are_drawn_at_the_zones_size(self):
		folder = Path(test_output_path_for("sun_moon"))
		ds = SunMoonOverlayAsync("sun-moon-overlay", "Sun and Moon Overlay")
		for view in ("sun", "daylight", "moon"):
			with self.subTest(view=view):
				ctx = make_context(dimensions=(400, 80))
				result = await ds.render_async(ctx, { "view": view }, await ds.open_async(ctx, { "view": view }))
				assert result is not None
				self.assertEqual(result.image.size, (400, 80))
				result.image.save(folder.joinpath(f"overlay-{view}.png"))

if __name__ == "__main__":
	unittest.main()
