import asyncio
import os
import threading
import unittest
from datetime import date, datetime, timezone
from typing import Any, cast

from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.overlay_text import OUTLINE_WIDTH, fit_line, outline_factor
from ..datasources.today.today import TodayAsync, date_parts
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import TimerTaskItem, TimerTaskTask, TriggerDict
from ..model.service_container import ServiceContainer
from ..model.theme import inputs_from
from ..plugins.overlay.overlay import OverlayAsync
from ..plugins.plugin_base import PermanentError, PluginExecutionContext
from ..task.display_messages import OverlayImage, OverlayZones
from ..task.message_router import MessageRouter
from ..task.overlay_zones import zones_for
from .test_theme import CHROME, HAVE_CHROME
from .test_timer_layer import at
from .utils import save_image, test_output_path_for

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
THEME = { "preset": "classic" }
DAY = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)

class FakeSettings:
	def __init__(self, theme=None):
		self.theme = theme if theme is not None else THEME
	def open(self, name):
		return self
	def get(self):
		return ("rev", self.theme)

def provider(theme=None) -> ServiceContainer:
	container = ServiceContainer()
	container.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	container.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(theme)))
	return container

class TestDateParts(unittest.TestCase):
	def test_presets(self):
		day = date(2026, 10, 9)
		self.assertEqual(date_parts(day, "long"), ("Friday", ", October 9"))
		self.assertEqual(date_parts(day, "full"), ("Friday", ", October 9, 2026"))
		self.assertEqual(date_parts(day, "short"), ("Fri", ", Oct 9"))
		self.assertEqual(date_parts(day, "numeric"), ("", "2026-10-09"))
		# no zero padding in the presets
		self.assertEqual(date_parts(date(2026, 3, 1), "long"), ("Sunday", ", March 1"))

	def test_custom(self):
		self.assertEqual(date_parts(date(2026, 10, 9), "custom", "%d/%m/%Y"), ("", "09/10/2026"))

	def test_a_missing_or_empty_custom_pattern_is_a_permanent_error(self):
		for pattern in (None, "", "   "):
			with self.subTest(pattern=pattern), self.assertRaises(PermanentError):
				date_parts(date(2026, 10, 9), "custom", pattern)

	def test_a_pattern_strftime_refuses_is_a_permanent_error(self):
		# Windows refuses unknown directives; Linux prints them, so refuse deterministically here
		class Refusing(date):
			def strftime(self, fmt):
				raise ValueError("Invalid format string")
		with self.assertRaises(PermanentError):
			date_parts(Refusing(2026, 10, 9), "custom", "%Q")

	def test_an_unknown_format_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			date_parts(date(2026, 10, 9), "weekly")

class TestFitLine(unittest.TestCase):
	"""The size and the baseline are chosen in Python, with the font file Chromium draws with (the page cannot run a script to fit the text)."""
	def _font(self, family="Jost"):
		stm = StaticConfigurationManager(STATIC)
		return lambda px: stm.get_font(family, px, "bold")

	def test_the_line_and_its_outline_fit_the_box(self):
		for family in ("Jost", "League Spartan", "Dogica", "DSEG7"):
			with self.subTest(family=family):
				font = self._font(family)
				placed = fit_line("Friday, October 9, 2026", (200, 40), font, 1.0, False)
				left, top, right, bottom = font(placed.font_px).getbbox("Friday, October 9, 2026", anchor="ls")
				self.assertLessEqual(right - left + placed.outline_px, 200)
				self.assertLessEqual(bottom - top + placed.outline_px, 40)

	def test_the_outline_is_a_factor_of_the_text_size(self):
		full = fit_line("Fri", (246, 96), self._font(), 1.0, False)
		half = fit_line("Fri", (246, 96), self._font(), 0.5, False)
		self.assertAlmostEqual(full.outline_px, full.font_px * OUTLINE_WIDTH)
		self.assertAlmostEqual(half.outline_px, half.font_px * OUTLINE_WIDTH * 0.5)
		self.assertEqual(fit_line("Fri", (246, 96), self._font(), 0.0, False).outline_px, 0)
		self.assertGreater(fit_line("Fri", (246, 96), self._font(), 1.0, True).heavy_px, 0)

	def test_the_outline_setting_of_a_task(self):
		# a task from before the setting: the full outline
		self.assertEqual(outline_factor({}), 1.0)
		self.assertEqual(outline_factor({ "outline": 0 }), 0.0)
		self.assertEqual(outline_factor({ "outline": 0.3 }), 0.3)
		self.assertEqual(outline_factor({ "outline": 7 }), 1.0)
		self.assertEqual(outline_factor({ "outline": True }), 1.0)

	def test_an_unknown_weight_is_a_permanent_error(self):
		dsec = DataSourceExecutionContext(provider(), (246, 96), DAY)
		with self.assertRaises(PermanentError):
			asyncio.run(TodayAsync("today", "Today").render_async(dsec, { "format": "long", "weight": "black" }, {}))

def _ink(image) -> tuple[int, int, int, int]:
	box = image.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
	assert box is not None
	return box

