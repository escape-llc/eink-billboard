from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Mapping, Protocol, runtime_checkable
from PIL import Image

from ..model.service_container import IServiceProvider

class DataSource:
	"""
	Base class of all data sources.
	"""
	def __init__(self, id: str, name: str) -> None:
		self._id = id
		self._name = name
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name

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
	def use[T: "DataSource"](self, source_id: str, kind: type[T]) -> tuple[T, "DataSourceExecutionContext"]:
		"""
		The data source this one uses (`uses` in its descriptor), found by its id, and the context to ask it with (`context_for`): the one way a data source asks another.
		The id is our descriptor's own, never a request's. A source that is not there (disabled sources are not loaded) is a `PermanentError` in our words.
		"""
		# imported here: plugin_base imports this module
		from ..plugins.plugin_base import PermanentError
		source = self._isp.required(DataSourceManager).get_source(source_id)
		if not isinstance(source, kind):
			raise PermanentError(f"The {self._name_of(source_id)} data source is not available. It is needed here: enable it, or choose another source.")
		return source, self.context_for(source)
	def _name_of(self, source_id: str) -> str:
		"""What people call a data source that is not loaded: its descriptor's name, or its id when there is no descriptor to read."""
		from ..model.configuration_manager import ConfigurationManager
		cm = self._isp.get_service(ConfigurationManager)
		if cm is not None:
			for found in cm.enum_datasources():
				if found["info"].get("id") == source_id:
					return str(found["info"].get("name") or source_id)
		return source_id
	def provide[T: "DataSource"](self, kind: type[T]) -> tuple[T, "DataSourceExecutionContext"]:
		"""
		A provider of a capability (#513): `kind` is its contract (`WeatherApi`), and any loaded data source that implements it may answer. The one chosen,
		in order: the device's provider of it (the system setting the contract names), when it is set up (`configured`); the only one that is set up;
		the device's provider, set up or not (its own error says what to set); the only one there is (likewise). Otherwise a `PermanentError` that names
		the capability. Set up means its settings are complete, never that its last call worked: a passing failure does not switch providers.
		"""
		# imported here: plugin_base and configuration_manager import this module, and the contracts are data sources
		from ..plugins.plugin_base import PermanentError
		from ..model.configuration_manager import SettingsConfigurationManager
		from .contracts.provider import ProviderContract
		if not issubclass(kind, ProviderContract):
			raise TypeError(f"{kind.__name__} is not a contract")
		providers = sorted((s for s in self._isp.required(DataSourceManager).sources.values() if isinstance(s, kind)), key=lambda s: s.id)
		chosen: str|None = None
		scm = self._isp.get_service(SettingsConfigurationManager)
		if kind.setting is not None and scm is not None:
			_, system = scm.open("system").get()
			value = (system or {}).get(kind.setting)
			chosen = value if isinstance(value, str) else None
		named = [p for p in providers if p.id == chosen]
		ready = [p for p in providers if isinstance(p, ProviderContract) and p.configured(self.context_for(p))]
		for candidates in ([p for p in named if p in ready], ready, named, providers):
			if len(candidates) == 1:
				return candidates[0], self.context_for(candidates[0])
		if not providers:
			raise PermanentError(f"No {kind.noun} provider is installed. Enable one in the Data Sources settings.")
		if not ready:
			raise PermanentError(f"No {kind.noun} provider is set up. Set one up in its settings: {', '.join(p.name for p in providers)}.")
		raise PermanentError(f"Several {kind.noun} providers are set up. Choose the device's {kind.noun} provider in the System settings.")
	def context_for(self, source: "DataSource") -> "DataSourceExecutionContext":
		"""
		A context for asking another data source for its data (the Weather Overlay asks the Weather): the same services, time and size, with the other's own
		settings and files (its `DatasourceConfigurationManager`, opened by its id as the settings routes open it). So what it keeps (its cache, its lock) is shared,
		never copied, and the origin is not asked again. The id is the source's own (its descriptor's), never a URL's.
		"""
		# imported here: configuration_manager imports this module
		from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager
		from ..model.service_container import ServiceContainer
		local = ServiceContainer(self._isp)
		local.add_service(DatasourceConfigurationManager, self._isp.required(ConfigurationManager).datasource_manager(source.id))
		return DataSourceExecutionContext(local, self._dimensions, self._timestamp)

