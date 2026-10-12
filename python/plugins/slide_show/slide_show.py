import asyncio
import logging
import threading
from datetime import timedelta
from typing import Any, Mapping, TypedDict, cast

from ..plugin_base import PluginAsync, PluginExecutionContext, TrackType
from ...datasources.data_source import DataSourceManager, MediaListAsync, MediaRenderAsync
from ..kept_list import NoItem, fingerprint_of, open_list
from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager
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
	listMode: str
	refreshHours: int

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

# the task's settings that do not choose the list (the rest, with the data source's own settings, are what a kept list is for)
NOT_THE_LIST = ("slideMinutes", "slideMax", "showAs", "listMode", "refreshHours")
PLUGIN_ID = "slide-show"

def keeps_list(context: PluginExecutionContext, datasource_id: str) -> bool:
	"""Whether the data source's list is a real one (`keepsList` in its descriptor), not a view of now that is made fresh every time."""
	cm = context.provider.get_service(ConfigurationManager)
	if cm is not None:
		for item in cm.enum_datasources():
			info = item["info"]
			if info.get("id") == datasource_id:
				return info.get("keepsList") is True
	return False

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
			# the list of this visit: the slot's kept one when the source's list is a real one and the task says `continue`, else a new one (kept_list.py)
			keep = context.slot is not None and settings.get("listMode", "continue") == "continue" and keeps_list(context, dataSourceName)
			pcm = plugin_settings = ds_rev = None
			if keep:
				cm = context.provider.required(ConfigurationManager)
				pcm = cm.plugin_manager(PLUGIN_ID)
				plugin_settings = pcm.open().get()[1]
				ds_rev = dsec.provider.required(DatasourceConfigurationManager).open().get()[0]
			own = { k: v for k, v in settings.items() if k not in NOT_THE_LIST }
			kept = await open_list(
				pcm, context.slot or "", fingerprint_of(dataSourceName, own, ds_rev), context.timestamp,
				lambda: dataSource.open_async(dsec, cast(Mapping[str,Any], settings)),
				keep=keep, refresh_hours=settings.get("refreshHours"), stale_days=(plugin_settings or {}).get("staleDays"))
			slideMinutes = settings.get("slideMinutes", 15)
			slideMax = settings.get("slideMax", 0)
			count = 0
			failures = 0
			last_error: Exception|None = None
			try:
				while slideMax == 0 or count < slideMax:
					item = kept.head()
					if isinstance(item, NoItem):
						break
					self.logger.info(f"{self.id} playing '{track.title}' {count + 1}/{slideMax if slideMax else 'all'}")
					try:
						mrr = await dataSource.render_async(dsec, cast(Mapping[str,Any], settings), item)
					except Exception as e:
						# one dead item (URL, file, ...) must not abort the whole show; a failed item is not a slide
						failures += 1
						last_error = e
						self.logger.error(f"{self.id} '{track.title}' item failed ({type(e).__name__}: {e})", exc_info=True)
						kept.drop()
						continue
					count += 1
					if mrr is not None:
						router.send("display", DisplayImage(context.timestamp, mrr.title if mrr.title is not None else track.title, mrr.image, layer=layer))
					# shown: off the list now, so a restart or a cancel during the wait does not show it twice
					kept.drop()
					if mrr is not None:
						await timer.sleep(timedelta(minutes=slideMinutes))
			except asyncio.CancelledError as e:
				# a kept list was saved item by item: the next visit goes on from here
				self.logger.info(f"{self.id} cancelled")
				raise
			if count == 0 and failures == 0:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
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
