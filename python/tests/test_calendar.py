import atexit
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
from PIL import Image

from ..datasources.calendar_sources.calendar_sources import CalendarSources, ran_out_note
from ..datasources.calendar import calendar as calendar_module
from ..datasources.calendar.calendar import CalendarPagesAsync, Layout, Page, Slot, agenda_params, chosen_views, month_params, month_weeks, page_params, query_range, rolling_weeks, weeks_params
from ..datasources.contracts.calendar import CalendarApi, Event
from ..datasources.calendar_sources.sources import NotACalendar, auth_headers, caldav_calendars, events_between, holiday_events, last_day, parse_calendar, safe_color, web_url
from ..datasources.data_source import DataSourceExecutionContext
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..utils import url_guard
from ..web.documents import plugin_content_errors
from ..utils.image_utils import chrome_command
from ..web.deps import get_time_of_day
from .fake_internet import FakeInternet, fixture_text
from .test_datasource_fixes import STATIC, FakeDatasourceSettings, FakeRenderSession, _Cob
from .utils import test_output_path_for, save_datasource_settings, use_transport
from .test_web_api import WebApiTestBase

# the display is on the US west coast in October (daylight time); "now" is Wednesday 7 October 2026, noon
ZONE = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=ZONE)
TODAY = NOW.date()
FAMILY = { "name": "Family", "color": "#3366cc", "source": "ical", "url": "webcal://calendar.example.test/family.ics", "auth": "none" }
CALENDARS = [
	FAMILY,
	{ "name": "Work", "color": "#cc3333", "source": "caldav", "url": "https://dav.example.test/cal/work/", "auth": "none" },
	{ "name": "Season", "source": "ical", "url": "https://calendar.example.test/season.ics", "auth": "none" },
	{ "name": "Old season", "source": "ical", "url": "https://calendar.example.test/ended.ics", "auth": "none" },
	{ "name": "Private", "source": "ical", "url": "https://calendar.example.test/private.ics", "auth": "basic", "username": "user", "password": "pass" },
	{ "name": "Locked", "source": "ical", "url": "https://calendar.example.test/private.ics", "auth": "basic", "username": "user", "password": None },
	{ "name": "Sign-in page", "source": "ical", "url": "https://calendar.example.test/page", "auth": "none" },
	{ "name": "Off", "source": "ical", "url": "https://calendar.example.test/family.ics", "auth": "none", "enabled": False },
]
HOLIDAYS = [{ "name": "US", "color": "#228833", "country": "US", "subdivision": None }]

class FakeSettings:
	"""Stands in for SettingsConfigurationManager: the display and system documents and a theme."""
	THEME = { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 }
	def __init__(self, orientation: str = "landscape", time_format: str = "24h"):
		self.docs = { "display": { "orientation": orientation }, "system": { "timeFormat": time_format }, "theme": self.THEME }
	def open(self, name: str):
		return _Cob(self.docs.get(name))

class Context(DataSourceExecutionContext):
	"""
	The pages' context in these tests: one settings document (a fake) serves the pages and their provider, the Calendar Sources, which is the one
	`provide` answers (how a provider is chosen is `test_provide`'s).
	"""
	def provide(self, kind):
		assert kind is CalendarApi
		return CalendarSources("calendar-sources", "Calendar Sources"), self

def make_context(calendars: list|None = None, holidays: list|None = None, orientation: str = "landscape", time_format: str = "24h", now: datetime = NOW, **more) -> DataSourceExecutionContext:
	root = ServiceContainer()
	settings = { "calendars": CALENDARS if calendars is None else calendars, "holidays": HOLIDAYS if holidays is None else holidays, "cacheHours": 0, **more }
	root.add_service(DatasourceConfigurationManager, cast(Any, FakeDatasourceSettings(settings)))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation, time_format)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	# where the data sources' own folders are (their page templates): the source root
	root.add_service(ConfigurationManager, ConfigurationManager())
	return Context(root, (800, 480), now)

def family() -> Any:
	return parse_calendar(fixture_text("calendar-family.ics").encode())

def at(day: int, hour: int = 0, minute: int = 0, month: int = 10) -> datetime:
	return datetime(2026, month, day, hour, minute, tzinfo=ZONE)

