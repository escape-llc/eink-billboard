from concurrent.futures import Executor, ThreadPoolExecutor, Future
from datetime import datetime
from typing import Protocol, runtime_checkable
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
	def __init__(self, isp: IServiceProvider, dimensions: tuple[int, int], schedule_ts: datetime):
		if isp is None:
			raise ValueError("isp is None")
		if dimensions is None:
			raise ValueError("dimensions is None")
		if schedule_ts is None:
			raise ValueError("schedule_ts is None")
		self._isp = isp
		self._dimensions = dimensions
		self._schedule_ts = schedule_ts
	@property
	def provider(self) -> IServiceProvider:
		return self._isp
	@property
	def dimensions(self) -> tuple[int, int]:
		return self._dimensions
	@property
	def schedule_ts(self) -> datetime:
		return self._schedule_ts

@runtime_checkable
class MediaRender(Protocol):
	"""Protocol for rendering media."""
	def render(self, dsec: DataSourceExecutionContext, params:dict[str,any], state:any) -> Future[Image.Image | None]:
		"""
		Ability to render an image from the params and state.
		
		:param self: Description
		:param dsec: Execution context
		:type dsec: DataSourceExecutionContext
		:param params: options for this render (visual)
		:type params: dict[str, any]
		:param state: state for this render (data)
		:type state: any
		:return: The future to (image or None).
		:rtype: Future[Image | None]
		"""
		...
@runtime_checkable
class MediaItem(MediaRender, Protocol):
	def open(self, dsec: DataSourceExecutionContext, params:dict[str,any]) -> Future[any]:
		...
@runtime_checkable
class MediaList(MediaRender,Protocol):
	def open(self, dsec: DataSourceExecutionContext, params:dict[str,any]) -> Future[list]:
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