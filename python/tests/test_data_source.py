from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import unittest
import logging

from python.datasources.countdown.countdown import Countdown
from python.datasources.year_progress.year_progress import YearProgress

from ..datasources.clock.clock import Clock
from ..datasources.openai_image.openai_image import OpenAI
from ..datasources.comic.comic_feed import ComicFeed
from ..datasources.data_source import DataSourceExecutionContext, DataSourceManager
from ..datasources.wpotd.wpotd import Wpotd
from ..datasources.image_folder.image_folder import ImageFolder
from ..datasources.newspaper.newspaper import Newspaper
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from .utils import create_configuration_manager, save_image, test_output_path_for

logging.basicConfig(
	level=logging.DEBUG,  # Or DEBUG for more detail
	format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

class TestDataSources(unittest.TestCase):
	def create_data_source_context(self, dsid:str, schedule_ts: datetime = datetime.now()) -> DataSourceExecutionContext:
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

	def run_datasource(self, ds, params, image_size, image_count, timeout = 5):
		tpe = ThreadPoolExecutor(max_workers=2)
		ds.set_executor(tpe)
		try:
			folder = test_output_path_for(f"ds-{ds.id}")
			dsec = self.create_data_source_context(ds.id)
			future_state = ds.open(dsec, params)
			state = future_state.result(timeout=5)
			self.assertTrue(len(state) > 0)
			images = []
			ix = 0
			while len(state) > 0:
				item = state[0]
				state.pop(0)
				future_img = ds.render(dsec, params, item)
				result = future_img.result(timeout=timeout)
				if result is None:
					break
				images.append(result)
				save_image(result, folder, ix, f"item_{ix}")
				ix += 1
				self.assertEqual(result.size, image_size)
			self.assertEqual(len(images), image_count)
		finally:
			ds.set_executor(None)
			tpe.shutdown(wait=True, cancel_futures=True)
	def run_datasource2(self, ds, params, image_size, image_count, timeout = 5):
		tpe = ThreadPoolExecutor(max_workers=2)
		ds.set_executor(tpe)
		try:
			folder = test_output_path_for(f"ds-{ds.id}")
			dsec = self.create_data_source_context(ds.id)
			future_state = ds.open(dsec, params)
			state = future_state.result(timeout=5)
			self.assertIsNotNone(state)
			images = []
			ix = 0
			item = state
			future_img = ds.render(dsec, params, item)
			result = future_img.result(timeout=timeout)
			self.assertIsNotNone(result)
			images.append(result)
			save_image(result, folder, ix, f"item_{ix}")
			self.assertEqual(result.size, image_size)
			self.assertEqual(len(images), image_count)
		finally:
			ds.set_executor(None)
			tpe.shutdown(wait=True, cancel_futures=True)
	def test_image_folder(self):
		ds = ImageFolder("image-folder", "image-folder")
		params = {
			"folder": "python/tests/images"
		}
		self.run_datasource(ds, params, (800, 480), 9)
	def test_comic_feed(self):
		ds = ComicFeed("comic-feed", "comic-feed")
		params = {
			"comic": "XKCD",
			"titleCaption": True,
			"fontSize": 12
		}
		self.run_datasource(ds, params, (800, 480), 4)
	def test_wikipedia(self):
		ds = Wpotd("wpotd", "wpotd")
		params = {
			"shrinkToFit": True
		}
		self.run_datasource(ds, params, (800, 480), 1)
	def test_newspaper(self):
		ds = Newspaper("newspaper", "newspaper")
		params = {
			"slug": "ny_nyt"
		}
		self.run_datasource(ds, params, (700, 1166), 1)
	def test_clock_gradient(self):
		ds = Clock("clock-gradient", "clock")
		params = {
			"clockFace": "Gradient Clock",
			"primaryColor": "#db3246",
			"secondaryColor": "#000000"
		}
		self.run_datasource2(ds, params, (800, 480), 1)
	def test_clock_digital(self):
		ds = Clock("clock-digital", "clock")
		params = {
			"clockFace": "Digital Clock",
			"primaryColor": "#ffffff",
			"secondaryColor": "#000000"
		}
		self.run_datasource2(ds, params, (800, 480), 1)
	def test_clock_word(self):
		ds = Clock("clock-word", "clock")
		params = {
			"clockFace": "Word Clock",
			"primaryColor": "#000000",
			"secondaryColor": "#ffffff"
		}
		self.run_datasource2(ds, params, (800, 480), 1)
	def test_clock_divided(self):
		ds = Clock("clock-divided", "clock")
		params = {
			"clockFace": "Divided Clock",
			"primaryColor": "#20b7ae",
			"secondaryColor": "#ffffff"
		}
		self.run_datasource2(ds, params, (800, 480), 1)
	def test_countdown(self):
		ds = Countdown("countdown", "countdown")
		params = {
			"targetDate": "2027-01-01",
			"title": "New Year Countdown"
		}
		self.run_datasource2(ds, params, (800, 480), 1)
	def test_year_progress(self):
		ds = YearProgress("year-progress", "year-progress")
		params = {
			"title": "New Year Countdown"
		}
		self.run_datasource2(ds, params, (800, 480), 1)

	@unittest.skip("OpenAI Image tests cost money!")
	def test_openai(self):
		ds = OpenAI("openai-image", "openai-image")
		params = {
			"prompt": "an electronic ink billboard in a futuristic setting",
			"imageModel": "dall-e-3",
		}
		self.run_datasource(ds, params, (1024, 1792), 1, timeout=60)
	def test_datasource_manager(self):
		sources = {
			"image-folder": ImageFolder("image-folder", "image-folder"),
			"comic-feed": ComicFeed("comic-feed", "comic-feed"),
			"wpotd": Wpotd("wpotd", "wpotd"),
			"newspaper": Newspaper("newspaper", "newspaper")
		}
		dsm = ds_mgr = None
		try:
			dsm = ds_mgr = DataSourceManager(None, sources)
			for name, ds in sources.items():
				retrieved = dsm.get_source(name)
				self.assertIsNotNone(retrieved)
				self.assertEqual(retrieved.name, ds.name)
			nonexistent = dsm.get_source("nonexistent-source")
			self.assertIsNone(nonexistent)
		finally:
			if dsm is not None:
				dsm.shutdown()

	def test_image_folder_raises_without_executor(self):
		dsec = self.create_data_source_context("image-folder")
		ds = ImageFolder("image-folder", "image-folder")
		params = {"folder": "python/tests/images"}
		with self.assertRaises(RuntimeError):
			ds.open(dsec, params)
		with self.assertRaises(RuntimeError):
			ds.render(dsec, params, None)

	def test_comic_feed_raises_without_executor(self):
		dsec = self.create_data_source_context("comic-feed")
		ds = ComicFeed("comic-feed", "comic-feed")
		params = {"comic": "XKCD", "titleCaption": True, "fontSize": 12}
		with self.assertRaises(RuntimeError):
			ds.open(dsec, params)
		with self.assertRaises(RuntimeError):
			ds.render(dsec, params, None)

	def test_wpotd_raises_without_executor(self):
		dsec = self.create_data_source_context("wpotd")
		ds = Wpotd("wpotd", "wpotd")
		params = {"shrinkToFit": True}
		with self.assertRaises(RuntimeError):
			ds.open(dsec, params)
		with self.assertRaises(RuntimeError):
			ds.render(dsec, params, None)

	def test_newspaper_raises_without_executor(self):
		dsec = self.create_data_source_context("newspaper")
		ds = Newspaper("newspaper", "newspaper")
		params = {"slug": "ny_nyt"}
		with self.assertRaises(RuntimeError):
			ds.open(dsec, params)
		with self.assertRaises(RuntimeError):
			ds.render(dsec, params, None)

	def test_openai_raises_without_executor(self):
		dsec = self.create_data_source_context("openai-image")
		ds = OpenAI("openai-image", "openai-image")
		params = {"prompt": "test", "imageModel": "dall-e-3"}
		with self.assertRaises(RuntimeError):
			ds.open(dsec, params)
		with self.assertRaises(RuntimeError):
			ds.render(dsec, params, None)

if __name__ == "__main__":
	unittest.main()