class TestReading(unittest.TestCase):
	def october(self) -> list[Event]:
		return events_between(family(), at(1), at(1, month=11) + timedelta(days=3), ZONE, "Family", "#3366cc")

	def test_recurrences_are_expanded_and_an_exception_left_out(self):
		practice = [e.start for e in self.october() if e.title == "Soccer practice"]
		# every Monday at 17:30 (a floating time is the device's own), except the 12th
		self.assertEqual(practice, [at(5, 17, 30), at(19, 17, 30), at(26, 17, 30), at(2, 17, 30, month=11)])

	def test_times_are_in_the_device_zone(self):
		by_title = { e.title: e for e in self.october() }
		self.assertEqual(by_title["Dentist"].start, at(8, 9, 30), "16:30 UTC")
		self.assertEqual(by_title["Call with Grandma"].start, at(10, 17, 0), "20:00 in New York")
		self.assertEqual(by_title["Dentist"].location, "")
		self.assertEqual(by_title["Soccer practice"].location, "North field")

	def test_all_day_and_multi_day_events_cover_their_days(self):
		by_title = { e.title: e for e in self.october() }
		self.assertTrue(by_title["School holiday"].all_day)
		self.assertEqual(by_title["School holiday"].days(), [date(2026, 10, 16)])
		self.assertEqual(by_title["Camping trip"].days(), [date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25)])
		self.assertEqual(by_title["Night flight"].days(), [date(2026, 10, 30), date(2026, 10, 31)], "overnight: on both days")
		self.assertEqual(by_title["Conference"].days()[-1], date(2026, 11, 2), "into the next month")

	def test_a_cancelled_event_is_left_out(self):
		self.assertNotIn("Cancelled lunch", [e.title for e in self.october()])

	def test_a_page_that_is_no_calendar_is_said_so(self):
		with self.assertRaises(NotACalendar):
			parse_calendar(b"<html><body>Sign in</body></html>")

	def test_caldav_answers_hold_one_calendar_per_event(self):
		cals = caldav_calendars(fixture_text("calendar-dav.xml").encode())
		events = [e for cal in cals for e in events_between(cal, at(5), at(10), ZONE, "Work", None)]
		self.assertEqual([(e.title, e.start) for e in events if e.title == "Team standup"][:2], [("Team standup", at(5, 9)), ("Team standup", at(6, 9))])
		self.assertIn("Quarterly review", [e.title for e in events])
		with self.assertRaises(NotACalendar):
			caldav_calendars(b"<html/>")

	def test_webcal_is_https_and_colors_are_checked(self):
		self.assertEqual(web_url("webcal://calendar.example.test/x.ics"), "https://calendar.example.test/x.ics")
		self.assertEqual(web_url("https://a/x.ics"), "https://a/x.ics")
		self.assertEqual(safe_color("#3366cc"), "#3366cc")
		for bad in ("red", "#12", "#3366cc;background:url(x)", None, 5):
			self.assertIsNone(safe_color(bad))

	def test_sign_in_headers_and_a_missing_secret(self):
		self.assertEqual(auth_headers({ "auth": "none" }), {})
		self.assertEqual(auth_headers({ "auth": "basic", "username": "user", "password": "pass" }), { "Authorization": "Basic dXNlcjpwYXNz" })
		self.assertEqual(auth_headers({ "auth": "bearer", "token": "t" }), { "Authorization": "Bearer t" })
		for row in ({ "name": "X", "auth": "basic", "username": "u" }, { "name": "X", "auth": "bearer" }):
			with self.subTest(row), self.assertRaisesRegex(PermanentError, "'X' needs"):
				auth_headers(row)

