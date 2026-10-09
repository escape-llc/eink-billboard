import logging
import threading
from typing import Any, Mapping, cast

from ...datasources.data_source import DataSourceManager, MediaItemAsync, MediaRenderAsync
from ...model.schedule import TimerTaskItem
from ...task.display_messages import OverlayImage, OverlayRevoke, OverlayZones
from ...task.message_router import MessageRouter
from ..plugin_base import PermanentError, PluginAsync, PluginExecutionContext, TrackType

class OverlayAsync(PluginAsync):
	"""
	A timer task that puts a data source's image in a zone of the screen (python/task/overlay_zones.py), over the background.
	The overlay belongs to the task (its id is the key): the next run replaces it, and a run where the data source has nothing to show
	(open or render gives None) takes it down. The data source renders at the zone's size, as the viewer sees it.
	"""
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.logger = logging.getLogger(__name__)
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	async def _do_task_async(self, context: PluginExecutionContext, track: TimerTaskItem) -> None:
		settings = cast(Mapping[str, Any], track.task.content)
		dsm = context.provider.required(DataSourceManager)
		router = context.provider.required(MessageRouter)
		zones = context.provider.required(OverlayZones)
		zone_name = settings.get("zone")
		zone = zones.get(zone_name) if isinstance(zone_name, str) else None
		if zone is None:
			raise PermanentError(f"Zone '{zone_name}' is not one of this display's ({', '.join(zones.names())})")
		data_source_name = settings.get("dataSource")
		if data_source_name is None:
			raise PermanentError("dataSource is not specified")
		data_source = dsm.get_source(data_source_name)
		if data_source is None:
			raise PermanentError(f"dataSource '{data_source_name}' is not available")
		if not (isinstance(data_source, MediaItemAsync) and isinstance(data_source, MediaRenderAsync)):
			raise PermanentError(f"{data_source_name}: does not support async media item and render")
		wash = settings.get("wash", 0.0)
		wash = float(wash) if isinstance(wash, (int, float)) and not isinstance(wash, bool) else 0.0
		# the data source sees the zone as its whole screen
		zone_context = PluginExecutionContext(context.provider, zone.dimensions, context.timestamp)
		dsec = zone_context.create_datasource_context(data_source)
		try:
			state = await data_source.open_async(dsec, settings)
			mrr = None if state is None else await data_source.render_async(dsec, settings, state)
		except Exception as e:
			# say which task failed; the timer layer shows the error in the zone
			self.logger.error(f"{self.id} '{track.title}' failed ({type(e).__name__}: {e})", exc_info=True)
			raise
		if mrr is None:
			self.logger.info(f"{self.id} '{track.title}': nothing to show, revoking its overlay")
			router.send("display", OverlayRevoke(dsec.timestamp, track.id))
			return
		router.send("display", OverlayImage(dsec.timestamp, track.id, zone.name, mrr.title if mrr.title is not None else track.title, mrr.image, wash))
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		try:
			if isinstance(track, TimerTaskItem):
				await self._do_task_async(context, track)
				return
			raise PermanentError(f"The overlay plugin runs as a timer task, not as {type(track).__name__}")
		finally:
			self.logger.info(f"{self.id} done '{track.title}'")
			done.set()
