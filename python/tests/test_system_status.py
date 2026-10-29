"""
The System Status data source (#651): the Device card's Machine readings as a page, with a word on a reading that is too high.
"""
import shutil
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from ..datasources.data_source import DataSourceExecutionContext
from ..datasources.system_status import system_status as module
from ..datasources.system_status.system_status import Row, SystemStatusAsync, chosen_readings, format_bytes, format_uptime, status_rows
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..plugins.plugin_base import PermanentError
from ..utils.image_utils import chrome_command
from .test_datasource_fixes import STATIC, FakeRenderSession, _Cob
from .utils import storage_path, test_output_path_for

HOST = { "os": "Linux", "os_release": "6.12", "machine": "aarch64", "cpus": 4, "uptime_seconds": 3 * 86400 + 4 * 3600 + 5, "app_uptime_seconds": 600 }
LOAD = { "cpu_percent": 12.4, "memory": { "total": 4 * 1024 ** 3, "used": 1024 ** 3, "percent": 25.0 } }
PI = { "model": "Raspberry Pi 5 Model B", "temperature_c": 51.2, "throttled_now": False }
VOLUME = { "total": 32 * 1024 ** 3, "used": 8 * 1024 ** 3, "free": 24 * 1024 ** 3, "percent": 25.0 }
ALL = ["system", "processor", "memory", "disk", "temperature", "uptime"]

def rows_by_label(rows: list[Row]) -> dict[str, Row]:
	return { r.label: r for r in rows }

class TestRows(unittest.TestCase):
	def test_readings_come_in_page_order_and_none_is_all(self):
		self.assertEqual(chosen_readings({}), ALL)
		self.assertEqual(chosen_readings({ "readings": [] }), ALL)
		self.assertEqual(chosen_readings({ "readings": ["uptime", "disk"] }), ["disk", "uptime"])
		with self.assertRaises(PermanentError):
			chosen_readings({ "readings": ["fan"] })

	def test_sizes_and_spans_read_like_the_system_page(self):
		self.assertEqual(format_bytes(512), "512 B")
		self.assertEqual(format_bytes(1536), "1.5 KB")
		self.assertEqual(format_bytes(24 * 1024 ** 3), "24.0 GB")
		self.assertEqual(format_uptime(3 * 86400 + 4 * 3600), "3 days 4 h")
		self.assertEqual(format_uptime(86400), "1 day 0 h")
		self.assertEqual(format_uptime(2 * 3600 + 5 * 60), "2 h 5 min")
		self.assertEqual(format_uptime(90), "1 min")
		self.assertEqual(format_uptime(5), "5 s")

	def test_a_pi_gives_every_row(self):
		rows = rows_by_label(status_rows(ALL, HOST, LOAD, PI, VOLUME, {}))
		self.assertEqual(list(rows), ["Board", "System", "Processor", "Memory", "Disk", "Temperature", "Machine up", "App running"])
		self.assertEqual(rows["Processor"].value, "4 cores, 12% busy")
		self.assertEqual(rows["Memory"].value, "1.0 GB of 4.0 GB")
		self.assertEqual(rows["Disk"].value, "24.0 GB free of 32.0 GB")
		self.assertEqual(rows["Temperature"].value, "51.2 °C")
		self.assertEqual({ r.warning for r in rows.values() }, { "" })

	def test_what_the_machine_cannot_give_is_left_out(self):
		rows = status_rows(ALL, { "os": "Windows", "os_release": "11", "machine": "AMD64", "cpus": 1 }, {}, None, None, {})
		self.assertEqual([r.label for r in rows], ["System", "Processor"])
		self.assertEqual(rows[1].value, "1 core")
		self.assertIsNone(rows[1].percent)

	def test_a_reading_that_is_too_high_gets_a_word(self):
		hot = status_rows(["temperature"], HOST, LOAD, { **PI, "temperature_c": 71.0 }, VOLUME, {})
		self.assertEqual(hot[0].warning, "High")
		self.assertEqual(status_rows(["temperature"], HOST, LOAD, { **PI, "temperature_c": 71.0 }, VOLUME, { "temperatureLimit": 75 })[0].warning, "")
		# the limit itself counts
		self.assertEqual(status_rows(["temperature"], HOST, LOAD, { **PI, "temperature_c": 70.0 }, VOLUME, {})[0].warning, "High")
		full = { **VOLUME, "used": 30 * 1024 ** 3, "free": 2 * 1024 ** 3, "percent": 93.8 }
		self.assertEqual(status_rows(["disk"], HOST, LOAD, PI, full, {})[0].warning, "Low space")
		self.assertEqual(status_rows(["disk"], HOST, LOAD, PI, full, { "diskWarnPercent": 95 })[0].warning, "")
		self.assertEqual(status_rows(["disk"], HOST, LOAD, PI, VOLUME, {})[0].warning, "")

	def test_the_firmwares_warning_outranks_a_temperature_over_the_limit(self):
		row = status_rows(["temperature"], HOST, LOAD, { **PI, "temperature_c": 82.0, "throttled_now": True }, VOLUME, {})[0]
		self.assertEqual(row.warning, "Throttled")

	def test_no_host_name_address_user_or_path_is_in_a_row(self):
		text = " ".join(f"{r.label} {r.value} {r.warning}" for r in status_rows(ALL, HOST, LOAD, PI, VOLUME, {}))
		for secret in ("/", "\\", "@", "localhost", ".local"):
			self.assertNotIn(secret, text)

