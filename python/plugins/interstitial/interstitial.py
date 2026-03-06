from datetime import timedelta
import logging
import threading
from typing import Any, TypedDict, cast

from ...datasources.data_source import DataSourceManager, MediaItemAsync, MediaRenderAsync
from ...model.schedule import TimerTaskItem
from ...task.display import PriorityImage
from ...task.message_router import MessageRouter
from ..plugin_base import PluginAsync, PluginExecutionContext, TrackType

class SettingsDict(TypedDict):
	dataSource: str
	slideMinutes: int

class InterstitialAsync(PluginAsync):
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
	async def _do_task_async(self, context: PluginExecutionContext, track: TimerTaskItem) -> None:
		settings: SettingsDict = cast(SettingsDict, track.task.content)
		# assert required services are available
		dsm = context.provider.required(DataSourceManager)
		router = context.provider.required(MessageRouter)
		# safe to continue
		dataSourceName = settings.get("dataSource", None)
		if dataSourceName is None:
			raise RuntimeError("dataSource is not specified")
		dataSource = dsm.get_source(dataSourceName)
		if dataSource is None:
			raise RuntimeError(f"dataSource '{dataSourceName}' is not available")
		if isinstance(dataSource, MediaItemAsync) and isinstance(dataSource, MediaRenderAsync):
			dsec = context.create_datasource_context(dataSource)
			state = await dataSource.open_async(dsec, cast(dict[str,Any],settings))
			if state is None:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
			item = state
			mrr = await dataSource.render_async(dsec, cast(dict[str,Any],settings), item)
			if mrr is not None:
				# send priority display message
				slideMinutes = settings.get("slideMinutes", 1)
				router.send("display", PriorityImage(dsec.timestamp, mrr.title if mrr.title is not None else track.title, mrr.image, timedelta(minutes=slideMinutes)))
		else:
			raise RuntimeError(f"{dataSourceName}: does not support async media item and render")
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		try:
			if isinstance(track, TimerTaskItem):
				await self._do_task_async(context, track)
				return
			raise RuntimeError(f"Unsupported track type: {type(track)}")
		finally:
			self.logger.info(f"{self.id} done '{track.title}'")
			done.set()