class TestRunningOut(unittest.TestCase):
	"""A calendar where nothing repeats (or every repeat ends) is empty after its last day: a season's fixtures, a year's file."""
	def test_a_calendar_with_a_repeat_that_never_ends_does_not_run_out(self):
		self.assertIsNone(last_day(family(), ZONE))

	def test_a_season_runs_out_on_its_last_match(self):
		self.assertEqual(last_day(parse_calendar(fixture_text("calendar-season.ics").encode()), ZONE), date(2027, 5, 30))
		self.assertEqual(last_day(parse_calendar(fixture_text("calendar-ended.ics").encode()), ZONE), date(2026, 5, 24))

	def test_repeats_that_end_run_out_at_their_last_occurrence(self):
		counted = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20261005T090000Z\r\nDTEND:20261005T100000Z\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
		self.assertEqual(last_day(parse_calendar(counted), ZONE), date(2026, 10, 19))
		until = counted.replace(b"COUNT=3", b"UNTIL=20261102T090000Z")
		self.assertEqual(last_day(parse_calendar(until), ZONE), date(2026, 11, 2))
		self.assertIsNone(last_day(parse_calendar(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"), ZONE), "nothing at all is not 'ran out'")

	def test_the_note_names_the_day(self):
		self.assertEqual(ran_out_note("League", date(2026, 10, 20), TODAY, date(2026, 11, 1)), "League has no events after 20 Oct 2026")
		self.assertEqual(ran_out_note("League", date(2026, 5, 24), TODAY, date(2026, 11, 1)), "League ended on 24 May 2026")
		self.assertIsNone(ran_out_note("League", date(2027, 5, 30), TODAY, date(2026, 11, 1)), "past what the page shows: nothing to say yet")
		self.assertIsNone(ran_out_note("League", None, TODAY, date(2026, 11, 1)))

class TestHolidays(unittest.TestCase):
	def test_a_countrys_holidays_are_all_day_events_in_the_sets_color(self):
		found = holiday_events({ "name": "US", "color": "#228833", "country": "US" }, [2026], ZONE)
		christmas = [e for e in found if e.start.date() == date(2026, 12, 25)]
		self.assertEqual(len(christmas), 1)
		self.assertTrue(christmas[0].all_day and christmas[0].holiday)
		self.assertEqual((christmas[0].calendar, christmas[0].color), ("US", "#228833"))

	def test_a_subdivision_adds_its_own(self):
		country = { d.start.date() for d in holiday_events({ "name": "GB", "country": "GB" }, [2026], ZONE) }
		scotland = { d.start.date() for d in holiday_events({ "name": "Scotland", "country": "GB", "subdivision": "SCT" }, [2026], ZONE) }
		self.assertIn(date(2026, 11, 30), scotland - country, "St Andrew's Day")

	def test_an_unknown_country_or_subdivision_is_permanent(self):
		with self.assertRaisesRegex(PermanentError, "country 'ZZ' is not known"):
			holiday_events({ "name": "X", "country": "ZZ" }, [2026], ZONE)
		with self.assertRaisesRegex(PermanentError, "subdivision 'XX'"):
			holiday_events({ "name": "X", "country": "US", "subdivision": "XX" }, [2026], ZONE)

class TestGrid(unittest.TestCase):
	def test_the_weeks_of_the_month_start_on_the_chosen_day(self):
		monday = month_weeks(TODAY, "monday")
		self.assertEqual((monday[0][0], monday[-1][-1], len(monday)), (date(2026, 9, 28), date(2026, 11, 1), 5))
		sunday = month_weeks(TODAY, "sunday")
		self.assertEqual((sunday[0][0], sunday[-1][-1]), (date(2026, 9, 27), date(2026, 10, 31)))
		self.assertTrue(all(len(w) == 7 for w in monday))
		# a month that needs six rows
		self.assertEqual(len(month_weeks(date(2026, 8, 15), "monday")), 6)

	def test_what_is_read_is_what_the_views_show(self):
		self.assertEqual(query_range(TODAY, ["month"], "monday", 7, ZONE), (datetime(2026, 9, 28, tzinfo=ZONE), datetime(2026, 11, 2, tzinfo=ZONE)))
		self.assertEqual(query_range(TODAY, ["agenda"], "monday", 7, ZONE), (datetime(2026, 10, 7, tzinfo=ZONE), datetime(2026, 10, 14, tzinfo=ZONE)))
		self.assertEqual(query_range(date(2026, 10, 28), ["month", "agenda"], "monday", 10, ZONE)[1], datetime(2026, 11, 7, tzinfo=ZONE))

	def test_views_come_in_page_order_and_none_is_month(self):
		self.assertEqual(chosen_views({ "views": ["agenda", "month"] }), ["month", "agenda"])
		self.assertEqual(chosen_views({ "views": ["agenda", "weeks", "month"] }), ["month", "weeks", "agenda"])
		self.assertEqual(chosen_views({ "views": ["agenda"] }), ["agenda"])
		for nothing in ({}, { "views": [] }, { "views": None }, { "views": ["week"] }):
			self.assertEqual(chosen_views(nothing), ["month"])

	def slot(self) -> Slot:
		events = events_between(family(), at(28, month=9), at(2, month=11), ZONE, "Family", "#3366cc")
		events += holiday_events(HOLIDAYS[0], [2026], ZONE)
		return Slot(TODAY, ZONE, sorted(events, key=lambda e: e.start))

	def cell(self, params: dict, day: date) -> dict:
		for week in params["weeks"]:
			for cell in week["days"]:
				if cell["day"] == day.day and cell["in_month"] == (day.month == 10):
					return cell
		raise AssertionError(day)

	def test_week_numbers_are_iso_and_shown_only_when_asked_for(self):
		layout = Layout((800, 480), 1.0, False)
		slot = self.slot()
		params = month_params(slot, {}, layout)
		self.assertFalse(params["week_numbers"])
		# the row of 5 October 2026 is ISO week 41
		self.assertEqual([w["number"] for w in params["weeks"]], [40, 41, 42, 43, 44])
		slot.week_start, slot.week_numbers = "sunday", True
		params = month_params(slot, {}, layout)
		self.assertTrue(params["week_numbers"])
		# a Sunday-first row is numbered by its Monday: Sun 4 Oct is in the row of Mon 5 Oct
		self.assertEqual(params["weeks"][1]["days"][0]["day"], 4)
		self.assertEqual(params["weeks"][1]["number"], 41)

	def test_a_day_lists_holidays_first_then_all_day_then_by_time(self):
		params = month_params(self.slot(), {}, Layout((800, 480), 1.0, False))
		self.assertEqual(params["heading"], "October 2026")
		self.assertEqual(params["weekdays"][:2], ["Mon", "Tue"])
		self.assertTrue(self.cell(params, TODAY)["today"])
		columbus = self.cell(params, date(2026, 10, 12))
		self.assertTrue(columbus["entries"][0]["holiday"])
		self.assertNotIn("Soccer practice", [i["title"] for i in columbus["entries"]], "the exception date")
		dentist = self.cell(params, date(2026, 10, 8))["entries"][0]
		self.assertEqual((dentist["title"], dentist["time"], dentist["bar"], dentist["color"]), ("Dentist", "9:30", False, "#3366cc"))
		camping = self.cell(params, date(2026, 10, 24))["entries"][0]
		self.assertTrue(camping["bar"])
		self.assertFalse(self.cell(params, date(2026, 11, 1))["in_month"])

	def test_the_weekly_view_runs_on_across_months_and_tints_every_other_one(self):
		slot = self.slot()
		params = weeks_params(slot, { "weeksAhead": 4 }, Layout((800, 480), 1.0, False))
		days = [cell for row in params["weeks"] for cell in row["days"]]
		self.assertEqual((len(params["weeks"]), days[0]["date"], days[-1]["date"]), (5, date(2026, 10, 5), date(2026, 11, 8)), "this week and four more")
		self.assertEqual(params["heading"], "5 Oct – 8 Nov 2026")
		self.assertTrue(all(c["in_month"] for c in days), "no day is dimmed as outside the month")
		self.assertEqual({ c["date"].month for c in days if c["alt"] }, { 11 }, "October (today's month) is plain, November tinted")
		self.assertEqual([(c["date"], c["label"]) for c in days if c["label"]], [(date(2026, 10, 5), "Oct"), (date(2026, 11, 1), "Nov")])
		self.assertTrue(self.cell_of(params, date(2026, 10, 12))["entries"][0]["holiday"])
		slot.week_start = "sunday"
		self.assertEqual(weeks_params(slot, { "weeksAhead": 0 }, Layout((800, 480), 1.0, False))["weeks"][0]["days"][0]["date"], date(2026, 10, 4))
		self.assertEqual(len(weeks_params(slot, { "weeksAhead": 99 }, Layout((800, 480), 1.0, False))["weeks"]), 9, "at most eight more")
		self.assertEqual(len(weeks_params(slot, {}, Layout((800, 480), 1.0, False))["weeks"]), 5, "four more by default")

	def cell_of(self, params: dict, day: date) -> dict:
		return next(c for row in params["weeks"] for c in row["days"] if c["date"] == day)

	def test_the_weekly_view_reads_its_weeks(self):
		self.assertEqual(query_range(TODAY, ["weeks"], "monday", 7, ZONE, 4), (datetime(2026, 10, 5, tzinfo=ZONE), datetime(2026, 11, 9, tzinfo=ZONE)))
		self.assertEqual(rolling_weeks(date(2026, 12, 30), "monday", 1)[-1][-1], date(2027, 1, 10), "across the new year")

	def test_what_ended_before_the_slot_is_faded(self):
		slot = self.slot()
		slot.now = NOW
		params = month_params(slot, {}, Layout((800, 480), 1.0, False))
		self.assertTrue(self.cell(params, date(2026, 10, 5))["entries"][0]["past"], "Monday's events are over")
		self.assertFalse(self.cell(params, date(2026, 10, 8))["entries"][0]["past"], "tomorrow's dentist is not")
		# today: the standup is over at noon, the evening is not
		today = Slot(TODAY, ZONE, [Event(at(7, 9), at(7, 9, 15), False, "Standup", "", "Work", None), Event(at(7, 18), at(7, 19), False, "Dinner", "", "Family", None)], now=NOW)
		entries = agenda_params(today, {}, Layout((800, 480), 1.0, False))["days"][0]["entries"]
		self.assertEqual([(e["title"], e["past"]) for e in entries], [("Standup", True), ("Dinner", False)])

	def test_a_day_with_more_than_fits_says_how_many_more(self):
		slot = Slot(TODAY, ZONE, [Event(at(7, h), at(7, h, 30), False, f"Meeting {h}", "", "Work", None) for h in range(8, 20)])
		layout = Layout((800, 480), 1.0, False)
		fits = layout.month_slots(5)
		self.assertGreater(fits, 0)
		cell = self.cell(month_params(slot, {}, layout), TODAY)
		self.assertEqual(len(cell["entries"]) + cell["more"], 12)
		self.assertEqual(len(cell["entries"]), fits - 1, "the last line says how many more")
		# a bigger text fits fewer
		self.assertLess(Layout((800, 480), 1.45, False).month_slots(5), fits)
		self.assertLessEqual(Layout((800, 480), 1.0, False, notes=3).month_slots(5), fits, "the footer's notes take room")

	def test_twelve_hour_times_and_a_portrait_grid(self):
		layout = Layout((480, 800), 1.0, True)
		slot = self.slot()
		slot.week_start = "sunday"
		params = month_params(slot, {}, layout)
		self.assertEqual(params["weekdays"][:2], ["S", "M"])
		self.assertEqual(self.cell(params, date(2026, 10, 8))["entries"][0]["time"], "", "a narrow day has no room for the time")
		self.assertEqual(self.cell(month_params(slot, {}, Layout((800, 480), 1.0, True)), date(2026, 10, 8))["entries"][0]["time"], "9:30a")
		self.assertEqual(layout.clock(at(8, 17, 30)), "5:30 PM")

	def test_the_agenda_groups_the_coming_days(self):
		params = agenda_params(self.slot(), { "agendaDays": 7 }, Layout((800, 480), 1.0, False))
		self.assertEqual(params["heading"], "Agenda")
		labels = [d["label"] for d in params["days"]]
		self.assertEqual(labels[0], "Tomorrow", "nothing today, so the first day is tomorrow")
		self.assertIn("Saturday, 10 October", labels)
		saturday = params["days"][labels.index("Saturday, 10 October")]["entries"][0]
		self.assertEqual((saturday["title"], saturday["range"]), ("Call with Grandma", "17:00 – 17:30"))
		monday = params["days"][labels.index("Monday, 12 October")]["entries"]
		self.assertEqual((monday[0]["holiday"], monday[0]["range"]), (True, "All day"))
		self.assertEqual(params["more"], 0)

	def test_an_overnight_event_shows_on_both_days(self):
		slot = Slot(date(2026, 10, 30), ZONE, events_between(family(), at(30), at(1, month=11), ZONE, "Family", None))
		params = agenda_params(slot, { "agendaDays": 2 }, Layout((800, 480), 1.0, False))
		ranges = { (d["label"], i["title"]): i["range"] for d in params["days"] for i in d["entries"] }
		self.assertEqual(ranges[("Today", "Night flight")], "22:00 – …")
		self.assertEqual(ranges[("Tomorrow", "Night flight")], "… – 06:00")

	def test_an_agenda_too_long_for_the_page_says_how_many_more(self):
		slot = Slot(TODAY, ZONE, [Event(at(7 + d, 9), at(7 + d, 10), False, f"Item {d}-{n}", "", "Work", None) for d in range(7) for n in range(6)])
		params = agenda_params(slot, { "agendaDays": 7 }, Layout((800, 480), 1.0, False))
		shown = sum(len(d["entries"]) for d in params["days"])
		self.assertGreater(params["more"], 0)
		self.assertEqual(shown + params["more"], 42)
		self.assertLessEqual(shown + len(params["days"]), Layout((800, 480), 1.0, False).agenda_lines())

	def test_nothing_coming_is_an_empty_agenda(self):
		params = agenda_params(Slot(TODAY, ZONE), {}, Layout((800, 480), 1.0, False))
		self.assertEqual((params["days"], params["more"]), ([], 0))

class TestOpen(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)

	def asked(self) -> list[str]:
		return sorted(f"{r.method} {r.url}" for r in self.fake.requests)

	async def test_both_views_are_two_pages_of_one_read(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "views": ["agenda", "month"], "calendars": ["Family"] })
		self.assertEqual([p.view for p in pages], ["month", "agenda"])
		self.assertIs(pages[0].slot, pages[1].slot, "the events are read once for the slot")
		self.assertEqual(self.asked(), ["GET https://calendar.example.test/family.ics"], "webcal read as https, once")
		self.assertIn("Dentist", [e.title for e in pages[0].slot.events])
		self.assertIn("Columbus Day", [e.title for e in pages[0].slot.events], "all holiday sets when none is chosen")

	async def test_the_week_start_and_week_numbers_come_from_the_data_sources_settings(self):
		ds = CalendarPagesAsync("calendar", "Calendar")
		[page] = await ds.open_async(make_context([], [], weekStart="sunday", weekNumbers=True), { "weekStart": "monday" })
		self.assertEqual((page.slot.week_start, page.slot.week_numbers), ("sunday", True), "a task's own value is not read")
		[page] = await ds.open_async(make_context([], []), {})
		self.assertEqual((page.slot.week_start, page.slot.week_numbers), ("monday", False))

	async def test_three_views_are_three_pages(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "views": ["agenda", "weeks", "month"], "calendars": ["Family"] })
		self.assertEqual([p.view for p in pages], ["month", "weeks", "agenda"])

	async def test_one_view_is_one_page_and_none_is_the_month(self):
		ds = CalendarPagesAsync("calendar", "Calendar")
		self.assertEqual([p.view for p in await ds.open_async(make_context(), { "views": ["agenda"], "calendars": ["Family"] })], ["agenda"])
		self.assertEqual([p.view for p in await ds.open_async(make_context(), { "views": [], "calendars": ["Family"] })], ["month"])

	async def test_no_calendars_is_an_empty_month_not_a_failure(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context([], []), {})
		self.assertEqual(([p.view for p in pages], pages[0].slot.events, pages[0].slot.notes), (["month"], [], []))
		self.assertEqual(self.fake.requests, [])

	async def test_none_chosen_is_every_enabled_calendar(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context([FAMILY, CALENDARS[1], CALENDARS[-1]], []), {})
		self.assertEqual(self.asked(), ["GET https://calendar.example.test/family.ics", "REPORT https://dav.example.test/cal/work/"], "the disabled one is not read")
		self.assertEqual({ e.calendar for e in pages[0].slot.events }, { "Family", "Work" })

	async def test_caldav_is_one_report_for_the_range_shown(self):
		await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Work"] })
		[report] = self.fake.requests
		self.assertIn(b'start="20260928T070000Z" end="20261102T070000Z"', report.content)

	async def test_a_calendar_behind_a_sign_in_gets_it(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Private"] })
		self.assertIn("Dentist", [e.title for e in pages[0].slot.events])
		self.assertEqual(self.fake.requests[0].headers["Authorization"], "Basic dXNlcjpwYXNz")

	async def test_a_name_that_is_not_in_the_settings_is_permanent(self):
		with self.assertRaisesRegex(PermanentError, "'Gone' is not in the Calendar Sources settings"):
			await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Family", "Gone"] })
		with self.assertRaisesRegex(PermanentError, "holiday set 'Gone'"):
			await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "holidaySets": ["Gone"] })
		self.assertEqual(self.fake.requests, [])

	async def test_a_calendar_that_fails_is_named_in_the_footer_and_the_rest_show(self):
		with self.assertLogs("python.datasources.calendar_sources.calendar_sources", "WARNING") as logged:
			pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Family", "Sign-in page", "Locked"] })
		self.assertEqual(pages[0].slot.notes, ["Sign-in page could not be loaded: the answer is not a calendar", "The calendar 'Locked' needs a username and password."])
		self.assertIn("Dentist", [e.title for e in pages[0].slot.events])
		self.assertNotIn("calendar.example.test", "\n".join(logged.output), "the log names the calendar, never its address")

	async def test_when_every_calendar_fails_the_slot_fails(self):
		with self.assertRaisesRegex(RuntimeError, "No calendar could be loaded") as raised:
			await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Sign-in page"] })
		self.assertNotIsInstance(raised.exception, PermanentError, "a server can come back")
		with self.assertRaisesRegex(PermanentError, "needs a username and password"):
			await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Locked"] })

	async def test_a_server_error_is_told_without_the_address(self):
		use_transport(self, httpx.MockTransport(lambda r: httpx.Response(401)))
		secret = { **FAMILY, "url": "https://calendar.example.test/private-abc123/basic.ics" }
		with self.assertRaises(RuntimeError) as raised:
			await CalendarPagesAsync("calendar", "Calendar").open_async(make_context([secret], []), {})
		self.assertIn("the server answered 401 (it needs a sign-in)", str(raised.exception))
		self.assertNotIn("abc123", str(raised.exception))

	async def test_a_calendar_that_ran_out_says_so(self):
		pages = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(), { "calendars": ["Season", "Old season"] })
		self.assertEqual(pages[0].slot.notes, ["Old season ended on 24 May 2026"], "the season still has matches past the month shown")
		later = await CalendarPagesAsync("calendar", "Calendar").open_async(make_context(now=datetime(2027, 5, 20, 12, tzinfo=ZONE)), { "calendars": ["Season"] })
		self.assertEqual(later[0].slot.notes, ["Season has no events after 30 May 2027"])

