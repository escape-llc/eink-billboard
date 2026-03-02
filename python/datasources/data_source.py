from concurrent.futures import Executor, ThreadPoolExecutor, Future
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from PIL import Image

from ..model.service_container import IServiceProvider

class DataSource:
	"""
	Base class of all data sources.
	"""
	def __init__(self, id: str, name: str) -> None:
		self._id = id
		self._name = name
		self._es = None
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	def set_executor(self, es: Executor) -> None:
		self._es = es

class DataSourceExecutionContext:
	"""
	Passed to all DataSource methods to provide context about the execution.
	"""
	def __init__(self, isp: IServiceProvider, dimensions: tuple[int, int], timestamp: datetime):
		if isp is None:
			raise ValueError("isp is None")
		if dimensions is None:
			raise ValueError("dimensions is None")
		if timestamp is None:
			raise ValueError("timestamp is None")
		self._isp = isp
		self._dimensions = dimensions
		self._timestamp = timestamp
	@property
	def provider(self) -> IServiceProvider:
		return self._isp
	@property
	def dimensions(self) -> tuple[int, int]:
		return self._dimensions
	@property
	def timestamp(self) -> datetime:
		return self._timestamp

@dataclass(frozen=True,slots=True)
class MediaRenderResult:
	"""Result of MediaRender.render()"""
	image: Image.Image
	title: str|None

@runtime_checkable
class MediaRender(Protocol):
	"""Ability to render media from the source's state (element for a MediaList)."""
	def render(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> Future[MediaRenderResult | None]:
		"""
		Ability to render an image from the params and state.

		:param self: data source
		:type self: MediaRender
		:param dsec: Execution context
		:type dsec: DataSourceExecutionContext
		:param params: options for this render (visual)
		:type params: dict[str, any]
		:param state: state for this render (data)
		:type state: any
		:return: The future to (image or None).
		:rtype: Future[Image.Image | None]
		"""
		...
@runtime_checkable
class MediaItem(Protocol):
	"""Ability to return a single media item."""
	def open(self, dsec: DataSourceExecutionContext, params:dict[str,Any]) -> Future[Any]:
		...
@runtime_checkable
class MediaList(Protocol):
	"""Ability to return a list of media items."""
	def open(self, dsec: DataSourceExecutionContext, params:dict[str,Any]) -> Future[list]:
		...

@runtime_checkable
class DataSourceMessage(Protocol):
	"""
	Tag specific messages with this protocol for the data source manager.
	"""
	@property
	def source_id(self) -> str:
		...

@runtime_checkable
class DataSourceAccept(Protocol):
	"""Data Source accepting messages protocol."""
	def accept(self, msg: DataSourceMessage) -> None:
		...

@runtime_checkable
class MediaItemAsync(Protocol):
	"""Ability to return a single media item asynchronously."""
	async def open_async(self, dsec: DataSourceExecutionContext, params:dict[str,Any]) -> Any:
		...

@runtime_checkable
class MediaListAsync(Protocol):
	"""Ability to return a list of media items asynchronously."""
	async def open_async(self, dsec: DataSourceExecutionContext, params:dict[str,Any]) -> list:
		...

@runtime_checkable
class MediaRenderAsync(Protocol):
	"""Ability to render media from the source's state (element for a MediaList) asynchronously."""
	async def render_async(self, dsec: DataSourceExecutionContext, params:dict[str,Any], state:Any) -> MediaRenderResult | None:
		...

class DataSourceManager:
	"""
	Maintains and manages multiple data sources.
	Manages execution of Futures for data sources.
	"""
	def __init__(self, es: Executor|None, sources: dict[str, DataSource]) -> None:
		self.es = es if es is not None else ThreadPoolExecutor(max_workers=4)
		self.sources = sources
		for source in self.sources.values():
			source.set_executor(self.es)
	def get_source(self, name: str) -> DataSource|None:
		return self.sources.get(name, None)
	def shutdown(self) -> None:
		self.es.shutdown(wait=True, cancel_futures=True)
	def accept(self, msg: DataSourceMessage) -> None:
		source = self.get_source(msg.source_id)
		if source is not None and isinstance(source, DataSourceAccept):
			# Handle the message with the appropriate data source
			source.accept(msg)
		pass