def _solid(image) -> set[tuple[int, int, int]]:
	return { px[:3] for px in image.getdata() if px[3] == 255 }

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRender(unittest.TestCase):
	def _render(self, params, size=(246, 96), theme=None):
		dsec = DataSourceExecutionContext(provider(theme), size, DAY)
		result = asyncio.run(TodayAsync("today", "Today").render_async(dsec, params, {}))
		assert result is not None
		return result

	def test_the_text_sits_near_the_screens_edge_not_in_the_middle_of_the_band(self):
		def ink(params):
			return _ink(self._render({ "format": "short", **params }).image)
		# the outline is counted, so it is not cut at the screen's edge (Chromium and PIL may place the ink a pixel apart)
		self.assertAlmostEqual(ink({ "zone": "top-left", "offset": 6 })[1], 6, delta=2)
		self.assertAlmostEqual(96 - ink({ "zone": "bottom-right", "offset": 6 })[3], 6, delta=2)
		# the offset moves it, in a top zone down from the edge and in a bottom zone up from it
		self.assertAlmostEqual(ink({ "zone": "top-center", "offset": 20 })[1], 20, delta=2)
		self.assertAlmostEqual(96 - ink({ "zone": "bottom-center", "offset": 20 })[3], 20, delta=2)
		# no zone (a data source used elsewhere): centered
		middle = ink({})
		self.assertLess(abs((middle[1] + middle[3]) / 2 - 48), 4)

	def test_the_date_is_outlined_text_in_the_theme_colors_on_a_transparent_page(self):
		result = self._render({ "format": "long" })
		image = result.image
		save_image(image, test_output_path_for("today_tests"), 1, "outlined")
		self.assertEqual((result.title, image.size, image.mode), ("Friday, October 9", (246, 96), "RGBA"))
		self.assertEqual([image.getpixel(corner)[3] for corner in ((0, 0), (245, 0), (0, 95), (245, 95))], [0, 0, 0, 0])
		palette = inputs_from(THEME, "spectra6").palette
		solid = _solid(image)
		# the letters in their roles, and the outline in the theme's outline color (white on a white page)
		self.assertTrue({ palette.rgb("text_secondary_1"), palette.rgb("text_primary"), palette.rgb("text_outline") } <= solid, solid)
		self.assertEqual(palette.rgb("text_outline"), (255, 255, 255))
		# the highlight (the weekday) comes first: the leftmost letter pixel is the highlight's
		box = _ink(image)
		letters = (palette.rgb("text_secondary_1"), palette.rgb("text_primary"))
		first = next(image.getpixel((x, y))[:3] for x in range(box[0], box[2]) for y in range(box[1], box[3]) if image.getpixel((x, y))[3] == 255 and image.getpixel((x, y))[:3] in letters)
		self.assertEqual(first, palette.rgb("text_secondary_1"))

	def test_a_black_page_outlines_in_black(self):
		solid = _solid(self._render({ "format": "numeric" }, theme={ **THEME, "background": "black" }).image)
		# the outline is the page's black, the letters its swapped inks: white for the main text, yellow for the highlight
		self.assertIn((0, 0, 0), solid)
		self.assertTrue({ (255, 255, 255), (255, 255, 0) } & solid, solid)

	def test_an_outline_of_0_draws_only_the_letters(self):
		primary = inputs_from(THEME, "spectra6").palette.rgb("text_primary")
		self.assertEqual(_solid(self._render({ "format": "numeric", "outline": 0 }).image), { primary })
		self.assertIn((255, 255, 255), _solid(self._render({ "format": "numeric", "outline": 1 }).image))

	def test_the_theme_chooses_the_font_and_the_text_fits_the_zone(self):
		pages = set()
		for family in ("Jost", "League Spartan", "Dogica", "DSEG7"):
			with self.subTest(font=family):
				image = self._render({ "format": "full" }, size=(150, 40), theme={ **THEME, "fontOverlay": family }).image
				box = _ink(image)
				self.assertTrue(box[0] >= 0 and box[2] <= 150 and box[3] <= 40, box)
				pages.add(image.tobytes())
		self.assertEqual(len(pages), 4)

	def test_heavy_is_bolder(self):
		def letters(weight):
			return sum(1 for px in self._render({ "format": "numeric", "outline": 0, "weight": weight }).image.getdata() if px[3] == 255)
		self.assertGreater(letters("heavy"), letters("bold"))

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestTodayOverlay(unittest.TestCase):
	def test_the_overlay_plugin_puts_today_in_its_zone(self):
		sent: list = []
		container = provider()
		container.add_service(ConfigurationManager, cast(Any, type("CM", (), { "datasource_manager": lambda self, name: object() })()))
		today = TodayAsync("today", "Today")
		container.add_service(DataSourceManager, cast(Any, type("DSM", (), { "get_source": lambda self, name: today if name == "today" else None })()))
		router = MessageRouter()
		router.send = lambda route, msg: sent.append(msg)  # type: ignore
		container.add_service(MessageRouter, router)
		container.add_service(OverlayZones, OverlayZones([z.definition() for z in zones_for((800, 480), "landscape")]))
		item = TimerTaskItem("today-task", "Today", True, TimerTaskTask("overlay", { "dataSource": "today", "zone": "top-right", "outline": 1, "format": "short" }), cast(TriggerDict, at(0, 0)))
		asyncio.run(OverlayAsync("overlay", "Overlay").task_async(PluginExecutionContext(container, (800, 480), DAY), item, threading.Event()))
		[msg] = sent
		self.assertIsInstance(msg, OverlayImage)
		self.assertEqual((msg.key, msg.zone, msg.title, msg.img.size), ("today-task", "top-right", "Fri, Oct 9", (246, 96)))

if __name__ == "__main__":
	unittest.main()
