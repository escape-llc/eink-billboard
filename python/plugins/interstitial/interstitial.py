from datetime import timedelta
import logging

from python.datasources.data_source import DataSourceExecutionContext, DataSourceManager, MediaItem
from python.model.schedule import TimerTaskItem
from python.plugins.slide_show.slide_show import SlideShowTimerExpired
from python.task.display import DisplayImage
from python.task.future_source import CancelToken, SubmitFuture
from python.task.message_router import MessageRouter
from python.task.messages import BasicMessage, FutureCompleted, MessageSink
from python.task.playlist_layer import NextTrack
from python.task.timer import IProvideTimer
from ..plugin_base import BasicExecutionContext2, TrackType, PluginProtocol

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
	def _source_start(self, is_cancelled:CancelToken, context: BasicExecutionContext2, track:TimerTaskItem) -> bool|None:
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
			self._render_image(track.title, dsec, dataSource, settings, state, router, timer, timer_sink)
		return None
	def _continuation_start(self, cancelled:bool, result, exception, msg_ts) -> BasicMessage:
		if cancelled:
			return None
		return FutureCompleted(self._name, "start", result, exception, msg_ts)
	def _render_image(self, title: str, context: DataSourceExecutionContext, dataSource: MediaItem, settings: dict, state: any, router: MessageRouter, timer: IProvideTimer, timer_sink: MessageSink):
		item = state
		future2 = dataSource.render(context, settings, item)
		ftimeout = settings.get("timeoutSeconds", 10)
		image = future2.result(timeout=ftimeout)
		# TODO send an interstitial display message
		router.send("display", DisplayImage(title, image, context.schedule_ts))
		slideMinutes = settings.get("slideMinutes", 15)
		self.timer_info = timer.create_timer(timedelta(minutes=slideMinutes), timer_sink, SlideShowTimerExpired(state, context.schedule_ts))
	def start(self, context: BasicExecutionContext2, track: TrackType) -> None:
		self.logger.info(f"{self.id} start '{track.title}'")
		if isinstance(track, TimerTaskItem):
			submit = context.provider.required(SubmitFuture)
			self.submit_result = submit.submit_future(lambda x: self._source_start(x, context, track),
													 lambda cancelled,result,exception: self._continuation_start(cancelled, result, exception, context.schedule_ts))
			return
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
		if isinstance(track, TimerTaskItem):
			if isinstance(msg, FutureCompleted):
				self.logger.info(f"{self.name} FutureCompleted {msg}")
				self.submit_result = None
				# TODO may want to end timeslot here and not set/wait for the timer
			elif isinstance(msg, SlideShowTimerExpired):
				sink = context.provider.required(MessageSink)
				sink.accept(NextTrack(msg.timestamp))
			return
		raise RuntimeError(f"Unsupported track type: {type(track)}")
	pass