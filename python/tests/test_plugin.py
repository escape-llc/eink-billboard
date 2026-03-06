from datetime import datetime, timedelta
import queue
import threading
from time import sleep, time
import unittest

from ..model.time_of_day import TimeOfDay
from ..datasources.comic.comic_feed import ComicFeedAsync
from ..datasources.data_source import DataSource, DataSourceManager
from ..datasources.image_folder.image_folder import ImageFolderAsync
from ..datasources.newspaper.newspaper import NewspaperAsync
from ..datasources.openai_image.openai_image import OpenAIAsync
from ..datasources.wpotd.wpotd import WpotdAsync
from ..model.service_container import ServiceContainer
from ..model.schedule import PlaylistSchedule, PlaylistScheduleData
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..plugins.slide_show.slide_show import SlideShowAsync
from ..plugins.plugin_base import PluginExecutionContext
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..task.timer import IProvideTimer
from ..task.message_router import MessageRouter, Route
from ..task.messages import BasicMessage, QuitMessage
from ..task.protocols import MessageSink
from .utils import RecordingTask, ScaledTimeOfDay, ScaledTimerThreadService, create_configuration_manager, save_images

class DebugMessageSink(MessageSink):
	def __init__(self):
		self.msg_queue = queue.Queue()
	def accept(self, msg: BasicMessage):
		self.msg_queue.put(msg)

TICK_RATE_FAST = 0.05
TICK_RATE_SLOW = 1
TICKS = 60*1

class TestAsyncPlugins(unittest.TestCase):
	def run_slide_show(self, track:PlaylistSchedule, dsm: DataSourceManager, timeout=10, testCancel=False):
		plugin = SlideShowAsync("slide-show", "Slide Show Plugin")
		cm = create_configuration_manager()
		scm = cm.settings_manager()
		stm = cm.static_manager()
		display = RecordingTask("FakeDisplay")
		display.start()
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		time_of_day = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		timer = ScaledTimerThreadService(time_of_day, 60)
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		root.add_service(StaticConfigurationManager, stm)
		root.add_service(SettingsConfigurationManager, scm)
		root.add_service(DataSourceManager, dsm)
		root.add_service(MessageRouter, router)
		root.add_service(IProvideTimer, timer)
		root.add_service(TimeOfDay, time_of_day)
		context = PluginExecutionContext(root, (800,480), time_of_day.current_time())
		pool = AsyncHttpWorkerPool()
		pool.start()
		done = threading.Event()
		fut = pool.submit(plugin.task_async, context, track, done)
		if testCancel:
			sleep(2)
			fut.cancel()
		# SHOULD signal first
		sig = done.wait(timeout=timeout)
		self.assertTrue(sig, "Plugin did not complete within timeout")
		# SHOULD NOT have to wait
		if testCancel:
			self.assertTrue(fut.cancelled(), "Future was not cancelled")
		else:
			self.assertFalse(fut.cancelled(), "Future was cancelled unexpectedly")
			fut.result()
		pool.shutdown()
		display.accept(QuitMessage(time_of_day.current_time()))
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
		dsmap:dict[str,DataSource] = {"image-folder": ImageFolderAsync("image-folder", "image-folder")}
		datasources = DataSourceManager(dsmap)
		display = self.run_slide_show(track, datasources)
		self.assertEqual(len(display.msgs), 9, "display.msgs failed")
	def test_slide_show_with_comic(self):
		content = {
			"dataSource": "comic-feed",
			"comic": "XKCD",
			"slideMax": 0,
			"slideMinutes": 2
		}
		plugin_data = PlaylistScheduleData(content)
		track = PlaylistSchedule(
			plugin_name="slide-show",
			id="10",
			title="10 Item",
			content=plugin_data
		)
		dsmap:dict[str,DataSource] = {"comic-feed": ComicFeedAsync("comic-feed", "comic-feed")}
		datasources = DataSourceManager(dsmap)
		display = self.run_slide_show(track, datasources, 20)
		self.assertEqual(len(display.msgs), 4, "display.msgs failed")
	def test_slide_show_with_comic_cancel(self):
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
		dsmap:dict[str,DataSource] = {"comic-feed": ComicFeedAsync("comic-feed", "comic-feed")}
		datasources = DataSourceManager(dsmap)
		display = self.run_slide_show(track, datasources, 20, testCancel=True)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
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
		dsmap:dict[str,DataSource] = {"wpotd": WpotdAsync("wpotd", "wpotd")}
		datasources = DataSourceManager(dsmap)
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
		dsmap:dict[str,DataSource] = {"newspaper": NewspaperAsync("newspaper", "newspaper")}
		datasources = DataSourceManager(dsmap)
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
		dsmap:dict[str,DataSource] = {"openai-image": OpenAIAsync("openai-image", "openai-image")}
		datasources = DataSourceManager(dsmap)
		display = self.run_slide_show(track, datasources, 61)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
	pass

if __name__ == "__main__":
	unittest.main()