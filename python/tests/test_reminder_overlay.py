import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any, cast


from ..datasources.calendar.calendar import CalendarSources
from ..datasources.calendar_pages.calendar_pages import CalendarPagesAsync
from ..datasources.contracts.calendar import Event
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.overlay_text import lines_that_fit
from ..datasources.reminder_overlay.reminder_overlay import ReminderOverlayAsync, clock, event_lines, title_text, upcoming, when_text, window_minutes
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..model.theme import current_inputs
from ..plugins.plugin_base import PermanentError
from .fake_internet import FakeInternet
from .test_calendar import CALENDARS, NOW, FakeSettings, at
from .test_datasource_fixes import STATIC
from .test_theme import CHROME, HAVE_CHROME
from .utils import save_datasource_settings, save_image, test_output_path_for, use_transport

def event(start: datetime, minutes: int = 30, title: str = "Meeting", all_day: bool = False) -> Event:
	return Event(start, start + timedelta(minutes=minutes), all_day, title, "", "Family", None)

class TestWindow(unittest.TestCase):
	def test_what_is_on_now_or_starts_in_the_window_the_nearest_first(self):
		now = at(8, 9)
		events = [event(at(8, 9, 50), title="Later"), event(at(8, 8, 45), 30, "On now"), event(at(8, 8), 30, "Over"), event(at(8, 11), title="Beyond"),
			event(at(8), 24 * 60, "All day", True), event(at(8, 9, 20), title="Soon")]
		self.assertEqual([e.title for e in upcoming(events, now, 60, False)], ["On now", "Soon", "Later"])
		self.assertEqual([e.title for e in upcoming(events, now, 60, True)], ["All day", "On now", "Soon", "Later"])

	def test_the_window_is_a_whole_number_of_minutes_of_at_least_one(self):
		self.assertEqual([window_minutes({}), window_minutes({ "windowMinutes": 90 }), window_minutes({ "windowMinutes": 10 ** 9 })], [60, 90, 7 * 24 * 60])
		for bad in (0, -5, "x", True):
			with self.assertRaises(PermanentError):
				window_minutes({ "windowMinutes": bad })

class TestWords(unittest.TestCase):
	def test_the_time_is_in_the_devices_format(self):
		self.assertEqual([clock(at(8, 9, 5), False), clock(at(8, 0, 5), True), clock(at(8, 15, 30), True)], ["09:05", "12:05 AM", "3:30 PM"])

	def test_when_it_is(self):
		now = at(8, 9)
		self.assertEqual(when_text(event(at(8, 8, 45)), now, False), "Now")
		self.assertEqual(when_text(event(at(8, 9, 30)), now, False), "09:30")
		self.assertEqual(when_text(event(at(9, 9, 30)), now, True), "Fri 9:30 AM")
		self.assertEqual(when_text(event(at(8), 24 * 60, all_day=True), now, False), "Today")
		self.assertEqual(when_text(event(at(9), 24 * 60, all_day=True), now, False), "Fri")

	def test_a_long_title_is_cut_and_the_time_is_highlighted(self):
		self.assertEqual(len(title_text(event(at(8, 9), title="x" * 100))), 30)
		[line] = event_lines([event(at(8, 9, 30), title="Dentist")], at(8, 9), False)
		self.assertEqual(line, [("09:30", "text-secondary-1"), ("  Dentist", "text-primary")])

class Harness:
	"""A storage with the Calendar Sources' settings, and the context the Reminder Overlay gets: its own folder, with the calendar provider found by the DataSourceManager."""
	def __init__(self, test: unittest.TestCase, sources: dict|None = None, settings: dict|None = None):
		self.fake = FakeInternet()
		use_transport(test, self.fake)
		folder = tempfile.mkdtemp(prefix="eink-reminder-test-")
		test.addCleanup(shutil.rmtree, folder, True)
		self.cm = ConfigurationManager(storage_path=folder)
		self.cm.hard_reset()
		save_datasource_settings(self.cm, "calendar", { "cacheHours": 0.25, "staleDays": 30, "calendars": CALENDARS, "holidays": [], "accounts": [], **(settings or {}) })
		self.calendar = CalendarSources("calendar", "Calendar Sources")
		self.sources = { "calendar": self.calendar } if sources is None else sources

	def context(self, now=NOW, own="reminder-overlay") -> DataSourceExecutionContext:
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(own))
		root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings()))
		root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
		root.add_service(DataSourceManager, DataSourceManager(self.sources))
		return DataSourceExecutionContext(root, (246, 96), now)

	def asked(self) -> int:
		return len(self.fake.requests)

