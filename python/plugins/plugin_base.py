from abc import ABC, abstractmethod
import datetime
import os
from typing import Protocol, runtime_checkable
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..datasources.data_source import DataSource, DataSourceExecutionContext, DataSourceManager
from ..model.service_container import IServiceProvider, ServiceContainer, ServiceContainer
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, PluginConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ..model.schedule import PlaylistBase, SchedulableBase, TimerTaskTask
from ..task.active_plugin import ActivePlugin
from ..task.message_router import MessageRouter
from ..task.messages import BasicMessage
from ..utils.image_utils import render_html_arglist
from ..utils.file_utils import path_to_file_url

class BasicExecutionContext2:
	def __init__(self, isp: IServiceProvider, dimensions: tuple[int, int], schedule_ts: datetime.datetime):
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
	def schedule_ts(self) -> datetime.datetime:
		return self._schedule_ts
	def create_datasource_context(self, ds:DataSource):
		cm = self._isp.required(ConfigurationManager)
		dscm = cm.datasource_manager(ds.name)
		local = ServiceContainer(self._isp)
		local.add_service(DatasourceConfigurationManager, dscm)
		dsec = DataSourceExecutionContext(
			local,
			self.dimensions,
			self.schedule_ts
		)
		return dsec

class BasicExecutionContext:
	def __init__(self, stm: StaticConfigurationManager, scm: SettingsConfigurationManager, dsm: DataSourceManager, dimensions, router:MessageRouter):
		if stm is None:
			raise ValueError("stm is None")
		if scm is None:
			raise ValueError("scm is None")
		if dsm is None:
			raise ValueError("dsm is None")
		if router is None:
			raise ValueError("router is None")
		self.scm = scm
		self.stm = stm
		self.dsm = dsm
		self.dimensions = dimensions
		self.router = router

class PluginExecutionContext(BasicExecutionContext):
	def __init__(self, sb: SchedulableBase, stm: StaticConfigurationManager, scm: SettingsConfigurationManager, dsm: DataSourceManager, pcm: PluginConfigurationManager, ap:ActivePlugin, dimensions, schedule_ts: datetime, router:MessageRouter):
		super().__init__(stm, scm, dsm, dimensions, router)
		if sb is None:
			raise ValueError("sb is None")
		if pcm is None:
			raise ValueError("pcm is None")
		if ap is None:
			raise ValueError("ap is None")
		if schedule_ts is None:
			raise ValueError("schedule_ts is None")
		self.sb = sb
		self.pcm = pcm
		self.schedule_ts = schedule_ts
		self._ap = ap

	def future(self, token:str, cx:callable):
		self._ap.future(token,cx)
	def alarm_clock(self, wake_up_ts:datetime):
		self._ap.alarm_clock(wake_up_ts)

class RenderSession:
	def __init__(self, stm: StaticConfigurationManager, render_dir:str, html_file:str, css_file:str=None):
		if stm is None:
			raise ValueError("stm is None")
		if render_dir is None:
			raise ValueError("render_dir is None")
		if html_file is None:
			raise ValueError("html_file is None")
		self.html_file = html_file
		# NOTE CSS files MUST use absolute paths because HTML is saved to a temporary file
		# load the base plugin and current plugin css files
		self.css_files = [
			path_to_file_url(os.path.join(stm.ROOT_PATH, "render", "plugin.css")),
			path_to_file_url(os.path.join(stm.ROOT_PATH, "render", "themes.css"))
		]
		if css_file:
			self.css_files.append(css_file)
		self.env = self._create_render_environment(stm, render_dir)
		self.font_faces = stm.enum_fonts()
	def _create_render_environment(self, stm: StaticConfigurationManager, render_dir:str):
		loader = FileSystemLoader([render_dir, os.path.join(stm.ROOT_PATH, "render")])
		return Environment(
			loader=loader,
			autoescape=select_autoescape(['html', 'xml'])
		)
	def render(self, dimensions, template_params={}):
		template_params["style_sheets"] = self.css_files
		template_params["width"] = dimensions[0]
		template_params["height"] = dimensions[1]
		template_params["font_faces"] = self.font_faces

		# load and render the given html template
		template = self.env.get_template(self.html_file)
		rendered_html = template.render(template_params)
		return render_html_arglist(rendered_html, [f"--window-size={dimensions[0]},{dimensions[1]}"])
	pass

type TrackType = SchedulableBase | PlaylistBase | TimerTaskTask
@runtime_checkable
class PluginProtocol(Protocol):
	@property
	def id(self) -> str:
		...
	@property
	def name(self) -> str:
		...
	def start(self, context: BasicExecutionContext2, track: TrackType) -> None:
		...
	def receive(self, context: BasicExecutionContext2, track: TrackType, msg: BasicMessage) -> None:
		...
	def stop(self, context: BasicExecutionContext2, track: TrackType) -> None:
		...

class PluginBase(ABC):
	def __init__(self, id, name):
		self.id = id
		self.name = name
	@abstractmethod
	def timeslot_start(self, pec: PluginExecutionContext):
		pass
	@abstractmethod
	def timeslot_end(self, pec: PluginExecutionContext):
		pass
	@abstractmethod
	def schedule(self, pec: PluginExecutionContext):
		pass
	@abstractmethod
	def receive(self, pec: PluginExecutionContext, msg: BasicMessage):
		pass
	@abstractmethod
	def reconfigure(self, pec: PluginExecutionContext, config):
		pass
