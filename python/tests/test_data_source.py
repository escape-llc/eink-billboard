from datetime import datetime
from typing import cast
import unittest

from ..datasources.countdown.countdown import CountdownAsync
from ..datasources.year_progress.year_progress import YearProgressAsync
from ..datasources.clock.clock import ClockAsync
from ..datasources.openai_image.openai_image import OpenAIAsync
from ..datasources.comic.comic_feed import ComicFeedAsync
from ..datasources.data_source import DataSourceExecutionContext, MediaItemAsync, MediaListAsync, MediaRenderAsync
from ..datasources.wpotd.wpotd import WpotdAsync
from ..datasources.image_folder.image_folder import ImageFolderAsync
from ..datasources.newspaper.newspaper import NewspaperAsync
from ..model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from .utils import create_configuration_manager, save_image, test_output_path_for

def create_data_source_context(dsid:str, schedule_ts: datetime = datetime.now()) -> DataSourceExecutionContext:
	cm = create_configuration_manager()
	cm.ensure_folders()
	scm = cm.settings_manager()
	stm = cm.static_manager()
	dscm = cm.datasource_manager(dsid)
	root = ServiceContainer()
	#root.add_service(ConfigurationManager, cm)
	root.add_service(StaticConfigurationManager, stm)
	root.add_service(SettingsConfigurationManager, scm)
	root.add_service(DatasourceConfigurationManager, dscm)
	resolution = (800,480)
	return DataSourceExecutionContext(root, resolution, schedule_ts)

class TestAsyncDataSources(unittest.TestCase):
	def setUp(self):
		self.pool = AsyncHttpWorkerPool()
		self.pool.start()

	def tearDown(self):
		try:
			self.pool.shutdown()
		except Exception:
			pass

	async def run_datasource_async(self, ds, params, image_size, image_count):
		self.assertIsInstance(ds, MediaListAsync)
		self.assertIsInstance(ds, MediaRenderAsync)
		folder = test_output_path_for(f"ds-{ds.id}-async")
		dsec = create_data_source_context(ds.id)
		state:list = await cast(MediaListAsync, ds).open_async(dsec, params)
		self.assertTrue(len(state) > 0)
		images = []
		ix = 0
		while len(state) > 0:
			item = state[0]
			state.pop(0)
			result = await cast(MediaRenderAsync, ds).render_async(dsec, params, item)
			if result is None:
				self.assertIsNotNone(result)
			else:
				images.append(result)
				save_image(result.image, folder, ix, f"item_{ix}")
			ix += 1
		self.assertEqual(len(images), image_count)
	async def run_datasource2_async(self, ds, params, image_size, image_count):
		self.assertIsInstance(ds, MediaItemAsync)
		self.assertIsInstance(ds, MediaRenderAsync)
		folder = test_output_path_for(f"ds-{ds.id}-async")
		dsec = create_data_source_context(ds.id)
		state = await cast(MediaItemAsync, ds).open_async(dsec, params)
		self.assertIsNotNone(state)
		images = []
		ix = 0
		item = state
		result = await cast(MediaRenderAsync, ds).render_async(dsec, params, item)
		if result is None:
			self.assertIsNotNone(result)
		else:
			images.append(result)
			save_image(result.image, folder, ix, f"item_{ix}")
		self.assertEqual(len(images), image_count)
	def test_image_folder(self):
		ds = ImageFolderAsync("image-folder", "image-folder")
		params = {
			"folder": "python/tests/images"
		}
		self.pool.submit(self.run_datasource_async, ds, params, (800, 480), 9).result(timeout=60)
	def test_comic_feed(self):
		ds = ComicFeedAsync("comic-feed", "comic-feed")
		params = {
			"comic": "XKCD",
			"titleCaption": True,
			"fontSize": 12
		}
		self.pool.submit(self.run_datasource_async, ds, params, (800, 480), 4).result(timeout=60)
	def test_newspaper(self):
		ds = NewspaperAsync("newspaper", "newspaper")
		params = {
			"slug": "ny_nyt"
		}
		self.pool.submit(self.run_datasource_async, ds, params, (700, 1166), 1).result(timeout=60)
	def test_wikipedia(self):
		ds = WpotdAsync("wpotd", "wpotd")
		params = {
			"shrinkToFit": True
		}
		self.pool.submit(self.run_datasource_async, ds, params, (800,480), 1).result(timeout=60)
	@unittest.skip("OpenAI Image tests cost money!")
	def test_openai(self):
		ds = OpenAIAsync("openai-image", "openai-image")
		params = {
			"prompt": "an electronic ink billboard in a futuristic setting",
			"imageModel": "dall-e-3",
		}
		self.pool.submit(self.run_datasource_async, ds, params, (1024,1792), 1).result(timeout=60)
	def test_clock_gradient(self):
		ds = ClockAsync("clock-gradient", "clock")
		params = {
			"clockFace": "Gradient Clock",
			"primaryColor": "#db3246",
			"secondaryColor": "#000000"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800, 480), 1).result(timeout=60)
	def test_clock_digital(self):
		ds = ClockAsync("clock-digital", "clock")
		params = {
			"clockFace": "Digital Clock",
			"primaryColor": "#ffffff",
			"secondaryColor": "#000000"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800,480), 1).result(timeout=60)
	def test_clock_word(self):
		ds = ClockAsync("clock-word", "clock")
		params = {
			"clockFace": "Word Clock",
			"primaryColor": "#000000",
			"secondaryColor": "#ffffff"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800,480), 1).result(timeout=60)
	def test_clock_divided(self):
		ds = ClockAsync("clock-divided", "clock")
		params = {
			"clockFace": "Divided Clock",
			"primaryColor": "#20b7ae",
			"secondaryColor": "#ffffff"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800,480), 1).result(timeout=60)
	def test_countdown(self):
		ds = CountdownAsync("countdown", "countdown")
		params = {
			"targetDate": "2027-01-01",
			"title": "New Year Countdown"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800,480), 1).result(timeout=60)
	def test_year_progress(self):
		ds = YearProgressAsync("year-progress", "year-progress")
		params = {
			"title": "New Year Countdown"
		}
		self.pool.submit(self.run_datasource2_async, ds, params, (800,480), 1).result(timeout=60)

if __name__ == "__main__":
	unittest.main()