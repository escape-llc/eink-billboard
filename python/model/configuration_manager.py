import hashlib
import importlib
import os
import json
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Protocol, cast
from PIL import ImageFont

from ..datasources.data_source import DataSource
from ..utils.file_utils import path_to_file_url
from .schedule_manager import ScheduleManager

logger = logging.getLogger(__name__)

HASH_KEY = "_rev"
ID_KEY = "_id"

def create_hash(data:dict) -> str:
	"""
	Computes a SHA256 hash of a JSON-serializable object and returns it.

	This function first removes any existing HASH_KEY key to ensure the hash is
	always based purely on the object's content.
	Args:
		data (dict): The dictionary to process.
	Returns:
		str: The computed SHA256 hash in hexadecimal format.
	"""
	for_hash = data.copy()

	# Remove the existing hash key if it is present.
	# The `pop` method with a default value of `None` prevents a KeyError.
	for_hash.pop(HASH_KEY, None)

	# Serialize the cleaned data into a canonical string.
	# `sort_keys=True` ensures consistent key order.
	# `separators=(',', ':')` removes whitespace for a compact string.
	canonical_string = json.dumps(
			for_hash,
			sort_keys=True,
			separators=(',', ':')
	)

	byte_string = canonical_string.encode('utf-8')
	object_hash = hashlib.sha256(byte_string).hexdigest()

	return object_hash

def _internal_load(file_path: str) -> dict|None:
	if os.path.isfile(file_path):
		try:
			with open(file_path, 'r') as fx:
				data = json.load(fx)
				return data
		except Exception as e:
			logger.error(f"Error loading file '{file_path}': {e}")
			return None
	return None

def _internal_save(file_path: str, data: dict) -> None:
	try:
		if file_path is None:
			raise ValueError("file_path cannot be None")
		if data is None:
			raise ValueError("data cannot be None")
		with open(file_path, 'w') as fx:
			json.dump(data, fx, indent=2)
#			logger.debug(f"File '{file_path}' saved successfully.")
	except Exception as e:
		logger.error(f"Error saving file '{file_path}': {e}")

type LoadFunc = Callable[[str], dict|None]
type SaveFunc = Callable[[str, dict], None]
type HashFunc = Callable[[dict], str]
type GetResult = tuple[str|None, dict|None]
type SaveResult = tuple[bool, str|None]

class ConfigurationObject:
	"""Configuration holder that lazily loads content and persists
	changes via the provided callables. Methods are protected by a
	per-instance reentrant lock to make operations thread-safe.
	"""
	def __init__(self, moniker: str, loader: LoadFunc, saver: SaveFunc):
		if moniker == None:
			raise ValueError("moniker cannot be None")
		if loader == None:
			raise ValueError("loader cannot be None")
		if saver == None:
			raise ValueError("saver cannot be None")
		self.moniker = moniker
		self._content: dict|None = None
		self._hash: str|None = None
		self._loader = loader
		self._saver = saver
		# Use RLock so the same thread can re-enter safely if needed
		self._lock = threading.RLock()
	def __enter__(self):
		self._lock.acquire()
		return self
	def __exit__(self, exc_type, exc_val, exc_tb):
		self._lock.release()
		return False
	def get(self) -> GetResult:
		with self._lock:
			if self._content is None:
				self._content = self._loader(self.moniker)
				self._hash = create_hash(self._content) if self._content is not None else None
			return (self._hash, self._content.copy() if self._content is not None else None)
	def save(self, hash: str, content: dict) -> SaveResult:
		with self._lock:
			if self._content is None:
				self._content = self._loader(self.moniker)
				self._hash = create_hash(self._content) if self._content is not None else None
			if self._hash != hash:
				return (False, None)
			# Persist new state and force reload on next get()
			self._saver(self.moniker, content)
			nhash = create_hash(content)
			self._content = None
			self._hash = None
			return (True, nhash)
	def evict(self) -> None:
		with self._lock:
			self._content = None
			self._hash = None

class FileConfiguration(ConfigurationObject):
	def __init__(self, moniker):
		super().__init__(moniker, _internal_load, _internal_save)

