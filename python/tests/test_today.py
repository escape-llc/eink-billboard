import asyncio
import os
import threading
import unittest
from datetime import date, datetime, timezone
from typing import Any, cast

from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.today.today import TodayAsync, date_parts
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import TimerTaskItem, TimerTaskTask, TriggerDict
from ..model.service_container import ServiceContainer
from ..model.theme import inputs_from, palette_of
from ..plugins.overlay.overlay import OverlayAsync
from ..plugins.plugin_base import PermanentError, PluginExecutionContext
from ..task.display_messages import OverlayImage, OverlayZones
from ..task.message_router import MessageRouter
from ..task.overlay_zones import zones_for
from .test_timer_layer import at

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
THEME = { "theme": "split-complementary", "hue": 210, "saturation": 80, "lightness": 50 }
DAY = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)

class FakeSettings:
	def open(self, name):
		return self
	def get(self):
		return ("rev", THEME)

def provider() -> ServiceContainer:
	container = ServiceContainer()
	container.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	container.add_service(SettingsConfigurationManager, cast(Any, FakeSettings()))
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

class TestRender(unittest.TestCase):
	def _render(self, params, size=(246, 96)):
		dsec = DataSourceExecutionContext(provider(), size, DAY)
		return asyncio.run(TodayAsync("today", "Today").render_async(dsec, params, {}))

	def test_the_date_is_drawn_in_the_theme_colors_on_a_transparent_box(self):
		result = self._render({ "format": "long", "font": "Jost" })
		self.assertIsNotNone(result)
		assert result is not None
		image = result.image
		self.assertEqual((result.title, image.size, image.mode), ("Friday, October 9", (246, 96), "RGBA"))
		self.assertEqual(image.getpixel((0, 0))[3], 0)
		palette = palette_of(inputs_from(THEME))
		highlight, primary = palette.text_secondary_1.rgb, palette.text_primary.rgb
		solid = [image.getpixel((x, y)) for x in range(image.width) for y in range(image.height)]
		solid = [px[:3] for px in solid if px[3] == 255]
		self.assertIn(highlight, solid)
		self.assertIn(primary, solid)
		self.assertEqual(set(solid), { highlight, primary })
		# the highlight (the weekday) comes first
		bbox = image.getchannel("A").getbbox()
		assert bbox is not None
		first = next(image.getpixel((x, y))[:3] for x in range(bbox[0], bbox[2]) for y in range(bbox[1], bbox[3]) if image.getpixel((x, y))[3] == 255)
		self.assertEqual(first, highlight)

	def test_numeric_is_all_primary(self):
		result = self._render({ "format": "numeric", "font": "Jost" })
		assert result is not None
		solid = { px[:3] for px in (result.image.getpixel((x, y)) for x in range(246) for y in range(96)) if px[3] == 255 }
		self.assertEqual(solid, { palette_of(inputs_from(THEME)).text_primary.rgb })

	def test_the_text_fits_the_zone(self):
		for name in ("Jost", "Napoli", "Dogica", "DS-Digital"):
			with self.subTest(font=name):
				result = self._render({ "format": "full", "font": name }, size=(150, 40))
				assert result is not None
				bbox = result.image.getchannel("A").getbbox()
				assert bbox is not None
				self.assertTrue(bbox[0] >= 0 and bbox[2] <= 150 and bbox[3] <= 40, bbox)

	def test_an_unknown_font_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			self._render({ "format": "long", "font": "Comic Sans" })

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
		item = TimerTaskItem("today-task", "Today", True, TimerTaskTask("overlay", { "dataSource": "today", "zone": "top-right", "wash": 0.4, "format": "short", "font": "Jost" }), cast(TriggerDict, at(0, 0)))
		asyncio.run(OverlayAsync("overlay", "Overlay").task_async(PluginExecutionContext(container, (800, 480), DAY), item, threading.Event()))
		[msg] = sent
		self.assertIsInstance(msg, OverlayImage)
		self.assertEqual((msg.key, msg.zone, msg.title, msg.img.size, msg.wash), ("today-task", "top-right", "Fri, Oct 9", (246, 96), 0.4))

if __name__ == "__main__":
	unittest.main()
