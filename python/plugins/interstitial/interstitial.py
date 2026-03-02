from datetime import timedelta
import logging
from typing import Any

from ...datasources.data_source import DataSourceExecutionContext, DataSourceManager, MediaItem, MediaRender
from ...model.schedule import TimerTaskItem
from ...model.time_of_day import TimeOfDay
from ...task.display import DisplayImage
from ...task.protocols import CancelToken, SubmitFuture
from ...task.message_router import MessageRouter
from ...task.messages import BasicMessage, FutureCompleted, MessageSink, TimerExpired
from ...task.playlist_layer import NextTrack
from ...task.timer import IProvideTimer
from ..plugin_base import PluginExecutionContext, TrackType, PluginProtocol

class Interstitial(PluginProtocol):
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.submit_result = None
		self.timer_info = None
		self.logger = logging.getLogger(__name__)
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	def _source_start(self, is_cancelled:CancelToken, context: PluginExecutionContext, track:TimerTaskItem) -> bool|None:
		settings = track.task.content
		# assert required services are available
		dsm = context.provider.required(DataSourceManager)
		router = context.provider.required(MessageRouter)
		timer = context.provider.required(IProvideTimer)
		timer_sink = context.provider.required(MessageSink)
		# safe to continue
		dataSourceName = settings.get("dataSource", None)
		if dataSourceName is None:
			raise RuntimeError("dataSource is not specified")
		dataSource = dsm.get_source(dataSourceName)
		if dataSource is None:
			raise RuntimeError(f"dataSource '{dataSourceName}' is not available")
		if isinstance(dataSource, MediaItem):
			dsec = context.create_datasource_context(dataSource)
			future = dataSource.open(dsec, settings)
			ftimeout = settings.get("timeoutSeconds", 10)
			state = future.result(timeout=ftimeout)
			if state is None:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
			if is_cancelled():
				return True
			if isinstance(dataSource, MediaRender):
				self._render_image(track.title, dsec, dataSource, settings, state, router, timer, timer_sink)
		return None
	def _continuation_start(self, cancelled:bool, result, exception, context: PluginExecutionContext) -> BasicMessage|None:
		if cancelled:
			return None
		tod:TimeOfDay|None = context.provider.get_service(TimeOfDay)
		return FutureCompleted(tod.current_time() if tod is not None else context.timestamp, self._name, "start", result, exception)
	def _render_image(self, title: str, context: DataSourceExecutionContext, dataSource: MediaRender, settings: dict, state: Any, router: MessageRouter, timer: IProvideTimer, timer_sink: MessageSink):
		item = state
		future2 = dataSource.render(context, settings, item)
		ftimeout = settings.get("timeoutSeconds", 10)
		mrr = future2.result(timeout=ftimeout)
		if mrr is not None:
			# TODO send an interstitial display message
			router.send("display", DisplayImage(context.timestamp, mrr.title if mrr.title is not None else title, mrr.image))
			slideMinutes = settings.get("slideMinutes", 15)
			self.timer_info = timer.create_timer(timedelta(minutes=slideMinutes), timer_sink, "slideshow", state)
	def start(self, context: PluginExecutionContext, track: TrackType) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		if isinstance(track, TimerTaskItem):
			submit = context.provider.required(SubmitFuture)
			self.submit_result = submit.submit_future(lambda x: self._source_start(x, context, track),
													 lambda cancelled,result,exception: self._continuation_start(cancelled, result, exception, context))
			return
		raise RuntimeError(f"Unsupported track type: {type(track)}")
	def stop(self, context: PluginExecutionContext, track: TrackType) -> None:
		self.logger.info(f"{self.id} stop '{track.title}'")
		if self.timer_info is not None:
			self.timer_info[1]()
			self.timer_info = None
		if self.submit_result is not None:
			self.submit_result()
			self.submit_result = None
	def receive(self, context: PluginExecutionContext, track: TrackType, msg: BasicMessage) -> None:
		self.logger.info(f"{self.id} receive '{track.title}' {msg}")
		if isinstance(track, TimerTaskItem):
			if isinstance(msg, FutureCompleted):
				self.logger.info(f"{self.name} FutureCompleted {msg}")
				self.submit_result = None
				# TODO may want to end timeslot here and not set/wait for the timer
			elif isinstance(msg, TimerExpired):
				sink = context.provider.required(MessageSink)
				sink.accept(NextTrack(msg.timestamp))
			return
		raise RuntimeError(f"Unsupported track type: {type(track)}")
	pass