class FakeSettings:
	def __init__(self, orientation: str = "landscape"):
		self.docs = { "display": { "orientation": orientation }, "system": {}, "theme": { "theme": "analogous", "hue": 200, "saturation": 60, "lightness": 50 } }
	def open(self, name: str):
		return _Cob(self.docs.get(name))

def make_context(orientation: str = "landscape", dimensions=(800, 480)) -> DataSourceExecutionContext:
	from datetime import datetime, timezone
	root = ServiceContainer()
	root.add_service(ConfigurationManager, ConfigurationManager(storage_path=storage_path()))
	root.add_service(SettingsConfigurationManager, cast(Any, FakeSettings(orientation)))
	root.add_service(StaticConfigurationManager, StaticConfigurationManager(STATIC))
	return DataSourceExecutionContext(root, dimensions, datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc))

class TestPage(unittest.IsolatedAsyncioTestCase):
	async def test_an_unknown_reading_is_a_permanent_error(self):
		with self.assertRaises(PermanentError):
			await SystemStatusAsync("system-status", "System Status").open_async(make_context(), { "readings": ["fan"] })

	async def test_the_page_is_drawn_at_the_target_size_from_the_rows(self):
		ds = SystemStatusAsync("system-status", "System Status")
		with patch.object(module, "RenderSession", FakeRenderSession), patch.object(module, "pi_info", return_value=PI):
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				result = await ds.render_async(make_context(orientation), { "readings": ["system", "disk"], "title": "My Pi" }, await ds.open_async(make_context(orientation), {}))
				assert result is not None and FakeRenderSession.last is not None
				self.assertEqual(result.image.size, size)
				self.assertEqual(result.title, "My Pi")
				self.assertEqual(FakeRenderSession.last.params["heading"], "My Pi")
				self.assertEqual([r["label"] for r in FakeRenderSession.last.params["rows"]], ["Board", "System", "Disk"])

CHROME = chrome_command()

@unittest.skipUnless(shutil.which(CHROME) is not None, f"needs {CHROME} on PATH (see AGENTS.md, Test environment)")
class TestRealPage(unittest.IsolatedAsyncioTestCase):
	"""The page as Chromium draws it. The images are in .test-output/system_status for a look."""
	async def test_the_page_is_drawn_with_and_without_warnings(self):
		folder = Path(test_output_path_for("system_status"))
		ds = SystemStatusAsync("system-status", "System Status")
		full = { **VOLUME, "used": 30 * 1024 ** 3, "free": 2 * 1024 ** 3, "percent": 93.8 }
		cases = (("fine", PI, VOLUME), ("alarms", { **PI, "temperature_c": 74.5 }, full), ("not-a-pi", None, VOLUME))
		for name, pi, volume in cases:
			for orientation, size in (("landscape", (800, 480)), ("portrait", (480, 800))):
				with self.subTest(case=name, orientation=orientation):
					with patch.object(module, "pi_info", return_value=pi), patch.object(module, "host_info", return_value=HOST), patch.object(module, "load_info", return_value=dict(LOAD)), \
						patch.object(ConfigurationManager, "disk_volume", return_value=volume):
						result = await ds.render_async(make_context(orientation, size[::-1] if orientation == "portrait" else size), {}, {})
					assert result is not None
					self.assertEqual(result.image.size, size)
					result.image.save(folder.joinpath(f"{name}-{orientation}.png"))
					self.assertGreater(len(result.image.convert("L").getcolors(maxcolors=256) or []), 1, "the page is not blank")

if __name__ == "__main__":
	unittest.main()
