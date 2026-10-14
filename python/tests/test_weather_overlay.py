import shutil
import tempfile
import unittest
from datetime import timedelta
from typing import Any, cast

import httpx

from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.overlay_text import fit_block
from ..datasources.weather.weather import WeatherAsync
from ..datasources.weather_overlay.weather_overlay import WeatherOverlayAsync, chosen_view, needs_of, view_lines
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..model.theme import inputs_from, palette_of
from ..plugins.plugin_base import PermanentError
from ..task.async_http_worker_pool import client_var
from .fake_internet import FakeInternet
from .test_theme import CHROME, HAVE_CHROME
from .test_weather import KEY, NOW, STATIC, FakeSettings, report
from .utils import save_datasource_settings, save_image, test_output_path_for

class TestViews(unittest.TestCase):
	def test_a_view_is_one_of_three_and_unset_is_now(self):
		self.assertEqual([chosen_view({}), chosen_view({ "view": "today" }), chosen_view({ "view": "outlook" })], ["now", "today", "outlook"])
		with self.assertRaises(PermanentError):
			chosen_view({ "view": "radar" })

	def test_each_view_asks_only_for_the_answer_it_shows(self):
		self.assertEqual([needs_of("now"), needs_of("today"), needs_of("outlook")], [{ "current" }, { "forecast" }, { "forecast" }])

	def test_now_is_the_temperature_highlighted_then_the_sky(self):
		lines, icon, title = view_lines("now", report())
		self.assertEqual(len(lines), 1)
		(temp, temp_role), (sky, sky_role) = lines[0]
		self.assertRegex(temp, r"^-?\d+°$")
		self.assertEqual((temp_role, sky_role), ("text-secondary-1", "text-primary"))
		self.assertTrue(sky.strip()[0].isupper())
		self.assertIsNotNone(icon)
		self.assertEqual(title, temp + sky)

	def test_today_is_the_range_and_the_chance_of_rain(self):
		lines, icon, _ = view_lines("today", report())
		text = "".join(t for t, _ in lines[0])
		self.assertRegex(text, r"^-?\d+° / -?\d+°  \d+%$")
		self.assertIsNotNone(icon)

	def test_the_outlook_is_three_days_a_line_each_starting_today(self):
		lines, icon, _ = view_lines("outlook", report())
		self.assertEqual(len(lines), 3)
		self.assertEqual(lines[0][0], ("Today", "text-secondary-1"))
		self.assertEqual([line[0][0] for line in lines[1:]], ["Thu", "Fri"])
		self.assertIsNone(icon)

	def test_a_report_without_what_the_view_needs_is_an_error(self):
		empty = report()
		empty.current, empty.days = None, []
		for view in ("now", "today", "outlook"):
			with self.subTest(view=view), self.assertRaises(RuntimeError):
				view_lines(view, empty)

class TestFitBlock(unittest.TestCase):
	def _font(self):
		stm = StaticConfigurationManager(STATIC)
		return lambda px: stm.get_font("Jost", px, "bold")

	def test_the_lines_and_the_icon_fit_the_zone(self):
		block = fit_block(["Today 19° / 10°", "Thu 19° / 8°", "Fri 18° / 6°"], (246, 96), self._font(), 1.0, False, "top", 6)
		self.assertEqual(len(block.lines), 3)
		# one size, one start, the lines a line apart
		self.assertEqual(len({ round(line.x - block.lines[0].x) for line in block.lines }), 1)
		self.assertGreater(block.lines[1].baseline, block.lines[0].baseline)
		with_icon = fit_block(["14° Scattered clouds"], (246, 96), self._font(), 1.0, False, "top", 6, icon=True)
		assert with_icon.icon_box is not None
		x, y, side = with_icon.icon_box
		self.assertGreaterEqual(x, 0)
		self.assertGreaterEqual(y, 6)
		# the text starts after the drawing
		self.assertGreater(with_icon.lines[0].x, x + side)

