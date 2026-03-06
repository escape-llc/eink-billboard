import asyncio
import logging
import threading
from datetime import timedelta
from typing import Any, TypedDict, cast

from ..plugin_base import PluginAsync, PluginExecutionContext, TrackType
from ...datasources.data_source import DataSourceManager, MediaListAsync, MediaRenderAsync
from ...model.schedule import PlaylistSchedule
from ...task.display import DisplayImage
from ...task.message_router import MessageRouter
from ...task.timer import IProvideTimer

class SettingsDict(TypedDict):
	dataSource: str
	slideMinutes: int
	slideMax: int

class SlideShowAsync(PluginAsync):
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.timer_info = None
		self.logger = logging.getLogger(__name__)
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	async def _run_slideshow(self, context: PluginExecutionContext, track: PlaylistSchedule) -> None:
		settings: SettingsDict = cast(SettingsDict, track.content.data)
		# assert required services are available
		dsm = context.provider.required(DataSourceManager)
		router = context.provider.required(MessageRouter)
		timer = context.provider.required(IProvideTimer)
		# safe to continue
		dataSourceName = settings.get("dataSource", None)
		if dataSourceName is None:
			raise RuntimeError("dataSource is not specified")
		dataSource = dsm.get_source(dataSourceName)
		if dataSource is None:
			raise RuntimeError(f"dataSource '{dataSourceName}' is not available")
		if isinstance(dataSource, MediaListAsync) and isinstance(dataSource, MediaRenderAsync):
			dsec = context.create_datasource_context(dataSource)
			# TODO check for existing state to resume from?
			state = await dataSource.open_async(dsec, cast(dict[str,Any], settings))
			if len(state) == 0:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
			slideMinutes = settings.get("slideMinutes", 15)
			slideMax = settings.get("slideMax", 0)
			count = 0
			startlen = len(state) if slideMax == 0 else slideMax
			try:
				while len(state) > 0 and (slideMax == 0 or count < slideMax):
					self.logger.info(f"{self.id} playing '{track.title}' {count + 1}/{startlen}")
					item = state[0]
					mrr = await dataSource.render_async(dsec, cast(dict[str,Any], settings), item)
					count += 1
					state.pop(0)
					if mrr is not None:
						router.send("display", DisplayImage(context.timestamp, mrr.title if mrr.title is not None else track.title, mrr.image))
						await timer.sleep(timedelta(minutes=slideMinutes))
			except asyncio.CancelledError as e:
				self.logger.info(f"{self.id} cancelled {len(state)} remaining")
				# TODO save state for next time?
				raise
		pass
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		try :
			if isinstance(track, PlaylistSchedule):
				await self._run_slideshow(context, track)
			else:
				raise RuntimeError(f"Unsupported track type: {type(track)}")
		finally:
			self.logger.info(f"{self.id} done '{track.title}'")
			done.set()
