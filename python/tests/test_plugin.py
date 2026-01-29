from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import queue
import threading
import unittest
import logging

from ..model.time_of_day import TimeOfDay
from ..datasources.comic.comic_feed import ComicFeed
from ..datasources.data_source import DataSourceManager
from ..datasources.image_folder.image_folder import ImageFolder
from ..datasources.newspaper.newspaper import Newspaper
from ..datasources.openai_image.openai_image import OpenAI
from ..datasources.wpotd.wpotd import Wpotd
from ..model.service_container import ServiceContainer
from ..plugins.slide_show.slide_show import SlideShow
from ..task.playlist_layer import NextTrack
from ..task.timer import IProvideTimer
from .utils import RecordingTask, ScaledTimeOfDay, ScaledTimerService, create_configuration_manager, save_images
from ..model.schedule import PlaylistSchedule, PlaylistScheduleData
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..plugins.plugin_base import BasicExecutionContext2, PluginProtocol
from ..task.future_source import FutureSource, SubmitFuture
from ..task.message_router import MessageRouter, Route
from ..task.messages import BasicMessage, MessageSink, QuitMessage

logging.basicConfig(
	level=logging.DEBUG,  # Or DEBUG for more detail
	format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

class DebugMessageSink(MessageSink):
	def __init__(self):
		self.msg_queue = queue.Queue()
	def accept(self, msg: BasicMessage):
		self.msg_queue.put(msg)

class PluginRecycleMessageSink(MessageSink):
	def __init__(self, plugin: PluginProtocol, track, context: BasicExecutionContext2):
		self.msg_queue = queue.Queue()
		self.plugin = plugin
		self.track = track
		self.context = context
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)
	def accept(self, msg: BasicMessage):
		self.logger.debug(f"PluginRecycleMessageSink: {msg}")
		if isinstance(msg, NextTrack):
			self.logger.info("PluginRecycleMessageSink: received NextTrack, stopping")
			self.stopped.set()
		else:
			self.plugin.receive(self.context, self.track, msg)

TICK_RATE_FAST = 0.05
TICK_RATE_SLOW = 1
TICKS = 60*1

class TestPlugins(unittest.TestCase):
	def run_slide_show(self, track:PlaylistSchedule, dsm: DataSourceManager, timeout=10):
		plugin = SlideShow("slide-show", "Slide Show Plugin")
		cm = create_configuration_manager()
		plugin.cm = cm
		scm = cm.settings_manager()
		stm = cm.static_manager()
		display = RecordingTask("FakeDisplay")
		display.start()
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		time_of_day = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		timer = ScaledTimerService(60, ThreadPoolExecutor())
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		root.add_service(StaticConfigurationManager, stm)
		root.add_service(SettingsConfigurationManager, scm)
		root.add_service(DataSourceManager, dsm)
		root.add_service(MessageRouter, router)
		root.add_service(IProvideTimer, timer)
		root.add_service(TimeOfDay, time_of_day)
		context = BasicExecutionContext2(root, [800,480], datetime.now())
		sink = PluginRecycleMessageSink(plugin, track, context)
		root.add_service(MessageSink, sink)
		fsource = FutureSource("plugin_test", sink, ThreadPoolExecutor())
		root.add_service(SubmitFuture, fsource)
		plugin.start(context, track)
		completed = sink.stopped.wait(timeout=timeout)
		fsource.shutdown()
		timer.shutdown()
		display.accept(QuitMessage(datetime.now()))
		display.join()
		save_images(display, plugin.name)
		return display
	def test_slide_show_with_image_folder(self):
		content = {
			"dataSource": "image-folder",
			"folder": "python/tests/images",
			"slideMax": 0,
			"slideMinutes": 1
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap = {"image-folder": ImageFolder("image-folder", "image-folder")}
		datasources = DataSourceManager(None, dsmap)
		display = self.run_slide_show(track, datasources)
		self.assertEqual(len(display.msgs), 9, "display.msgs failed")
	def test_slide_show_with_comic(self):
		content = {
			"dataSource": "comic-feed",
			"comic": "XKCD",
			"slideMax": 0,
			"slideMinutes": 3
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap = {"comic-feed": ComicFeed("comic-feed", "comic-feed")}
		datasources = DataSourceManager(None, dsmap)
		display = self.run_slide_show(track, datasources, 20)
		self.assertEqual(len(display.msgs), 4, "display.msgs failed")
	def test_slide_show_with_wpotd(self):
		content = {
			"dataSource": "wpotd",
			"slideMax": 0,
			"slideMinutes": 3
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap = {"wpotd": Wpotd("wpotd", "wpotd")}
		datasources = DataSourceManager(None, dsmap)
		display = self.run_slide_show(track, datasources, 5)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
	def test_slide_show_with_newspaper(self):
		content = {
			"dataSource": "newspaper",
			"slug": "ny_nyt",
			"slideMax": 0,
			"slideMinutes": 3
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap = {"newspaper": Newspaper("newspaper", "newspaper")}
		datasources = DataSourceManager(None, dsmap)
		display = self.run_slide_show(track, datasources, 5)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
	@unittest.skip("OpenAI Image tests cost money!")
	def test_slide_show_with_openai(self):
		content = {
			"dataSource": "openai-image",
			"prompt": "A futuristic electronic inky display showing a slideshow of images in a modern home, digital art",
			"slideMax": 0,
			"slideMinutes": 5,
			"timeoutSeconds": 60
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap = {"openai-image": OpenAI("openai-image", "openai-image")}
		datasources = DataSourceManager(None, dsmap)
		display = self.run_slide_show(track, datasources, 61)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")

if __name__ == "__main__":
	unittest.main()