class FileDeletableConfiguration(FileConfiguration):
	def __init__(self, moniker):
		super().__init__(moniker)
	def delete(self) -> None:
		with self._lock:
			if os.path.isfile(self.moniker):
				try:
					os.remove(self.moniker)
					logger.debug(f"Deleted file: {self.moniker}")
				except Exception as e:
					logger.error(f"Error deleting file '{self.moniker}': {e}")
			self._content = None
			self._hash = None

class ConfigurationObjectFactory(Protocol):
	def obtain(self, moniker: str, ctor: type[FileConfiguration]) -> tuple[bool, ConfigurationObject]:
		...

class DatasourceConfigurationManager:
	"""
	Manage settings, state, etc. for a datasource.
	Rooted at the "datasources/<datasource_id>" folder in storage.
	"""
	def __init__(self, root_path:str, datasource_id:str, cof: ConfigurationObjectFactory):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if datasource_id == None:
			raise ValueError("datasource_id cannot be None")
		if cof == None:
			raise ValueError("cof cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		self.datasource_id = datasource_id
		self.ROOT_PATH = os.path.join(root_path, self.datasource_id)
		self._cof = cof
	def settings_path(self):
		"""Returns the path to the settings.json file for this plugin."""
		return os.path.join(self.ROOT_PATH, "settings.json")
	def open(self) -> ConfigurationObject:
		"""Loads the settings for a given datasource from its JSON file."""
		plugin_settings_file = self.settings_path()
		cob = self._cof.obtain(plugin_settings_file, FileConfiguration)
		return cob[1]

class PluginConfigurationManager:
	"""
	Manage settings, state, etc. for a plugin.
	Rooted at the "plugins/<plugin_id>" folder in storage.
	"""
	def __init__(self, root_path:str, plugin_id:str, cof: ConfigurationObjectFactory):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if plugin_id == None:
			raise ValueError("plugin_id cannot be None")
		if cof == None:
			raise ValueError("cof cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		self.plugin_id = plugin_id
		self.ROOT_PATH = os.path.join(root_path, self.plugin_id)
		self._cof = cof
#		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")
	def open_state(self) -> ConfigurationObject:
		"""Loads the state for a given plugin from its JSON file."""
		plugin_state_file = os.path.join(self.ROOT_PATH, "state.json")
		cob = self._cof.obtain(plugin_state_file, FileDeletableConfiguration)
		return cob[1]
	def save_state(self, state):
		"""Saves the state for a given plugin to its JSON file."""
		if not os.path.exists(self.ROOT_PATH):
			raise ValueError(f"Directory {self.ROOT_PATH} does not exist.")
		plugin_state_file = os.path.join(self.ROOT_PATH, "state.json")
		_internal_save(plugin_state_file, state)
	def delete_state(self):
		if not os.path.exists(self.ROOT_PATH):
			return
		plugin_state_file = os.path.join(self.ROOT_PATH, "state.json")
		if not os.path.isfile(plugin_state_file):
			return
		try:
			os.remove(plugin_state_file)
		except Exception as e:
			logger.error(f"Error deleting file '{plugin_state_file}': {e}")
	def open(self) -> ConfigurationObject:
		"""Loads the settings for a given plugin from its JSON file."""
		plugin_settings_file = self.settings_path()
		cob = self._cof.obtain(plugin_settings_file, FileConfiguration)
		return cob[1]
	def settings_path(self):
		"""Returns the path to the settings.json file for this plugin."""
		return os.path.join(self.ROOT_PATH, "settings.json")

class SettingsConfigurationManager:
	"""
	Manage system-level settings, e.g. system, display (not plugins).
	Rooted at the "settings" folder in storage.
	"""
	def __init__(self, root_path:str, cof: ConfigurationObjectFactory):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		if cof == None:
			raise ValueError("cof cannot be None")
		self.ROOT_PATH = root_path
		self._cof = cof
#		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")
	def open(self, settings: str) -> ConfigurationObject:
		"""Loads the settings for a given settings from its JSON file."""
		settings_file = self.settings_path(settings)
		cob = self._cof.obtain(settings_file, FileConfiguration)
		return cob[1]
	def settings_path(self, settings: str):
		"""Returns the path to the JSON file for this settings."""
		return os.path.join(self.ROOT_PATH, f"{settings}-settings.json")

FONT_FAMILIES = {
	"Dogica": [{
		"font-weight": "normal",
		"file": "dogicapixel.ttf"
	},{
		"font-weight": "bold",
		"file": "dogicapixelbold.ttf"
	}],
	"Jost": [{
		"font-weight": "normal",
		"file": "Jost.ttf"
	},{
		"font-weight": "bold",
		"file": "Jost-SemiBold.ttf"
	}],
	"Napoli": [{
		"font-weight": "normal",
		"file": "Napoli.ttf"
	}],
	"DS-Digital": [{
		"font-weight": "normal",
		"file": os.path.join("DS-DIGI", "DS-DIGI.TTF")
	}]
}
class StaticConfigurationManager:
	"""
	Rooted at the "static" folder; manages static resources like fonts and render assets.
	"""
	def __init__(self, root_path):
		if root_path == None:
			raise ValueError("root_path cannot be None")
		if not os.path.exists(root_path):
			raise ValueError(f"root_path {root_path} does not exist.")
		self.ROOT_PATH = root_path
#		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")
	def enum_fonts(self):
		fonts_list = []
		for font_family, variants in FONT_FAMILIES.items():
			for variant in variants:
				fonts_list.append({
					"font_family": font_family,
					"url": path_to_file_url(os.path.join(self.ROOT_PATH, "fonts", variant["file"])),
					"font_weight": variant.get("font-weight", "normal"),
					"font_style": variant.get("font-style", "normal"),
				})
		return fonts_list
	def get_font(self, font_name: str, font_size=50, font_weight="normal"):
		if font_name in FONT_FAMILIES:
			font_variants = FONT_FAMILIES[font_name]

			font_entry = next((entry for entry in font_variants if entry["font-weight"] == font_weight), None)
			if font_entry is None:
				font_entry = font_variants[0]  # Default to first available variant

			if font_entry:
				font_path = os.path.join(self.ROOT_PATH, "fonts", font_entry["file"])
				return ImageFont.truetype(font_path, font_size)
		raise ValueError(f"Font not found: font_name={font_name}, font_weight={font_weight}")

class ConfigurationManager(ConfigurationObjectFactory):
	"""
	Manage the paths used for configuration and working storage.
	Act as a factory for other "sub" managers.
	"""
	def __init__(self, source_path:str|None = None, storage_path:str|None = None, nve_path:str|None = None):
		self._lock = threading.RLock()
		self._objectMap: dict[str, ConfigurationObject] = {}
		# Source path is the python directory
		# Storage path is where working storage is hosted (SHOULD be OUTSIDE the source tree)
		# NVE path (Non-Volatile Environment) is the source used to initialize Storage
		if source_path != None:
			self.ROOT_PATH = source_path
#			logger.debug(f"Provided source_path: {self.ROOT_PATH}")
		else:
			# NOTE: this is based on the current folder structure and location of this file
			self.ROOT_PATH = os.path.dirname(os.path.abspath(__file__))
			pobj = Path(self.ROOT_PATH)
			self.ROOT_PATH = str(pobj.parent)
#			logger.debug(f"Calculated source_path: {self.ROOT_PATH}")

		self.static_path = os.path.join(self.ROOT_PATH, "static")
#		logger.debug(f"ROOT_PATH: {self.ROOT_PATH}")
		# File path for storing the current image being displayed
#		self.current_image_file = os.path.join(self.ROOT_PATH, "static", "images", "current_image.png")
		# Directory path for storing plugin instance images
#		self.plugin_image_dir = os.path.join(self.ROOT_PATH, "static", "images", "plugins")
#		logger.debug(f"plugin_image_dir: {self.plugin_image_dir} storage: {self.STORAGE_PATH}")

		# Storage path is for storage; MUST BE external to the ROOT_PATH
		if storage_path != None:
			# points directly to ".storage" folder
			self.STORAGE_PATH = storage_path
#			logger.debug(f"Provided storage_path: {self.STORAGE_PATH}")
		else:
			# sibling ".storage" folder with ROOT_PATH
			pobj = Path(self.ROOT_PATH)
			self.STORAGE_PATH = os.path.join(pobj.parent, ".storage")
#			logger.debug(f"Calculated storage_path: {self.STORAGE_PATH}")

		if nve_path != None:
			self.NVE_PATH = nve_path
#			logger.debug(f"Provided nve_path: {nve_path}")
		else:
			self.NVE_PATH = os.path.join(self.ROOT_PATH, "storage")
#			logger.debug(f"Calculated nve_path: {self.NVE_PATH}")

		self.storage_plugins = os.path.join(self.STORAGE_PATH, "plugins")
		self.storage_ds = os.path.join(self.STORAGE_PATH, "datasources")
		self.storage_schedules = os.path.join(self.STORAGE_PATH, "schedules")
		self.storage_settings = os.path.join(self.STORAGE_PATH, "settings")
		self.storage_schemas = os.path.join(self.STORAGE_PATH, "schemas")
		# Load environment variables from a .env file if present
		# load_dotenv()
	def __enter__(self):
		self._lock.acquire()
		return self
	def __exit__(self, exc_type, exc_val, exc_tb):
		self._lock.release()
		return False

	def hard_reset(self):
		"""Deletes all storage folders and recreates them."""
		with self._lock:
			if os.path.exists(self.STORAGE_PATH):
				try:
					for item in os.listdir(self.STORAGE_PATH):
						item_path = os.path.join(self.STORAGE_PATH, item)
						if os.path.isfile(item_path):
								os.remove(item_path)  # Remove files
						elif os.path.isdir(item_path):
								shutil.rmtree(item_path)
					logger.info(f"HardReset '{self.STORAGE_PATH}' all contents deleted successfully.")
				except OSError as e:
					logger.error(f"HardReset: {self.STORAGE_PATH} : {e.strerror}")
			else:
				logger.debug(f"HardReset '{self.STORAGE_PATH}' does not exist.")

			self.ensure_folders()
			self._reset_storage()
			self._reset_plugins()
			self._reset_datasources()

	def _reset_storage(self):
		"""Copy the NVE storage tree to the STORAGE_PATH. Deploy settings to the STORAGE_PATH."""
		if not os.path.exists(self.STORAGE_PATH):
			raise ValueError(f"STORAGE_PATH {self.STORAGE_PATH}")
		if not os.path.exists(self.NVE_PATH):
			raise ValueError(f"NVE_PATH {self.NVE_PATH}")
		try:
			# base files: schedules and schemas
			shutil.copytree(self.NVE_PATH, self.STORAGE_PATH, dirs_exist_ok=True)
			# extract settings: system, display
			settings_files = os.listdir(self.storage_schemas)
			for file in settings_files:
				schema_path = os.path.join(self.storage_schemas, file)
				basename = Path(schema_path).stem
				settings_path = os.path.join(self.storage_settings, f"{basename}-settings.json")
				settings = {}
				with open(schema_path) as f:
					schema = json.load(f)
					defx = schema.get("default", None)
					if defx is not None:
						settings = defx
				with open(settings_path, 'w') as fx:
					json.dump(settings, fx, indent=2)

			logger.info(f"ResetStorage '{self.STORAGE_PATH}' all contents copied successfully.")
		except OSError as e:
				logger.error(f"ResetStorage: {self.STORAGE_PATH} : {e.strerror}")
		pass

	def _reset_plugins(self):
		plugins = self.enum_plugins()
		for pinfo in plugins:
			info = pinfo["info"]
			plugin_id = info.get("id")
			pcm = self.plugin_manager(plugin_id)
			self._ensure_folders(self.storage_plugins, plugin_id)
			psettings = info.get("settings", None)
			if psettings == None:
				continue
			settings = psettings.get("default", None)
			if settings == None:
				continue
			self._save_settings(pcm.settings_path(), settings)

	def _reset_datasources(self):
		dss = self.enum_datasources()
		for pinfo in dss:
			info = pinfo["info"]
			item_id = info.get("id")
			dsm = self.datasource_manager(item_id)
			self._ensure_folders(self.storage_ds, item_id)
			psettings = info.get("settings", None)
			if psettings == None:
				continue
			settings = psettings.get("default", None)
			if settings == None:
				continue
			self._save_settings(dsm.settings_path(), settings)

	def ensure_folders(self):
		"""Ensures that necessary directories exist.  Does not consider files."""
		with self._lock:
			if not os.path.exists(self.ROOT_PATH):
				raise ValueError(f"ROOT_PATH {self.ROOT_PATH} does not exist.")
			if not os.path.exists(self.NVE_PATH):
				raise ValueError(f"NVE_PATH {self.NVE_PATH} does not exist.")
			directories = [
				self.STORAGE_PATH,
				self.storage_plugins,
				self.storage_ds,
				self.storage_settings,
			]
			for directory in directories:
				if not os.path.exists(directory):
					try:
						os.makedirs(directory)
						logger.debug(f"EnsureFolders Created: {directory}")
					except Exception as e:
						logger.error(f"EnsureFolders {directory}: {e}")
				else:
					logger.debug(f"EnsureFolders exists: {directory}")

	def _ensure_folders(self, path: str, id: str) -> None:
		with self._lock:
			try:
				final_path = os.path.join(path, id)
				os.makedirs(final_path, exist_ok=True)
				logger.debug(f"Created: {final_path}")
			except Exception as e:
				logger.error(f"Error: {path}: {e}")

	def _save_settings(self, settings_file: str, settings: dict) -> None:
		with self._lock:
			_internal_save(settings_file, settings)

	def find(self, moniker: str) -> ConfigurationObject|None:
		"""Find a ConfigurationObject for the given moniker, or None if not found."""
		if moniker == None:
			raise ValueError("moniker cannot be None")
		with self._lock:
			ox = self._objectMap.get(moniker, None)
			return ox

	def obtain(self, moniker: str, ctor: type[FileConfiguration]) -> tuple[bool, ConfigurationObject]:
		"""Obtain a ConfigurationObject for the given moniker, and ctor."""
		if moniker == None:
			raise ValueError("moniker cannot be None")
		if ctor == None:
			raise ValueError("ctor cannot be None")
		with self._lock:
			ox = self._objectMap.get(moniker, None)
			if ox is not None:
				return (False, ox)
			obj = ctor(moniker)
			self._objectMap[moniker] = obj
			return (True, obj)

	def watch(self, type: str, moniker: str) -> None:
		"""Evicts the ConfigurationObject for the given moniker from the cache."""
		logger.info(f"ConfigurationManager.watch: type={type} moniker={moniker}")
		if moniker == None:
			return
		with self._lock:
			ox = self._objectMap.get(moniker, None)
			if ox is not None:
				logger.info(f"ConfigurationManager.watch: evicting moniker={moniker}")
				ox.evict()

	def schema_path(self, schema_name: str) -> str:
		"""Returns the path to the JSON schema file for the given schema_name."""
		if schema_name == None:
			raise ValueError("schema_name cannot be None")
		schema_file = os.path.join(self.storage_schemas, f"{schema_name}.json")
		return schema_file

	def plugin_manager(self, plugin_id: str) -> PluginConfigurationManager:
		"""Returns a PluginConfigurationManager for the given plugin_id."""
		if plugin_id == None:
			raise ValueError("plugin_id cannot be None")
		with self._lock:
			self._ensure_folders(self.storage_plugins, plugin_id)
			manager = PluginConfigurationManager(self.storage_plugins, plugin_id, self)
			return manager

	def datasource_manager(self, datasource_id: str) -> DatasourceConfigurationManager:
		"""Returns a DatasourceConfigurationManager for the given datasource_id."""
		if datasource_id == None:
			raise ValueError("datasource_id cannot be None")
		with self._lock:
			self._ensure_folders(self.storage_ds, datasource_id)
			manager = DatasourceConfigurationManager(self.storage_ds, datasource_id, self)
			return manager

	def schedule_manager(self) -> ScheduleManager:
		"""Create a ScheduleManager bound to the schedule storage folder."""
		manager = ScheduleManager(self.storage_schedules)
		return manager

	def settings_manager(self) -> SettingsConfigurationManager:
		"""Create a SettingsConfigurationManager bound to settings storage folder."""
		manager = SettingsConfigurationManager(self.storage_settings, self)
		return manager

	def static_manager(self) -> StaticConfigurationManager:
		"""Create a StaticConfigurationManager bound to the root path."""
		manager = StaticConfigurationManager(self.static_path)
		return manager

	def _collect_info(self, folder: str, info_file_name: str) -> list:
		# Iterate over all XXX folders
		item_list = []
		path = os.path.join(self.ROOT_PATH, folder)
		logger.debug(f"collect_info: {path}")
		for item in sorted(os.listdir(path)):
			item_path = os.path.join(self.ROOT_PATH, folder, item)
			if os.path.isdir(item_path) and item != "__pycache__":
				# Check if the XXX-info.json file exists
				info_file = os.path.join(item_path, info_file_name)
				if os.path.isfile(info_file):
					logger.debug(f"plugin info {info_file}")
					with open(info_file) as f:
						item_info = json.load(f)
					item_list.append({ "info":item_info, "path":item_path })
		return item_list

	def enum_plugins(self) -> list:
		"""Reads the plugin-info.json config JSON from each plugin folder. Excludes the base plugin."""
		# Iterate over all plugin folders
		plugins_list = self._collect_info("plugins", "plugin-info.json")
		return plugins_list

	def enum_datasources(self) -> list:
		"""Reads the datasource-info.json config JSON from each datasource folder. Excludes the base datasource."""
		# Iterate over all plugin folders
		datasources_list = self._collect_info("datasources", "datasource-info.json")
		return datasources_list

	def _resolve(self, info_path:str, info: dict) -> Any|None:
		info_id = info.get("id")
		info_file = cast(str, info.get("file"))
		info_module = cast(str, info.get("module"))
		info_class = cast(str, info.get("class"))
		module_path = os.path.join(info_path, info_file)
		if not os.path.exists(module_path):
			logger.error(f"No module path '{module_path}' for '{info_id}', skipping.")
			return None
		try:
			module = importlib.import_module(info_module)
			item_class = getattr(module, info_class, None)
			return item_class
		except ImportError as e:
			logger.error(f"Failed to import module '{info_module}': {e}")
			return None

	def create_plugin(self, info: dict) -> Any|None:
		info_info = info["info"]
		info_path = cast(str, info["path"])
		info_id = info_info.get("id")
		info_name = cast(str, info_info.get("name"))
		if info_info.get("disabled", False):
			logger.info(f"Plugin '{info_name}' (ID: {info_id}) is disabled; skipping load.")
			return None
		plugin_class = self._resolve(info_path, info_info)
		if plugin_class:
			return plugin_class(info_id, info_name)
		return None

	def load_plugins(self, infos: list[dict]) -> dict:
		"""Take the result of enum_plugins() and instantiate the plugin objects."""
		plugin_map = {}
		for info in infos:
			plugin = self.create_plugin(info)
			info_info = info["info"]
			plugin_id = info_info.get("id")
			if plugin:
				plugin_map[plugin_id] = plugin
			pass
		return plugin_map
	
	def create_datasource(self, info: dict) -> DataSource|None:
		info_info = info["info"]
		info_path = info["path"]
		info_id = info_info.get("id")
		info_name = info_info.get("name")
		if info_info.get("disabled", False):
			logger.info(f"Item '{info_name}' (ID: {info_id}) is disabled; skipping load.")
			return None
		ds_class = self._resolve(info_path, info_info)
		if ds_class:
			return ds_class(info_id, info_name)
		return None

	def load_datasources(self, infos: list[dict]) -> dict:
		"""Take the result of enum_datasources() and instantiate the datasource objects."""
		datasource_map = {}
		for info in infos:
			datasource = self.create_datasource(info)
			info_info = info["info"]
			info_id = info_info.get("id")
			if datasource:
				# Create an instance of the item class and add it to the dictionary
				datasource_map[info_id] = datasource
		return datasource_map

	def load_blueprints(self, infos: list[dict]) -> dict:
		"""Take the result of enum_X() and resolve the blueprints."""
		blueprint_map = {}
		for info in infos:
			info_info = info["info"]
			info_path = info["path"]
			info_id = info_info.get("id")
			info_name = info_info.get("name")
			if info_info.get("disabled", False):
				logger.info(f"'{info_name}' (ID: {info_id}) is disabled; skipping load.")
				continue
			blueprint_info = info_info.get("blueprint", None)
			if blueprint_info is None:
				continue
			blueprint_class = self._resolve(info_path, blueprint_info)
			if blueprint_class:
				# Create an instance of the blueprint class and add it to the blueprint_classes dictionary
				blueprint_map[info_id] = blueprint_class
			pass
		return blueprint_map