@dataclass(frozen=True,slots=True)
class MediaRenderResult:
	"""Result of MediaRender.render()"""
	image: Image.Image
	title: str|None
	# the layer this page asks for when the task leaves it to the source (Show As `auto`): `foreground` (text that overlays must not cover) or
	# `background`; None: the descriptor's features decide. A source whose pages differ (a picture with or without a caption) declares both layers
	layer: str|None = None
	# the picture the page was made from, before it was fitted, enhanced or captioned (a download, a drawn picture): what "Save to Gallery" keeps (#768).
	# None for a page that is drawn; a source of the person's own files (the Image Folder) or of the Gallery itself has nothing to add
	original: Image.Image|None = None

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
	async def open_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any]) -> Any:
		...

@runtime_checkable
class MediaListAsync(Protocol):
	"""Ability to return a list of media items asynchronously."""
	async def open_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any]) -> list[Any]:
		...

@runtime_checkable
class MediaRenderAsync(Protocol):
	"""Ability to render media from the source's state (element for a MediaList) asynchronously."""
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		...

@runtime_checkable
class DataSourceApi(Protocol):
	"""
	Data only: the answer of an origin (an API) for `params`, possibly one it kept (see `response_cache.cached`), for other data sources to show
	(they ask it with `dsec.use`). It renders nothing and is never a plugin's source: its descriptor has the `api` feature and no `layer-*` or `media-*`
	one. It holds what the origin needs (the key, the kept times) in its own settings, so every source that shows the data shares them and one answer.
	What `params` and the answer are is the source's own, documented on its class (the OpenWeatherMap one takes `needs` and answers a `Report`).
	"""
	async def open_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any]) -> Any:
		...

def target_dimensions(dsec: DataSourceExecutionContext, display_settings: Mapping[str, Any]|None = None) -> tuple[int, int]:
	"""
	The (width, height) a datasource must render at.

	`dsec.dimensions` is the raw device resolution (e.g. 800x480). For a portrait display the Display task rotates every image
	90 degrees and then centre-crops to the device ratio, so a datasource has to produce the *swapped* size (480x800): an image
	at the device size would be rotated and then cropped. Every datasource that renders at a size uses this; nothing else swaps.

	`display_settings` is the "display" settings document; when omitted it is read from the provider (landscape if unavailable).
	"""
	width, height = dsec.dimensions
	if display_settings is None:
		display_settings = _read_display_settings(dsec)
	orientation = display_settings.get("orientation", "landscape") if display_settings is not None else "landscape"
	return (height, width) if orientation == "portrait" else (width, height)

def _read_display_settings(dsec: DataSourceExecutionContext) -> Mapping[str, Any]|None:
	# imported here: configuration_manager imports this module
	from ..model.configuration_manager import SettingsConfigurationManager
	try:
		scm = dsec.provider.get_service(SettingsConfigurationManager)
		if scm is None:
			return None
		_, display_settings = scm.open("display").get()
		return display_settings
	except Exception as e:
		logging.getLogger(__name__).warning(f"Display settings unavailable, assuming landscape: {e}")
		return None

def enhanced(dsec: DataSourceExecutionContext, picture: Image.Image) -> Image.Image:
	"""
	A photograph with the display settings' brightness, contrast, saturation and sharpness applied (#723). Enhancement is the photograph's and nothing else's:
	a source that returns a photograph calls this on it, before it draws anything over it (a caption, a page around it), so what is drawn stays on its exact inks.
	A page a source draws itself never goes through it.
	"""
	# imported here: image_utils imports the HTTP layer
	from ..utils.image_utils import apply_image_enhancement
	return apply_image_enhancement(picture, _read_display_settings(dsec))

class DataSourceManager:
	"""
	Maintains and manages multiple data sources.
	Manages execution of Futures for data sources.
	"""
	def __init__(self, sources: Mapping[str, DataSource]) -> None:
		self.sources = sources
	def get_source(self, name: str) -> DataSource|None:
		return self.sources.get(name, None)
	def accept(self, msg: DataSourceMessage) -> None:
		source = self.get_source(msg.source_id)
		if source is not None and isinstance(source, DataSourceAccept):
			# Handle the message with the appropriate data source
			source.accept(msg)
		pass