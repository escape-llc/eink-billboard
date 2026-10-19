import json
import os
import threading
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image

from ..display import waveshare_display
from ..display.waveshare_display import MODELS, WaveshareDisplay, load_model, model_names, split_for_bi_color
from ..plugins.plugin_base import PermanentError
from .utils import temp_configuration_manager

def settings_of(settings: dict|None = None) -> Any:
	cm = MagicMock()
	cm.settings_manager.return_value.open.return_value.get.return_value = ("rev", settings or {})
	return cm

class FakePanel:
	"""A one-buffer panel (the usual driver): `getbuffer` and `display(image)`."""
	def __init__(self, width=800, height=480):
		self.width, self.height = width, height
		self.calls: list[tuple] = []
	def init(self):
		self.calls.append(("init",))
	def getbuffer(self, image):
		return ("buffer", image.size, image.mode)
	def display(self, image):
		self.calls.append(("display", image))
	def sleep(self):
		self.calls.append(("sleep",))

class FakeBiColorPanel(FakePanel):
	"""A black-white-red panel: `display(black, red)`; and the old spelling `Init`."""
	def __init__(self):
		super().__init__(400, 300)
	init = None  # type: ignore[assignment]
	def Init(self):
		self.calls.append(("Init",))
	def display(self, imageblack, imagered):
		self.calls.append(("display", imageblack, imagered))

def module_of(panel: Any) -> Any:
	return SimpleNamespace(EPD=lambda: panel, epdconfig=SimpleNamespace(module_exit=MagicMock()))

def display_with(panel: Any, refresh_seconds: float = 5.0, settings: dict|None = None) -> WaveshareDisplay:
	shown = WaveshareDisplay("waveshare", loader=lambda model: module_of(panel), refresh_seconds=refresh_seconds)
	shown.initialize(settings_of({ "waveshare-model": "epd7in3e", **(settings or {}) }))
	return shown

class TestModels(unittest.TestCase):
	def test_the_models_are_the_vendored_files_and_the_settings_offer_exactly_those(self):
		self.assertGreater(len(MODELS), 50)
		self.assertIn("epd7in3e", MODELS)
		self.assertNotIn("epdconfig", MODELS)
		self.assertEqual(MODELS, model_names())
		with open(os.path.join(os.path.dirname(waveshare_display.__file__), "..", "storage", "schemas", "display.json"), encoding="utf-8") as f:
			schema = json.load(f)
		offered = [item["value"] for item in schema["schema"]["lookups"]["waveshareModel"]["items"]]
		self.assertEqual(offered, list(MODELS), "the Display settings' list is the vendored drivers: update the schema (and VENDORED.md) with them")
		model = next(p for p in schema["schema"]["properties"] if p["name"] == "waveshare-model")
		self.assertEqual((model["lookup"], model["visibleIf"]), ("waveshareModel", { "field": "display_type", "const": "waveshare" }))

	def test_every_driver_has_what_the_display_calls(self):
		"""Read, not imported (they need a Raspberry Pi): a class EPD with a start and a display of one or two buffers."""
		import ast
		for model in MODELS:
			with open(os.path.join(waveshare_display.EPD_FOLDER, model + ".py"), encoding="utf-8", errors="replace") as f:
				tree = ast.parse(f.read())
			epd = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EPD"), None)
			with self.subTest(model=model):
				assert epd is not None
				methods = { m.name: m for m in epd.body if isinstance(m, ast.FunctionDef) }
				self.assertTrue("init" in methods or "Init" in methods)
				display = methods.get("display") or methods.get("display_1Gray")
				assert display is not None
				self.assertIn(len(display.args.args) - 1, (1, 2))
				self.assertIn("getbuffer", methods)

class TestLoading(unittest.TestCase):
	def test_no_model_or_one_that_is_not_ours_is_told_what_to_choose(self):
		for model, words in ((None, "Choose the Waveshare display's model"), ("", "Choose the Waveshare display's model"), ("epd7in3e; rm", "not one of the Waveshare models"), ("../x", "not one of the Waveshare models")):
			with self.subTest(model=model), self.assertRaisesRegex(PermanentError, words):
				load_model(model)

	def test_a_machine_without_the_libraries_or_without_the_board_is_worded(self):
		with patch("importlib.import_module", side_effect=ImportError("No module named 'spidev'")), self.assertRaisesRegex(PermanentError, "needs the device libraries.*mock or tk"):
			load_model("epd7in3e")
		with patch("importlib.import_module", side_effect=RuntimeError("Cannot find sysfs_software_spi.so")), self.assertRaisesRegex(PermanentError, "made for a Raspberry Pi and found none"):
			load_model("epd7in3e")

	def test_the_module_comes_from_our_list_not_the_settings_text(self):
		with patch("importlib.import_module") as imported:
			load_model("epd7in3e")
		self.assertEqual(imported.call_args.args[0], "python.display.waveshare_epd.epd7in3e")

