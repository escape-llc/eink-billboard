import logging
from datetime import datetime, timedelta

from ..plugin_base import BasicExecutionContext2, PluginProtocol, TrackType
from ...datasources.data_source import DataSourceExecutionContext, DataSourceManager, MediaList, MediaRender
from ...model.schedule import PlaylistSchedule, PluginSchedule
from ...task.display import DisplayImage
from ...task.message_router import MessageRouter
from ...task.protocols import CancelToken, SubmitFuture, SubmitResult
from ...task.playlist_layer import NextTrack
from ...task.timer import IProvideTimer
from ...task.messages import BasicMessage, FutureCompleted, MessageSink, PluginReceive

class SlideShowTimerExpired(PluginReceive):
	def __init__(self, remaining_state: list, timestamp: datetime):
		super().__init__(timestamp)
		self.remaining_state = remaining_state
	def __repr__(self) -> str:
		return f"SlideShowTimerExpired(remaining_items={len(self.remaining_state)})"

class SlideShow(PluginProtocol):
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.submit_result: SubmitResult|None = None
		self.timer_info = None
		self.logger = logging.getLogger(__name__)
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	def _source_start(self, is_cancelled:CancelToken, context: BasicExecutionContext2, track:PlaylistSchedule) -> bool|None:
		settings = track.content.data
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
		if isinstance(dataSource, MediaList):
			dsec = context.create_datasource_context(dataSource)
			future = dataSource.open(dsec, settings)
			ftimeout = settings.get("timeoutSeconds", 10)
			state = future.result(timeout=ftimeout)
			if len(state) == 0:
				raise RuntimeError(f"{dataSourceName}: No media items found for slide show")
			if is_cancelled():
				return True
			if isinstance(dataSource, MediaRender):
				self._render_image(track.title, dsec, dataSource, settings, state, router, timer, timer_sink)
		return None
	def _continuation_start(self, cancelled:bool, result, exception, msg_ts) -> BasicMessage|None:
		if cancelled:
			return None
		return FutureCompleted(self._name, "start", result, exception, msg_ts)
	def _source_next(self, is_cancelled:CancelToken, context: BasicExecutionContext2, track:PlaylistSchedule, msg: SlideShowTimerExpired) -> None:
		settings = track.content.data
		# assert required services are available
		dsm = context.provider.required(DataSourceManager)
		router = context.provider.required(MessageRouter)
		timer = context.provider.required(IProvideTimer)
		local_sink = context.provider.required(MessageSink)
		# safe to continue
		dataSourceName = settings.get("dataSource", None)
		if dataSourceName is None:
			raise RuntimeError("dataSource is not specified")
		dataSource = dsm.get_source(dataSourceName)
		if dataSource is None:
			raise RuntimeError(f"dataSource '{dataSourceName}' is not available")
		if isinstance(dataSource, MediaList):
			state = msg.remaining_state
			if len(state) == 0:
				self.logger.info(f"{dataSourceName}: Slide show completed, moving to next track")
				self.timer_info = None
				local_sink.accept(NextTrack(msg.timestamp))
				return None
			dsec = context.create_datasource_context(dataSource)
			if isinstance(dataSource, MediaRender):
				self._render_image(track.title, dsec, dataSource, settings, state, router, timer, local_sink)
		return None
	def _continuation_next(self, cancelled:bool, result, exception, msg_ts: datetime) -> BasicMessage|None:
		if cancelled:
			return None
		return FutureCompleted(self._name, "next", result, exception, msg_ts)
	def _render_image(self, title: str, context: DataSourceExecutionContext, dataSource: MediaRender, settings: dict, state: list, router: MessageRouter, timer: IProvideTimer, timer_sink: MessageSink):
		item = state[0]
		future2 = dataSource.render(context, settings, item)
		ftimeout = settings.get("timeoutSeconds", 10)
		image = future2.result(timeout=ftimeout)
		state.pop(0)
		if image is not None:
			router.send("display", DisplayImage(title, image, context.schedule_ts))
			slideMinutes = settings.get("slideMinutes", 15)
			self.timer_info = timer.create_timer(timedelta(minutes=slideMinutes), timer_sink, SlideShowTimerExpired(state, context.schedule_ts))
	def start(self, context: BasicExecutionContext2, track: TrackType) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		if isinstance(track, PlaylistSchedule):
			submit = context.provider.required(SubmitFuture)
			self.submit_result = submit.submit_future(lambda x: self._source_start(x, context, track),
													 lambda cancelled,result,exception: self._continuation_start(cancelled,result,exception, context.schedule_ts))
		elif isinstance(track, PluginSchedule):
			raise RuntimeError(f"Unsupported track type: {type(track)}")
		else:
			raise RuntimeError(f"Unsupported track type: {type(track)}")
	def stop(self, context: BasicExecutionContext2, track: TrackType) -> None:
		self.logger.info(f"{self.id} stop '{track.title}'")
		if self.timer_info is not None:
			self.timer_info[1]()
			self.timer_info = None
		if self.submit_result is not None:
			self.submit_result()
			self.submit_result = None
	def receive(self, context: BasicExecutionContext2, track: TrackType, msg: BasicMessage) -> None:
		self.logger.info(f"{self.id} receive '{track.title}' {msg}")
		if isinstance(track, PlaylistSchedule):
			if isinstance(msg, FutureCompleted):
				self.logger.info(f"{self.name} FutureCompleted {msg}")
				self.submit_result = None
			elif isinstance(msg, SlideShowTimerExpired):
				submit = context.provider.required(SubmitFuture)
				self.submit_result = submit.submit_future(lambda x: self._source_next(x, context, track, msg), lambda cancelled,result,exception: self._continuation_next(cancelled,result,exception, context.schedule_ts))
		elif isinstance(track, PluginSchedule):
			raise RuntimeError(f"Unsupported track type: {type(track)}")
		else:
			raise RuntimeError(f"Unsupported track type: {type(track)}")
