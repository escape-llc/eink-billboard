import asyncio
import logging
import threading
from datetime import timedelta
from typing import Any, Mapping, TypedDict, cast

from ..plugin_base import PluginAsync, PluginExecutionContext, TrackType
from ...datasources.data_source import DataSourceManager, MediaListAsync, MediaRenderAsync
from ...model.configuration_manager import ConfigurationManager
from ...model.schedule import PlaylistSchedule
from ...task.messages import BasicMessage
from ...task.display import DisplayImage
from ...task.display_messages import DISPLAY_LAYERS, DisplayLayer
from ...task.message_router import MessageRouter
from ...task.timer import IProvideTimer

class SettingsDict(TypedDict):
	dataSource: str
	slideMinutes: int
	slideMax: int
	showAs: str

def page_layer(context: PluginExecutionContext, datasource_id: str, show_as: str|None) -> DisplayLayer:
	"""
	How the slide show's pages are shown: the task's `showAs` (background, blend, override), or with `auto` (or nothing) what the data source's
	descriptor says: `layer-foreground` in its `features` overrides, anything else is a background page.
	"""
	for layer in DISPLAY_LAYERS:
		if show_as == layer:
			return layer
	cm = context.provider.get_service(ConfigurationManager)
	if cm is not None:
		for item in cm.enum_datasources():
			info = item["info"]
			if info.get("id") == datasource_id:
				return "override" if "layer-foreground" in (info.get("features") or []) else "background"
	return "background"

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
			layer = page_layer(context, dataSourceName, settings.get("showAs"))
			# TODO check for existing state to resume from?
			state = await dataSource.open_async(dsec, cast(Mapping[str,Any], settings))
			if len(state) == 0:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
			slideMinutes = settings.get("slideMinutes", 15)
			slideMax = settings.get("slideMax", 0)
			count = 0
			startlen = len(state) if slideMax == 0 else slideMax
			failures = 0
			last_error: Exception|None = None
			try:
				while len(state) > 0 and (slideMax == 0 or count < slideMax):
					self.logger.info(f"{self.id} playing '{track.title}' {count + 1}/{startlen}")
					item = state[0]
					state.pop(0)
					try:
						mrr = await dataSource.render_async(dsec, cast(Mapping[str,Any], settings), item)
					except Exception as e:
						# one dead item (URL, file, ...) must not abort the whole show; a failed item is not a slide
						failures += 1
						last_error = e
						self.logger.error(f"{self.id} '{track.title}' item failed ({type(e).__name__}: {e}); {len(state)} remaining", exc_info=True)
						continue
					count += 1
					if mrr is not None:
						router.send("display", DisplayImage(context.timestamp, mrr.title if mrr.title is not None else track.title, mrr.image, layer=layer))
						await timer.sleep(timedelta(minutes=slideMinutes))
			except asyncio.CancelledError as e:
				self.logger.info(f"{self.id} cancelled {len(state)} remaining")
				# TODO save state for next time?
				raise
			if failures > 0 and count == 0:
				raise RuntimeError(f"{dataSourceName}: All {failures} slide show items failed; last error: {last_error}")
		pass
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> BasicMessage|None:
		self.logger.info(f"{self.id} start '{track.title}'")
		try :
			if isinstance(track, PlaylistSchedule):
				await self._run_slideshow(context, track)
			else:
				raise RuntimeError(f"Unsupported track type: {type(track)}")
		finally:
			self.logger.info(f"{self.id} done '{track.title}'")
			done.set()
		return None