class TestDriver(unittest.TestCase):
	def test_the_resolution_is_the_panels_and_a_picture_is_started_drawn_and_put_to_sleep(self):
		panel = FakePanel()
		shown = display_with(panel)
		self.assertEqual(shown.resolution, (800, 480))
		panel.calls.clear()
		shown.render(Image.new("RGB", (800, 480), "red"), 1, "a page")
		self.assertEqual([c[0] for c in panel.calls], ["init", "display", "sleep"])
		self.assertEqual(panel.calls[1][1], ("buffer", (800, 480), "RGB"))

	def test_a_three_color_panel_is_given_the_black_and_the_red_layer(self):
		panel = FakeBiColorPanel()
		shown = display_with(panel)
		panel.calls.clear()
		image = Image.new("RGB", (400, 300), "white")
		image.paste((255, 0, 0), (0, 0, 200, 150))
		image.paste((0, 0, 0), (200, 150, 400, 300))
		shown.render(image, 1)
		kind, black, red = panel.calls[1]
		self.assertEqual((panel.calls[0][0], kind, panel.calls[2][0]), ("Init", "display", "sleep"))
		self.assertEqual((black[0], red[0]), ("buffer", "buffer"))
		layers = split_for_bi_color(image)
		self.assertEqual([layer.getpixel(point) for layer, point in ((layers[0], (300, 200)), (layers[0], (50, 50)), (layers[1], (50, 50)), (layers[1], (300, 200)))], [0, 1, 0, 1])

	def test_an_image_of_another_size_is_fitted_not_refused(self):
		panel = FakePanel()
		shown = display_with(panel)
		with self.assertLogs(waveshare_display.__name__, level="WARNING"):
			shown.render(Image.new("RGBA", (400, 240), (255, 0, 0, 0)), 1)
		self.assertEqual(panel.calls[-2][1][1], (800, 480))

	def test_a_driver_that_fails_is_worded_at_start_and_reported_at_draw(self):
		class Broken(FakePanel):
			def init(self):
				raise OSError("spi")
		with self.assertRaisesRegex(PermanentError, "could not be started.*SPI is enabled"):
			display_with(Broken())
		panel = FakePanel()
		shown = display_with(panel)
		panel.display = MagicMock(side_effect=OSError("write failed"))  # type: ignore[method-assign]
		with self.assertRaisesRegex(OSError, "write failed"):
			shown.render(Image.new("RGB", (800, 480)), 1)

	def test_a_panel_that_never_says_it_is_done_is_a_timeout_and_nothing_more_is_sent(self):
		release = threading.Event()
		class Stuck(FakePanel):
			def display(self, image):
				release.wait(5)
		self.addCleanup(release.set)
		# no rest between refreshes here: it is the guard that refuses the second one (the rest is tested in test_refresh_gate)
		shown = display_with(Stuck(), refresh_seconds=0.1, settings={ "refreshInterval": 0 })
		with self.assertRaisesRegex(RuntimeError, "did not finish refreshing"):
			shown.render(Image.new("RGB", (800, 480)), 1)
		with self.assertRaisesRegex(RuntimeError, "has not finished the last refresh"):
			shown.render(Image.new("RGB", (800, 480)), 2)
		release.set()

	def test_a_panel_that_never_answers_when_it_is_started_is_worded_not_waited_for(self):
		release = threading.Event()
		class Silent(FakePanel):
			def init(self):
				release.wait(5)
		self.addCleanup(release.set)
		shown = WaveshareDisplay("waveshare", loader=lambda model: module_of(Silent()), refresh_seconds=0.1, start_seconds=0.1)
		with self.assertRaisesRegex(PermanentError, "did not answer when it was started.*busy line"):
			shown.initialize(settings_of({ "waveshare-model": "epd7in3e" }))
		release.set()

	def test_before_and_after_the_display_exists_is_an_error_and_shutdown_releases_the_bus(self):
		shown = WaveshareDisplay("waveshare", loader=lambda model: module_of(FakePanel()))
		with self.assertRaises(RuntimeError):
			shown.render(Image.new("RGB", (8, 8)), 1)
		panel = FakePanel()
		shown = display_with(panel)
		module = shown.module
		shown.shutdown()
		module.epdconfig.module_exit.assert_called_once()
		with self.assertRaises(RuntimeError):
			shown.render(Image.new("RGB", (800, 480)), 1)

class TestDisplayTask(unittest.TestCase):
	def test_the_status_says_which_model_to_choose(self):
		from datetime import datetime, timezone
		from ..model.service_container import ServiceContainer
		from ..task.configure_event import ConfigureEvent, ConfigureNotify, ConfigureOptions
		from ..task.display import Display
		from ..task.message_router import MessageRouter
		from ..task.telemetry_hub import TelemetryHub
		cm = temp_configuration_manager(self)
		cob = cm.settings_manager().open("display")
		rev, doc = cob.get()
		assert doc is not None
		cob.save(rev, { **doc, "display_type": "waveshare" })
		notes: list[ConfigureNotify] = []
		sink = MagicMock()
		sink.accept.side_effect = notes.append
		now = datetime(2026, 10, 14, tzinfo=timezone.utc)
		Display("Display", MessageRouter())._configure_event(ConfigureEvent(now, ConfigureOptions(cm=cm, isp=ServiceContainer()), "display", sink))  # type: ignore[arg-type]
		[note] = notes
		self.assertTrue(note.error)
		hub = TelemetryHub()
		hub.accept(note)
		self.assertIn("Choose the Waveshare display's model", hub.status()["components"]["display"]["message"])

if __name__ == "__main__":
	unittest.main()