class Harness:
	"""A storage with the Weather's settings, and the context the Weather Overlay gets (its own folder; the Weather found by the DataSourceManager)."""
	def __init__(self, test: unittest.TestCase, sources: dict|None = None, settings: dict|None = None):
		self.fake = FakeInternet()
		client_var.set(httpx.AsyncClient(transport=self.fake))
		folder = tempfile.mkdtemp(prefix="eink-weather-overlay-test-")
		test.addCleanup(shutil.rmtree, folder, True)
		self.cm = ConfigurationManager(storage_path=folder)
		self.cm.hard_reset()
		save_datasource_settings(self.cm, "weather", { "apiKey": KEY, "units": "auto", "cacheHours": 6, **(settings or {}) })
		self.weather = WeatherAsync("weather", "Weather")
		self.sources = { "weather": self.weather } if sources is None else sources

	def context(self, now=NOW, own="weather-overlay") -> DataSourceExecutionContext:
		root = ServiceContainer()
		root.add_service(ConfigurationManager, self.cm)
		root.add_service(DatasourceConfigurationManager, self.cm.datasource_manager(own))
		root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings()))
		root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
		root.add_service(DataSourceManager, DataSourceManager(self.sources))
		return DataSourceExecutionContext(root, (246, 96), now)

	def asked(self) -> list[str]:
		return [r.url.path.rsplit("/", 1)[-1] for r in self.fake.requests]

class TestAsksTheWeather(unittest.IsolatedAsyncioTestCase):
	async def test_the_overlay_and_the_weathers_pages_share_one_call(self):
		h = Harness(self)
		await h.weather.open_async(h.context(own="weather"), { "views": ["current", "days"] })
		overlay = WeatherOverlayAsync("weather-overlay", "Weather Overlay")
		for view in ("now", "today", "outlook"):
			await overlay.open_async(h.context(NOW + timedelta(hours=1)), { "view": view })
		self.assertEqual(sorted(h.asked()), ["forecast", "weather"])
		# it keeps nothing of its own
		self.assertEqual(h.cm.datasource_manager("weather-overlay").list_files("cache-"), [])

	async def test_without_the_weather_it_says_so(self):
		h = Harness(self, sources={})
		with self.assertRaisesRegex(PermanentError, "Weather data source is not available"):
			await WeatherOverlayAsync("weather-overlay", "Weather Overlay").open_async(h.context(), { "view": "now" })

	async def test_the_weathers_settings_problems_are_its(self):
		h = Harness(self, settings={ "apiKey": None })
		with self.assertRaisesRegex(PermanentError, "Weather settings"):
			await WeatherOverlayAsync("weather-overlay", "Weather Overlay").open_async(h.context(), { "view": "now" })

	async def test_anything_but_its_state_is_nothing_to_show(self):
		h = Harness(self)
		self.assertIsNone(await WeatherOverlayAsync("weather-overlay", "Weather Overlay").render_async(h.context(), {}, "not a state"))

@unittest.skipUnless(HAVE_CHROME, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRender(unittest.IsolatedAsyncioTestCase):
	async def _render(self, params):
		h = Harness(self)
		overlay = WeatherOverlayAsync("weather-overlay", "Weather Overlay")
		dsec = h.context()
		result = await overlay.render_async(dsec, params, await overlay.open_async(dsec, params))
		assert result is not None
		return result.image

	def _solid(self, image) -> set[tuple[int, int, int]]:
		return { px[:3] for px in image.getdata() if px[3] == 255 }

	def _has(self, solid: set[tuple[int, int, int]], color: tuple[int, int, int]) -> bool:
		"""Chromium and Python round a derived color a step apart at most (test_theme)."""
		return any(all(abs(a - b) <= 1 for a, b in zip(px, color)) for px in solid)

	async def test_each_view_is_outlined_text_on_a_transparent_zone(self):
		palette = palette_of(inputs_from(FakeSettings.THEME))
		for n, view in enumerate(("now", "today", "outlook")):
			with self.subTest(view=view):
				image = await self._render({ "view": view, "zone": "top-left" })
				save_image(image, test_output_path_for("weather_overlay_tests"), n, view)
				self.assertEqual((image.size, image.mode), ((246, 96), "RGBA"))
				self.assertEqual([image.getpixel(c)[3] for c in ((0, 95), (245, 95))], [0, 0])
				solid = self._solid(image)
				for role in ("text_secondary_1", "text_primary", "text_outline"):
					self.assertTrue(self._has(solid, getattr(palette, role).rgb), role)

	async def test_the_icon_is_drawn_in_its_color_unless_turned_off(self):
		icon = palette_of(inputs_from(FakeSettings.THEME)).text_secondary_2.rgb
		self.assertTrue(self._has(self._solid(await self._render({ "view": "now" })), icon))
		self.assertFalse(self._has(self._solid(await self._render({ "view": "now", "showIcon": False })), icon))

if __name__ == "__main__":
	unittest.main()