BEFORE_DENTIST = at(8, 9)

class TestAsksTheCalendar(unittest.IsolatedAsyncioTestCase):
	async def test_it_lists_what_is_in_the_window_from_the_calendars_own_list(self):
		h = Harness(self)
		overlay = ReminderOverlayAsync("reminder-overlay", "Reminder Overlay")
		state = await overlay.open_async(h.context(BEFORE_DENTIST), { "calendars": ["Family"], "windowMinutes": 60 })
		self.assertEqual([e.title for e in state], ["Dentist"])
		self.assertEqual(await overlay.open_async(h.context(NOW), { "calendars": ["Family"], "windowMinutes": 60 }), [], "nothing in the window")
		# it keeps nothing of its own
		self.assertEqual(h.cm.datasource_manager("reminder-overlay").list_files("cache-"), [])

	async def test_the_overlay_and_the_calendars_pages_share_one_read(self):
		h = Harness(self)
		await CalendarPagesAsync("calendar-pages", "Calendar").open_async(h.context(BEFORE_DENTIST, own="calendar-pages"), { "views": ["agenda"], "calendars": ["Family"] })
		first = h.asked()
		overlay = ReminderOverlayAsync("reminder-overlay", "Reminder Overlay")
		await overlay.open_async(h.context(BEFORE_DENTIST + timedelta(minutes=5)), { "calendars": ["Family"], "windowMinutes": 60 })
		await overlay.open_async(h.context(BEFORE_DENTIST + timedelta(minutes=10)), { "calendars": ["Family"], "windowMinutes": 30 })
		self.assertEqual(h.asked(), first, "the overlay's runs asked nobody: the calendar provider kept its answer")

	async def test_without_the_calendar_it_says_so(self):
		h = Harness(self, sources={})
		with self.assertRaisesRegex(PermanentError, "No calendar provider is installed"):
			await ReminderOverlayAsync("reminder-overlay", "Reminder Overlay").open_async(h.context(), {})

	async def test_no_calendars_is_nothing_to_show(self):
		h = Harness(self, settings={ "calendars": [] })
		self.assertEqual(await ReminderOverlayAsync("reminder-overlay", "Reminder Overlay").open_async(h.context(BEFORE_DENTIST), {}), [])

	async def test_anything_but_its_state_or_an_empty_list_is_nothing_to_show(self):
		h = Harness(self)
		overlay = ReminderOverlayAsync("reminder-overlay", "Reminder Overlay")
		self.assertIsNone(await overlay.render_async(h.context(), {}, "not a state"))
		self.assertIsNone(await overlay.render_async(h.context(), {}, []))

class TestFit(unittest.TestCase):
	def test_as_many_lines_as_the_zone_has_room_for(self):
		stm = StaticConfigurationManager(STATIC)
		theme = current_inputs(cast(Any, FakeSettings()))
		texts = [f"{9 + n}:00  Meeting number {n}" for n in range(8)]
		count = lines_that_fit(stm, theme, (246, 96), texts, 1.0)
		self.assertTrue(1 <= count < 8, count)
		self.assertEqual(lines_that_fit(stm, theme, (246, 96), texts[:1], 1.0), 1)
		self.assertEqual(lines_that_fit(stm, theme, (246, 96), [], 1.0), 0)
		self.assertGreaterEqual(lines_that_fit(stm, theme, (800, 400), texts, 1.0), count)

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRender(unittest.IsolatedAsyncioTestCase):
	async def test_the_events_are_outlined_text_on_a_transparent_zone(self):
		h = Harness(self)
		overlay = ReminderOverlayAsync("reminder-overlay", "Reminder Overlay")
		params = { "calendars": ["Family"], "windowMinutes": 3000, "zone": "top-left" }
		dsec = h.context(BEFORE_DENTIST)
		result = await overlay.render_async(dsec, params, await overlay.open_async(dsec, params))
		assert result is not None
		save_image(result.image, test_output_path_for("reminder_overlay_tests"), 0, "events")
		self.assertEqual((result.image.size, result.image.mode), ((246, 96), "RGBA"))
		self.assertEqual([result.image.getpixel(c)[3] for c in ((0, 95), (245, 95))], [0, 0])
		self.assertIn("Dentist", result.title or "")

if __name__ == "__main__":
	unittest.main()
