from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import queue
import threading
import unittest
import time
import logging

from ..datasources.comic.comic_feed import ComicFeed
from ..datasources.data_source import DataSourceManager
from ..datasources.image_folder.image_folder import ImageFolder
from ..datasources.newspaper.newspaper import Newspaper
from ..datasources.openai_image.openai_image import OpenAI
from ..datasources.wpotd.wpotd import Wpotd
from ..model.service_container import ServiceContainer
from ..plugins.slide_show.slide_show import SlideShow
from ..task.playlist_layer import NextTrack
from ..task.timer import TimerService
from ..tests.utils import create_configuration_manager, save_image, save_images, test_output_path_for
from ..model.schedule import Playlist, PlaylistSchedule, PlaylistScheduleData, PluginSchedule, PluginScheduleData
from ..model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..plugins.plugin_base import BasicExecutionContext2, PluginBase, PluginExecutionContext, PluginProtocol
from ..task.active_plugin import ActivePlugin
from ..task.display import DisplayImage
from ..task.future_source import FutureSource, SubmitFuture
from ..task.message_router import MessageRouter, Route
from ..task.messages import BasicMessage, MessageSink, QuitMessage
from ..task.basic_task import DispatcherTask
from ..task.timer_tick import TickMessage

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

class RecordingTask(DispatcherTask):
	def __init__(self, name):
		super().__init__(name)
		self.msgs = []
		self.logger = logging.getLogger(__name__)

	def _basic_message(self, msg: BasicMessage):
		self.logger.debug(f"{self.name}: {msg}")
		self.msgs.append(msg)

TICK_RATE_FAST = 0.05
TICK_RATE_SLOW = 1
TICKS = 60*1

class TestPlugins(unittest.TestCase):
	def create_timer_task(self, now, count=10):
		nowx = now.replace(minute=0, second=0, microsecond=0)
		eventlist = [TickMessage(nowx + timedelta(minutes=ix), ix) for ix in range(count)];
		return eventlist

	def run_plugin_schedule(self, item:PluginSchedule, tick_rate = TICK_RATE_FAST):
		eventlist = self.create_timer_task(datetime.now(), TICKS)
		cm = create_configuration_manager()
		plugin_info = cm.enum_plugins()
		plugins = cm.load_plugins(plugin_info)
		plugin:PluginBase = plugins[item.plugin_name]
		self.assertIsNotNone(plugin, "plugin failed")
		psm = cm.plugin_manager(item.plugin_name)
		scm = cm.settings_manager()
		stm = cm.static_manager()
		resolution = [800,480]
		sink = DebugMessageSink()
		display = RecordingTask("FakeDisplay")
		display.start()
		router = MessageRouter()
		router.addRoute(Route("display", [display]))
		active_plugin = ActivePlugin(item.plugin_name, sink)
		resolution = [800,480]
		for event in eventlist:
			ctx = PluginExecutionContext(item, stm, scm, psm, active_plugin, resolution, event.tick_ts, router)
			if event.tick_number == 0:
				plugin.timeslot_start(ctx)
				if active_plugin.state == "ready":
					plugin.schedule(ctx)
			elif event.tick_number == TICKS - 1:
				plugin.timeslot_end(ctx)
			else:
				active_plugin.check_alarm_clock(event.tick_ts)
				if active_plugin.state == "ready":
					plugin.schedule(ctx)
			time.sleep(tick_rate)
			try:
				sinkmsg = sink.msg_queue.get_nowait()
				# dispatch callback
				active_plugin.state = "notify"
				plugin.receive(ctx, sinkmsg)
				active_plugin.notify_complete()
			except queue.Empty as e:
				pass
		active_plugin.shutdown()
		display.accept(QuitMessage())
		display.join()
		return display

	@unittest.skip("Countdown test skipped needs refactor")
	def test_countdown(self):
		content = {
			"theme": "traidic",
			"theme-h": 210,
			"theme-s": "70%",
			"theme-l": "50%",
			"frame": "Rectangle",
			"title": "Project Deadline",
			"targetDate": "2029-01-20"
		}
		plugin_data = PluginScheduleData(content)
		item = PluginSchedule(
			plugin_name="countdown",
			id="10",
			title="10 Item",
			start_minutes=600,
			duration_minutes=10,
			content=plugin_data
		)
		display = self.run_plugin_schedule(item)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
		save_images(display, item.plugin_name)

	@unittest.skip("Year Progress test skipped needs refactor")
	def test_year_progress(self):
		content = {
			"theme": "split-complementary",
			"theme-h": 130,
			"theme-s": "70%",
			"theme-l": "50%",
			"frame": "Rectangle",
		}
		plugin_data = PluginScheduleData(content)
		item = PluginSchedule(
			plugin_name="year_progress",
			id="10",
			title="10 Item",
			start_minutes=600,
			duration_minutes=10,
			content=plugin_data
		)
		display = self.run_plugin_schedule(item)
		self.assertEqual(len(display.msgs), 1, "display.msgs failed")
		save_images(display, item.plugin_name)

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
		timer = TimerService()
		root = ServiceContainer()
		root.add_service(ConfigurationManager, cm)
		root.add_service(StaticConfigurationManager, stm)
		root.add_service(SettingsConfigurationManager, scm)
		root.add_service(DataSourceManager, dsm)
		root.add_service(MessageRouter, router)
		root.add_service(TimerService, timer)
		context = BasicExecutionContext2(root, [800,480], datetime.now())
		sink = PluginRecycleMessageSink(plugin, track, context)
		root.add_service(MessageSink, sink)
		fsource = FutureSource("plugin_test", sink, ThreadPoolExecutor())
		root.add_service(SubmitFuture, fsource)
		plugin.start(context, track)
		completed = sink.stopped.wait(timeout=timeout)
		fsource.shutdown()
		timer.shutdown()
		display.accept(QuitMessage())
		display.join()
		save_images(display, plugin.name)
		return display
	def test_slide_show_with_image_folder(self):
		content = {
			"dataSource": "image-folder",
			"folder": "python/tests/images",
			"slideMax": 0,
			"slideMinutes": 1/60
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
			"slideMinutes": 3/60
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
			"slideMinutes": 3/60
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
			"slideMinutes": 3/60
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
			"slideMinutes": 1/60,
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