class TestRender(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		use_transport(self, FakeInternet())

	async def render(self, params: dict, orientation: str = "landscape", time_format: str = "24h"):
		ds = CalendarPagesAsync("calendar", "Calendar")
		pages = await ds.open_async(make_context(orientation=orientation), params)
		results = []
		with patch.object(calendar_module, "RenderSession", FakeRenderSession):
			for page in pages:
				result = await ds.render_async(make_context(orientation=orientation, time_format=time_format), params, page)
				assert FakeRenderSession.last is not None
				results.append((result, FakeRenderSession.last))
		return results

	async def test_each_page_is_drawn_with_its_view(self):
		[(month, ms), (agenda, ag)] = await self.render({ "views": ["month", "agenda"], "calendars": ["Family"] })
		assert month is not None and agenda is not None
		self.assertEqual((month.title, ms.params["view"]), ("October 2026", "month"))
		self.assertEqual((agenda.title, ag.params["view"]), ("Agenda", "agenda"))
		self.assertEqual(ms.dimensions, (800, 480))
		self.assertGreater(ms.params["font_px"], 0)

	async def test_portrait_and_the_twelve_hour_clock(self):
		[(_, session)] = await self.render({ "views": ["agenda"], "calendars": ["Family"] }, "portrait", "12h")
		self.assertEqual(session.dimensions, (480, 800))
		ranges = [i["range"] for d in session.params["days"] for i in d["entries"]]
		self.assertIn("9:30 AM – 10:15 AM", ranges)

	async def test_the_title_replaces_the_heading(self):
		[(result, session)] = await self.render({ "calendars": ["Family"], "title": "Our month" })
		assert result is not None
		self.assertEqual((result.title, session.params["heading"]), ("Our month", "Our month"))

	async def test_anything_but_a_page_is_nothing_to_show(self):
		self.assertIsNone(await CalendarPagesAsync("calendar", "Calendar").render_async(make_context(), {}, None))

	async def test_page_params_carry_the_notes(self):
		page = Page("month", Slot(TODAY, ZONE, [], ["A note"]))
		self.assertEqual(page_params(page, {}, Layout((800, 480), 1.0, False))["notes"], ["A note"])

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The pages as Chromium draws them: busy and empty, both views, both orientations. The images are in .test-output/calendar for a look."""
	def setUp(self):
		use_transport(self, FakeInternet())

	async def test_pages_are_drawn_at_the_display_size(self):
		folder = Path(test_output_path_for("calendar"))
		ds = CalendarPagesAsync("calendar", "Calendar")
		for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
			for name, calendars, chosen, numbers in (("busy", None, ["Family", "Work", "Sign-in page"], True), ("empty", [], [], False)):
				params = { "views": ["month", "weeks", "agenda"], "calendars": chosen, "agendaDays": 7, "weeksAhead": 4, "fontSize": "normal" }
				pages = await ds.open_async(make_context(calendars, orientation=orientation, weekNumbers=numbers), params)
				for page in pages:
					with self.subTest(orientation=orientation, name=name, view=page.view):
						result = await ds.render_async(make_context(calendars, orientation=orientation, weekNumbers=numbers), params, page)
						assert result is not None
						self.assertEqual(result.image.size, size)
						result.image.save(folder.joinpath(f"{orientation}-{name}-{page.view}.png"))
						self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")
						self.assertIsInstance(result.image, Image.Image)

TEST_URL = "/api/datasource/calendar-sources/test"
PUBLIC = "93.184.216.34"

class TestSignInStaysWithItsServer(unittest.IsolatedAsyncioTestCase):
	"""A CalDAV server that redirects to another host does not get to hand the user's password on (#456)."""
	async def test_a_basic_sign_in_is_not_sent_to_the_redirect_target(self):
		from ..datasources.calendar_sources.sources import read_caldav
		seen: list[httpx.Request] = []
		def handler(request: httpx.Request) -> httpx.Response:
			seen.append(request)
			request.read()
			if request.url.host == "dav.example.test":
				return httpx.Response(301, headers={ "Location": "https://elsewhere.example.test/cal/" })
			return httpx.Response(207, content=b'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:"/>')
		entry = { "name": "Work", "source": "caldav", "url": "https://dav.example.test/cal/", "auth": "basic", "username": "me", "password": "s3cret" }
		names = { "dav.example.test": [PUBLIC], "elsewhere.example.test": [PUBLIC] }
		async def resolve(host: str, port: int) -> list[str]:
			return names[host]
		async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
			with patch.object(url_guard, "_resolve", resolve):
				self.assertEqual(await read_caldav(client, entry, NOW, NOW + timedelta(days=7)), [])
		self.assertEqual([r.url.host for r in seen], ["dav.example.test", "elsewhere.example.test"])
		self.assertIn("authorization", seen[0].headers)
		self.assertNotIn("authorization", seen[1].headers)
		# a 301 keeps the REPORT and its query: the collection moved
		self.assertEqual((seen[1].method, seen[1].content), ("REPORT", seen[0].content))

class FixedTime:
	def current_time(self) -> datetime:
		return NOW

class TestCalendarRoutes(WebApiTestBase):
	"""The Test button (can the server read this address as a calendar, and when does it run out?) and the country list."""
	def setUp(self):
		super().setUp()
		names = { "calendar.example.test": [PUBLIC], "inside.example.test": ["127.0.0.1"] }
		async def resolve(host: str, port: int) -> list[str]:
			if host not in names:
				raise OSError("no such host")
			return names[host]
		patcher = patch.object(url_guard, "_resolve", resolve)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.app.dependency_overrides[get_time_of_day] = FixedTime

	def ask(self, value, transport=None) -> dict:
		with patch.object(AsyncHttpWorkerPool, "default_transport", transport or AsyncHttpWorkerPool.default_transport):
			resp = self.client.post(TEST_URL, json={ "value": value })
		self.assertEqual(resp.status_code, 200, resp.text)
		answer = resp.json()
		self.assertEqual(sorted(answer), ["message", "ok"])
		return answer

	def test_a_calendar_is_counted_and_named(self):
		self.assertEqual(self.ask("webcal://calendar.example.test/family.ics"), { "ok": True, "message": "9 events in the next 30 days, from “Family”" })

	def test_a_calendar_that_runs_out_is_said_to(self):
		answer = self.ask("https://calendar.example.test/season.ics")
		self.assertTrue(answer["ok"])
		self.assertEqual(answer["message"], "1 event in the next 30 days, from “Example League 2026-27”. Nothing repeats: it has no events after 30 May 2027, and then needs a new address.")
		ended = self.ask("https://calendar.example.test/ended.ics")
		self.assertFalse(ended["ok"])
		self.assertIn("It ended on 24 May 2026", ended["message"])

	def test_what_can_go_wrong_is_told_in_words(self):
		self.assertEqual(self.ask("https://calendar.example.test/private.ics")["message"], "The server answered 401 (this calendar needs a sign-in, which Test does not send).")
		self.assertEqual(self.ask("https://calendar.example.test/page")["message"], "That is not a calendar file (a CalDAV address cannot be tested here).")
		self.assertEqual(self.ask("https://unknown.example.test/x.ics")["message"], "The host name could not be found.")
		self.assertEqual(self.ask(""), { "ok": False, "message": "Enter an address first." })

	def test_this_device_is_not_a_place_to_test(self):
		asked: list[httpx.Request] = []
		def handler(request: httpx.Request) -> httpx.Response:
			asked.append(request)
			return httpx.Response(200, content=fixture_text("calendar-family.ics").encode())
		for value in ("http://127.0.0.1/x.ics", "webcal://localhost/x.ics", "https://inside.example.test/x.ics", "http://169.254.169.254/latest"):
			with self.subTest(value):
				self.assertFalse(self.ask(value, httpx.MockTransport(handler))["ok"])
		self.assertEqual(asked, [])

	def test_the_countries_are_the_holiday_packages(self):
		resp = self.client.get("/api/datasource/calendar-sources/lookups/countries")
		self.assertEqual(resp.status_code, 200)
		countries = { c["value"]: c["name"] for c in resp.json() }
		self.assertEqual((countries["US"], countries["GB"]), ("United States", "United Kingdom"))
		self.assertTrue(all(len(code) == 2 for code in countries))

	def test_another_data_source_chooses_from_the_calendars_list(self):
		# the Reminder Overlay's `calendars` are the Calendar's: its lookup is read from the Calendar's settings (`from`), and a task is checked against them
		self.write_datasource_settings("calendar-sources", { "cacheHours": 0.25, "staleDays": 30, "calendars": [FAMILY], "holidays": [] })
		resp = self.client.get("/api/datasources/reminder-overlay/lookups/calendar")
		self.assertEqual((resp.status_code, resp.json()), (200, [{ "name": "Family", "value": "Family" }]))
		self.assertEqual(self.client.get("/api/datasources/reminder-overlay/lookups/nothing").status_code, 404)
		plugins = { p["info"]["id"]: p for p in self.cm.enum_plugins() }
		sources = { d["info"]["id"]: d for d in self.cm.enum_datasources() }
		def settings_of(owner: str, ident: str):
			return (self.cm.plugin_manager(ident) if owner == "plugin" else self.cm.datasource_manager(ident)).open().get()[1]
		content = { "dataSource": "reminder-overlay", "zone": "top-right", "windowMinutes": 60, "calendars": ["Family"] }
		self.assertEqual(plugin_content_errors(plugins, sources, "overlay", content, ["task"], settings_of), [])
		errors = plugin_content_errors(plugins, sources, "overlay", { **content, "calendars": ["Gone"] }, ["task"], settings_of)
		self.assertIn(["task", "content", "calendars", "0"], [e["path"] for e in errors])

	def test_the_settings_keep_a_row_password_and_check_the_rows(self):
		self.write_datasource_settings("calendar-sources", { "cacheHours": 0.25, "staleDays": 30, "calendars": [{ "name": "Private", "source": "ical", "url": "https://calendar.example.test/private.ics", "auth": "basic", "username": "user", "password": "pass" }], "holidays": [] })
		doc = self.client.get("/api/datasources/calendar-sources/settings").json()
		self.assertEqual(doc["calendars"][0]["password"], "********")
		doc["calendars"][0]["color"] = "blue"
		doc["holidays"] = [{ "name": "US", "country": "US" }, { "name": "US", "country": "GB" }]
		resp = self.client.put("/api/datasources/calendar-sources/settings", json=doc)
		self.assertEqual(resp.status_code, 422)
		self.assertEqual(resp.json()["errors"], [
			{ "path": ["calendars", "0", "color"], "message": "Enter a color like #3366cc" },
			{ "path": ["holidays", "1", "name"], "message": "Must be unique" },
		])
		doc["calendars"][0]["color"] = "#3366cc"
		doc["calendars"][0]["auth"] = "none"
		doc["holidays"] = [{ "name": "US", "country": "US" }]
		self.assertEqual(self.client.put("/api/datasources/calendar-sources/settings", json=doc).status_code, 200)
		_, stored = self.cm.datasource_manager("calendar-sources").open().get()
		self.assertEqual((stored["calendars"][0]["password"], stored["calendars"][0]["username"]), (None, None), "signing in turned off: the secret is not kept")

def kept_context(dscm: DatasourceConfigurationManager, now: datetime = NOW) -> DataSourceExecutionContext:
	root = ServiceContainer()
	root.add_service(DatasourceConfigurationManager, dscm)
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings()))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	# where the data sources' own folders are (their page templates): the source root
	root.add_service(ConfigurationManager, ConfigurationManager())
	return Context(root, (800, 480), now)

