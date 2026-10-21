from datetime import datetime
import os
import threading
from typing import Protocol, runtime_checkable
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..datasources.data_source import DataSource, DataSourceExecutionContext
from ..model.service_container import IServiceProvider, ServiceContainer
from ..model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, StaticConfigurationManager
from ..model.schedule import ScheduleItemBase
from ..model.theme import DEFAULT_INPUTS, ThemeInputs, css_vars
from ..task.messages import BasicMessage
from ..utils.image_utils import render_html_arglist
from ..utils.file_utils import path_to_file_url

class PermanentError(Exception):
	"""
	A failure that trying again cannot fix (a setting that is wrong, a service that is not there for good).
	The playlist layer strikes the track out at once instead of waiting for its third transient failure.
	"""

class PluginExecutionContext:
	def __init__(self, isp: IServiceProvider, dimensions: tuple[int, int], timestamp: datetime, slot: str|None = None, resumed: bool = False):
		if isp is None:
			raise ValueError("isp is None")
		if dimensions is None:
			raise ValueError("dimensions is None")
		if timestamp is None:
			raise ValueError("timestamp is None")
		self._isp = isp
		self._dimensions = dimensions
		self._timestamp = timestamp
		self._slot = slot
		self._resumed = resumed
	@property
	def resumed(self) -> bool:
		"""
		The track is entered again after a stop (or a configuration change) interrupted it. A plugin that would only repeat what the panel already shows
		returns at once (the layer then goes on to the next track); one that can carry on where it was does. Every playlist plugin honours it (see `PluginAsync`).
		"""
		return self._resumed
	@property
	def slot(self) -> str|None:
		"""Who is running, unique on the device: the playlist's id and the track's (track ids repeat across playlists). None when not known (a timer task)."""
		return self._slot
	@property
	def provider(self) -> IServiceProvider:
		return self._isp
	@property
	def dimensions(self) -> tuple[int, int]:
		return self._dimensions
	@property
	def timestamp(self) -> datetime:
		return self._timestamp
	def update_timestamp(self, new_ts: datetime):
		if new_ts is None:
			raise ValueError("new_ts is None")
		self._timestamp = new_ts
	def create_datasource_context(self, ds:DataSource):
		cm = self._isp.required(ConfigurationManager)
		# its folder is its id (the descriptor's), as the settings routes use: the name is for people and may hold spaces
		dscm = cm.datasource_manager(ds.id)
		local = ServiceContainer(self._isp)
		local.add_service(DatasourceConfigurationManager, dscm)
		dsec = DataSourceExecutionContext(
			local,
			self.dimensions,
			self.timestamp
		)
		return dsec

class RenderSession:
	def __init__(self, stm: StaticConfigurationManager, render_dir:str, html_file:str, theme: ThemeInputs|None = None):
		if stm is None:
			raise ValueError("stm is None")
		if render_dir is None:
			raise ValueError("render_dir is None")
		if html_file is None:
			raise ValueError("html_file is None")
		self.html_file = html_file
		# the shared stylesheets; a page puts its own CSS in the {% block style %} of its template, so it is one file.
		# NOTE linked CSS files MUST use absolute paths because HTML is saved to a temporary file
		self.css_files = [
			path_to_file_url(os.path.join(stm.ROOT_PATH, "render", "plugin.css")),
			path_to_file_url(os.path.join(stm.ROOT_PATH, "render", "themes.css"))
		]
		# the device theme (python/model/theme.py: current_inputs); without one, the factory theme
		self.theme = theme if theme is not None else DEFAULT_INPUTS
		self.env = self._create_render_environment(stm, render_dir)
		self.font_faces = stm.enum_fonts()
	def _create_render_environment(self, stm: StaticConfigurationManager, render_dir:str):
		loader = FileSystemLoader([render_dir, os.path.join(stm.ROOT_PATH, "render")])
		return Environment(
			loader=loader,
			autoescape=select_autoescape(['html', 'xml'])
		)
	def render(self, dimensions, template_params: dict|None = None, transparent: bool = False):
		"""The page as an image. `transparent` (an overlay's page): Chromium draws no white under the page, so what the page does not paint stays clear;
		the page also sets `--page-bg: transparent`, or its container paints the theme's background."""
		template_params = dict(template_params or {})
		template_params["style_sheets"] = self.css_files
		template_params["theme_vars"] = css_vars(self.theme)
		template_params["width"] = dimensions[0]
		template_params["height"] = dimensions[1]
		template_params["font_faces"] = self.font_faces

		# load and render the given html template
		template = self.env.get_template(self.html_file)
		rendered_html = template.render(template_params)
		args = [f"--window-size={dimensions[0]},{dimensions[1]}"]
		if transparent:
			args.append("--default-background-color=00000000")
		return render_html_arglist(rendered_html, args)
	pass

# the schedule item a plugin is given (a timer task's item, or a playlist track); TimerTaskTask is only its content
type TrackType = ScheduleItemBase

@runtime_checkable
class PluginAsync(Protocol):
	"""
	A plugin runs one visit of a track. **Every plugin handles `context.resumed`** and says how in a class attribute, `resume_contract`:
	`"honours"` (a plugin the playlist layer runs: it carries on, or returns at once when carrying on would only repeat what the panel shows) or
	`"ignores"` (a plugin the timer layer runs, which never sets the flag). `test_plugin_resume` fails for a plugin that says neither.
	"""
	@property
	def id(self) -> str:
		...
	@property
	def name(self) -> str:
		...
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> BasicMessage|None:
		...
