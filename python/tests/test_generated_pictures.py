"""
A source that makes its one picture itself (Year Progress, Countdown, Today, System Status) opens a list of one item: an empty list is "nothing to show",
and the slide show failed such a track with "No media items found" (#719).
"""
import unittest

from ..datasources.countdown.countdown import CountdownAsync
from ..datasources.system_status.system_status import SystemStatusAsync
from ..datasources.today.today import TodayAsync
from ..datasources.year_progress.year_progress import YearProgressAsync
from .test_datasource_fixes import make_dsec

class TestGeneratedPictures(unittest.IsolatedAsyncioTestCase):
	async def test_each_opens_one_item(self):
		for source in (YearProgressAsync("year-progress", "Year Progress"), CountdownAsync("countdown", "Countdown"), TodayAsync("today", "Today"), SystemStatusAsync("system-status", "System Status")):
			with self.subTest(source=source.id):
				self.assertEqual(1, len(await source.open_async(make_dsec(), {})))