def calendar_settings(**more) -> DatasourceConfigurationManager:
	"""The data source's own folder in a private storage, its settings written (`cacheHours` as a test asks)."""
	folder = tempfile.mkdtemp(prefix="eink-calendar-test-")
	atexit.register(shutil.rmtree, folder, True)
	cm = ConfigurationManager(storage_path=folder)
	cm.hard_reset()
	save_datasource_settings(cm, "calendar-sources", { "cacheHours": 0.25, "staleDays": 30, "calendars": [FAMILY], "holidays": [], "accounts": [], **more })
	return cm.datasource_manager("calendar-sources")

class TestKept(unittest.IsolatedAsyncioTestCase):
	"""What a calendar answered is kept for the settings' `cacheHours`, shared by every page, task and overlay that shows its events."""
	def setUp(self):
		self.fake = FakeInternet()
		use_transport(self, self.fake)

	async def events(self, dscm, now=NOW, params=None, start=None, end=None):
		start = start or at(7)
		answer = await CalendarSources("calendar-sources", "Calendar Sources").open_async(kept_context(dscm, now), { **(params or {}), "start": start, "end": end or start + timedelta(days=3) })
		return answer.events

	async def test_a_second_read_in_the_time_asks_nobody_and_gives_the_same_events(self):
		dscm = calendar_settings()
		first = await self.events(dscm)
		again = await self.events(dscm, NOW + timedelta(minutes=10))
		self.assertEqual(len(self.fake.requests), 1)
		self.assertEqual(again, first)
		self.assertTrue(first and all(e.start.utcoffset() == ZONE.utcoffset(None) for e in again))
		await self.events(dscm, NOW + timedelta(minutes=20))
		self.assertEqual(len(self.fake.requests), 2, "the kept answer was older than a quarter of an hour")

	async def test_zero_asks_every_time_and_a_later_moment_in_the_same_days_shares_the_answer(self):
		dscm = calendar_settings(cacheHours=0)
		await self.events(dscm)
		await self.events(dscm)
		self.assertEqual(len(self.fake.requests), 2)
		dscm = calendar_settings()
		self.fake.requests.clear()
		await self.events(dscm, start=at(7, 9), end=at(10, 9))
		await self.events(dscm, start=at(7, 15), end=at(10, 9))
		self.assertEqual(len(self.fake.requests), 1, "the days are read whole: one answer serves any range inside them")

	async def test_the_pages_and_the_events_share_one_answer_and_a_failed_refresh_uses_the_old_one(self):
		dscm = calendar_settings()
		ds = CalendarPagesAsync("calendar", "Calendar")
		await ds.open_async(kept_context(dscm), { "views": ["agenda"] })
		self.assertEqual(len(self.fake.requests), 1)
		self.assertEqual(len(await self.events(dscm, start=at(7), end=at(14))), len(await self.events(dscm, start=at(7), end=at(14))))
		use_transport(self, httpx.MockTransport(lambda r: httpx.Response(503)))
		old = await ds.open_async(kept_context(dscm, NOW + timedelta(hours=1)), { "views": ["agenda"] })
		self.assertTrue(old[0].slot.events, "the origin did not answer: the kept answer is used")

	async def test_a_row_secret_is_not_kept(self):
		private = CALENDARS[4]
		dscm = calendar_settings(calendars=[private])
		await self.events(dscm)
		names = dscm.list_files("cache-")
		self.assertEqual(len(names), 1)
		self.assertNotIn("pass", json.dumps(dscm.file(names[0]).get()[1]))
