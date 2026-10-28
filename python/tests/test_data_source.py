from datetime import datetime
from typing import Any, cast
import unittest

from ..datasources.countdown.countdown import CountdownAsync
from ..datasources.year_progress.year_progress import YearProgressAsync
from ..datasources.clock.clock_face import ClockAsync
from ..datasources.comic.comic import ComicFeedAsync
from ..datasources.data_source import DataSourceExecutionContext, MediaItemAsync, MediaListAsync, MediaRenderAsync
from ..datasources.wikipedia_potd.wikipedia_potd import WpotdAsync
from ..datasources.image_folder.image_folder import ImageFolderAsync
from ..datasources.newspaper.newspaper import NewspaperAsync
from ..model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.service_container import ServiceContainer
from ..task.async_http_worker_pool import AsyncHttpWorkerPool
from ..model.configuration_manager import ConfigurationManager
from .utils import create_configuration_manager, save_datasource_settings, save_image, temp_configuration_manager, test_output_path_for

def create_data_source_context(dsid:str, schedule_ts: datetime|None = None, cm: ConfigurationManager|None = None) -> DataSourceExecutionContext:
	schedule_ts = schedule_ts or datetime.now()
	cm = cm or create_configuration_manager()
	cm.ensure_folders()
	scm = cm.settings_manager()
	stm = cm.static_manager()
	dscm = cm.datasource_manager(dsid)
	root = ServiceContainer()
	root.add_service(ConfigurationManager, cm)
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

	async def run_datasource_async(self, ds, params, image_size, image_count, cm: ConfigurationManager|None = None):
		self.assertIsInstance(ds, MediaListAsync)
		self.assertIsInstance(ds, MediaRenderAsync)
		folder = test_output_path_for(f"ds-{ds.id}-async")
		dsec = create_data_source_context(ds.id, cm=cm)
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
		# the task names a folder; the data source keeps where it is in its own settings
		cm = temp_configuration_manager(self)
		save_datasource_settings(cm, "image-folder", { "folders": [{ "name": "test images", "path": "python/tests/images" }] })
		params = {
			"folder": "test images"
		}
		self.pool.submit(self.run_datasource_async, ds, params, (800, 480), 3, cm).result(timeout=60)
	def test_image_folder_requires_folder(self):
		import asyncio
		ds = ImageFolderAsync("image-folder", "image-folder")
		with self.assertRaisesRegex(ValueError, "'folder' setting is required"):
			asyncio.run(ds.open_async(cast(Any, None), {}))
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
		ds = WpotdAsync("wikipedia-potd", "wikipedia-potd")
		params = {
			"shrinkToFit": True
		}
		self.pool.submit(self.run_datasource_async, ds, params, (800,480), 1).result(timeout=60)
	def test_clock_faces(self):
		for face in ("brass", "roman-classic", "aviator", "digital", "words"):
			with self.subTest(face=face):
				self.pool.submit(self.run_datasource2_async, ClockAsync(f"clock-{face}", "clock"), {"face": face, "shadow": "face"}, (800, 480), 1).result(timeout=60)
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