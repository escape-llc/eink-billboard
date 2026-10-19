import base64
import copy
import hashlib
import importlib
import os
import json
import re
import logging
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, ReadOnly, TypedDict, cast
from PIL import ImageFont

from ..datasources.data_source import DataSource
from ..utils.file_utils import path_to_file_url
from .schedule_manager import ScheduleManager

class ItemSettingsDict(TypedDict):
	schema: ReadOnly[dict]
	default: ReadOnly[dict]

class ItemInstanceSettingsDict(TypedDict):
	# the properties and lookups of a task's `content`; each property carries its own default
	schema: ReadOnly[dict]

ItemInfoDict = TypedDict('ItemInfoDict', {
	'id': ReadOnly[str],
	'name': ReadOnly[str],
	'version': ReadOnly[str],
	'class': ReadOnly[str],
	'file': ReadOnly[str],
	'module': ReadOnly[str],
	'description': ReadOnly[str],
	'disabled': ReadOnly[bool],
	'features': ReadOnly[list[str]],
	'settings': ReadOnly[ItemSettingsDict],
	'instanceSettings': ReadOnly[ItemInstanceSettingsDict]
})

class CollectInfoDict(TypedDict):
	info: ReadOnly[ItemInfoDict]
	path: ReadOnly[str]

logger = logging.getLogger(__name__)

_LEAF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
def leaf_name(name: str) -> str:
	"""A file's name (no extension) inside a sub-manager's folder. A name is never a path: the sub-manager's root is its owner's to give, not the caller's."""
	if not isinstance(name, str) or not _LEAF.match(name):
		raise ValueError("Not a valid file name.")
	return name

# What a backup holds (#368): the settings, schedules and each plugin's and data source's own files. Not the `schemas` (the code refreshes them at every start) and not the `state` (the panel's last
# refresh: the device's own bookkeeping about *this* panel, wrong on another one). Never the device password (`access`: a restore does not change who owns the device) and never an origin's
# kept answers (`cache-*`: regenerable, and stale by the time they are restored).
BACKUP_AREAS = ("settings", "schedules", "plugins", "datasources")
BACKUP_NEVER = ("settings/access-settings.json",)
BACKUP_CACHE_PREFIX = "cache-"
# a file of a backup is a small JSON document (a storage is a few hundred kilobytes in all)
BACKUP_MAX_FILE_BYTES = 5 * 1024 * 1024

class RestoreFailed(Exception):
	"""A file of a restore could not be written (the ones written before it were put back). `name` is the archive's file name, shown only to the person restoring."""
	def __init__(self, name: str):
		super().__init__("A restore could not write a file.")
		self.name = name

@dataclass(frozen=True)
class BackupFile:
	"""A file name of a backup, taken apart: `area` (settings, schedules, plugins, datasources), `owner` (the plugin's or data source's id; None for the others) and `stem` (the file's name, no extension)."""
	area: str
	owner: str|None
	stem: str

def backup_file(name: Any) -> BackupFile|None:
	"""
	The parts of a backup's file name, or None when a backup may not hold it: not `<area>/<file>.json` (settings, schedules) or `<area>/<id>/<file>.json` (plugins, data sources), a part that is not a
	plain name, the device password, or an origin's kept answers. This is the one place that says what a backup holds, when it is made and again when it is opened.
	"""
	if not isinstance(name, str) or name in BACKUP_NEVER:
		return None
	parts = name.split("/")
	area = parts[0]
	if area not in BACKUP_AREAS or len(parts) != (2 if area in ("settings", "schedules") else 3):
		return None
	file_name = parts[-1]
	if not file_name.endswith(".json") or file_name.startswith(BACKUP_CACHE_PREFIX):
		return None
	try:
		stem = leaf_name(file_name[:-len(".json")])
		owner = leaf_name(parts[1]) if len(parts) == 3 else None
	except ValueError:
		return None
	return BackupFile(area, owner, stem)

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

# the file primitives are in storage_files; these names stay for the tests that exercise them
from .storage_files import load_json as _internal_load, save_json as _internal_save

# settings that moved from one data source to another (`upgrade_settings`, once per storage): (from, to, keys). The Weather's went to the
# OpenWeatherMap API data source that asks the origin for it and the Weather Overlay; the OpenAI Image's key to the OpenAI provider its parts share.
SETTINGS_MOVES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
	("weather", "openweathermap", ("apiKey", "units", "currentCacheHours", "forecastCacheHours", "staleDays")),
	("openai-image", "openai", ("apiKey",)),
)

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
	def __init__(self, moniker: str, loader: LoadFunc, saver: SaveFunc, verify_on_save: bool = False):
		"""`verify_on_save`: `save()` re-reads the content with the loader and compares against that, not the cache (for stores others can edit, like files)."""
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
		self._verify_on_save = verify_on_save
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
	def save(self, hash: str|None, content: dict) -> SaveResult:
		with self._lock:
			if self._content is None or self._verify_on_save:
				# an outside edit is only evicted after the watcher's debounce: for files, trust the disk and never the cache,
				# so a stale cache can not commit over an edit made in that window
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
		super().__init__(moniker, _internal_load, _internal_save, verify_on_save=True)

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
	def file(self, name: str) -> ConfigurationObject:
		"""Another JSON file of this data source (`tokens`), with the same cache, revision and atomic save as the settings."""
		return self._cof.obtain(os.path.join(self.ROOT_PATH, f"{leaf_name(name)}.json"), FileConfiguration)[1]
	def list_files(self, prefix: str) -> list[str]:
		"""The names (no extension) of this data source's JSON files that start with `prefix`; none when it has no folder yet (a folder exists because something was written to it)."""
		leaf_name(prefix)
		if not os.path.isdir(self.ROOT_PATH):
			return []
		return sorted(f[:-5] for f in os.listdir(self.ROOT_PATH) if f.startswith(prefix) and f.endswith(".json") and _LEAF.match(f[:-5]))
	def delete_file(self, name: str) -> None:
		"""Remove one of this data source's JSON files (a list's state, a cache), by name. Its settings are never removed this way."""
		if leaf_name(name) == "settings":
			raise ValueError("The settings are not deleted this way.")
		path = os.path.join(self.ROOT_PATH, f"{name}.json")
		cob = self._cof.obtain(path, FileDeletableConfiguration)[1]
		if isinstance(cob, FileDeletableConfiguration):
			cob.delete()
			return
		# the object was made earlier as a plain file (`file(name)`): the factory hands that one back
		try:
			os.remove(path)
		except FileNotFoundError:
			pass
		cob.evict()

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
		plugin_state_file = os.path.join(self.ROOT_PATH, "state.json")
		# through the cached object, so a reader that holds it does not keep serving the old state
		cob = self._cof.obtain(plugin_state_file, FileDeletableConfiguration)[1]
		with cob:
			_internal_save(plugin_state_file, state)
			cob.evict()
	def delete_state(self):
		if not os.path.exists(self.ROOT_PATH):
			return
		plugin_state_file = os.path.join(self.ROOT_PATH, "state.json")
		cob = self._cof.obtain(plugin_state_file, FileDeletableConfiguration)[1]
		if isinstance(cob, FileDeletableConfiguration):
			# removes the file (if any) and the cached content together
			cob.delete()
			return
		if not os.path.isfile(plugin_state_file):
			return
		try:
			os.remove(plugin_state_file)
		except Exception as e:
			logger.error(f"Error deleting file '{plugin_state_file}': {e}")
		cob.evict()
	def open(self) -> ConfigurationObject:
		"""Loads the settings for a given plugin from its JSON file."""
		plugin_settings_file = self.settings_path()
		cob = self._cof.obtain(plugin_settings_file, FileConfiguration)
		return cob[1]
	def settings_path(self):
		"""Returns the path to the settings.json file for this plugin."""
		return os.path.join(self.ROOT_PATH, "settings.json")
	def file(self, name: str) -> ConfigurationObject:
		"""Another JSON file of this plugin, with the same cache, revision and atomic save as the settings."""
		return self._cof.obtain(os.path.join(self.ROOT_PATH, f"{leaf_name(name)}.json"), FileConfiguration)[1]
	def list_files(self, prefix: str) -> list[str]:
		"""The names (no extension) of this plugin's JSON files that start with `prefix`; none when it has no folder yet."""
		leaf_name(prefix)
		if not os.path.isdir(self.ROOT_PATH):
			return []
		return sorted(f[:-5] for f in os.listdir(self.ROOT_PATH) if f.startswith(prefix) and f.endswith(".json") and _LEAF.match(f[:-5]))
	def delete_file(self, name: str) -> None:
		"""Remove one of this plugin's JSON files (a kept list), by name. Its settings and state are never removed this way."""
		if leaf_name(name) in ("settings", "state"):
			raise ValueError("The settings are not deleted this way.")
		path = os.path.join(self.ROOT_PATH, f"{name}.json")
		cob = self._cof.obtain(path, FileDeletableConfiguration)[1]
		if isinstance(cob, FileDeletableConfiguration):
			cob.delete()
			return
		try:
			os.remove(path)
		except FileNotFoundError:
			pass
		cob.evict()

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
	IMAGES = { "logo.png": "image/png" }
	def image_data_url(self, name: str) -> str|None:
		"""One of our pictures (`static/images`, by a name from IMAGES) as a `data:` address, the only kind a rendered page may show (its Content-Security-Policy); None when it is not there."""
		kind = self.IMAGES.get(name)
		if kind is None:
			return None
		try:
			with open(os.path.join(self.ROOT_PATH, "images", name), "rb") as f:
				return f"data:{kind};base64," + base64.b64encode(f.read()).decode("ascii")
		except OSError:
			return None
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
		# what the device itself keeps between runs (when the panel was last refreshed): not settings, never edited by a person; made by the first write
		self.storage_state = os.path.join(self.STORAGE_PATH, "state")
		# Load environment variables from a .env file if present
		# load_dotenv()
	def __enter__(self):
		self._lock.acquire()
		return self
	def __exit__(self, exc_type, exc_val, exc_tb):
		self._lock.release()
		return False

	@staticmethod
	def needs_seeding(path: str) -> bool:
		"""
		True when there is nothing at `path` to keep: it does not exist, or it is an empty folder. A container's storage is a mounted volume,
		which exists from the start, so "missing" alone would never seed it. A folder with anything in it is somebody's storage: never reset.
		"""
		return not os.path.exists(path) or (os.path.isdir(path) and not os.listdir(path))

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
			cached = list(self._objectMap.values())
		# the files were replaced under the cached objects: none of them may keep serving what it loaded before.
		# Outside the manager's lock, like `watch`, because evicting waits for each object's own lock
		for ox in cached:
			ox.evict()

	def _reset_storage(self):
		"""Copy the NVE storage tree to the STORAGE_PATH. Deploy settings to the STORAGE_PATH."""
		if not os.path.exists(self.STORAGE_PATH):
			raise ValueError(f"STORAGE_PATH {self.STORAGE_PATH}")
		if not os.path.exists(self.NVE_PATH):
			raise ValueError(f"NVE_PATH {self.NVE_PATH}")
		try:
			# base files: schedules and schemas
			shutil.copytree(self.NVE_PATH, self.STORAGE_PATH, dirs_exist_ok=True)
			# git keeps no empty folder, so the factory tree has none for the schedules: without it every layer fails to configure on a new device
			os.makedirs(self.storage_schedules, exist_ok=True)
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
			psettings = info.get("settings", None)
			if psettings == None:
				continue
			settings = psettings.get("default", None)
			if settings == None:
				continue
			self._save_settings(dsm.settings_path(), settings)

	def refresh_schemas(self) -> list[str]:
		"""
		Bring the storage's schema files up to date with the ones shipped (the NVE): a schema describes the code's settings, so it is not the user's to keep, and a
		device that was seeded before a setting existed would otherwise never show it. Only `schemas/*.json` are touched, never a settings document or a schedule.
		Returns the names that were replaced.
		"""
		source = os.path.join(self.NVE_PATH, "schemas")
		if not os.path.isdir(source):
			return []
		os.makedirs(self.storage_schemas, exist_ok=True)
		replaced: list[str] = []
		with self._lock:
			for name in sorted(os.listdir(source)):
				if not name.endswith(".json"):
					continue
				with open(os.path.join(source, name), "rb") as f:
					wanted = f.read()
				target = os.path.join(self.storage_schemas, name)
				try:
					with open(target, "rb") as f:
						if f.read() == wanted:
							continue
				except FileNotFoundError:
					pass
				temp = os.path.join(self.storage_schemas, f".tmp-{name}")
				with open(temp, "wb") as f:
					f.write(wanted)
				os.replace(temp, target)
				replaced.append(name)
		if replaced:
			logger.info(f"Schemas brought up to date: {', '.join(replaced)}")
		return replaced

	def shipped_settings(self, name: str) -> dict:
		"""
		The factory values of a device-wide settings document: the `default` of the schema in the NVE (the shipped copy, which is not the user's to change), by the
		name of the document. `{}` when it has none. What "restore the default" restores, and what a document that is missing or damaged is read as.
		"""
		document = _internal_load(os.path.join(self.NVE_PATH, "schemas", f"{leaf_name(name)}.json"))
		default = document.get("default") if isinstance(document, dict) else None
		return copy.deepcopy(default) if isinstance(default, dict) else {}

	def upgrade_settings(self) -> list[str]:
		"""
		Add the settings a stored document lacks, from the defaults of its schema (the device's system, display and theme) or of its descriptor (a plugin's or a
		data source's settings): a setting added after the storage was seeded would otherwise be in no document, and the form would not show it. Only keys that are
		missing are added (with the default's value, `null` included, so the field is there to fill); a value the user set is never changed, and a document
		that is not there or does not load is left alone. Returns the documents that changed, by their file name.
		"""
		changed: list[str] = []
		def move(source: str, target: str, keys: tuple[str, ...]) -> None:
			"""
			The `keys` of one data source's settings, moved to another's: they are what the user set (the new document holds only its seeded defaults
			before), and they leave the old document, so a second start has nothing to move.
			"""
			src = self.datasource_manager(source).settings_path()
			stored = _internal_load(src) if os.path.isfile(src) else None
			if not isinstance(stored, dict):
				return
			present = [k for k in keys if k in stored]
			if not present:
				return
			dst = self.datasource_manager(target).settings_path()
			there = _internal_load(dst) if os.path.isfile(dst) else {}
			if not isinstance(there, dict):
				return
			_internal_save(dst, { **there, **{ k: copy.deepcopy(stored[k]) for k in present } })
			# out of the old document too: its schema no longer marks a key write-only, so the settings route would send it as it is
			_internal_save(src, { k: v for k, v in stored.items() if k not in present })
			# the names only: a value can be a secret
			logger.info(f"Settings moved from datasources/{source} to datasources/{target}: {', '.join(present)}")
			changed.append(f"datasources/{source}")
			changed.append(f"datasources/{target}")
		def upgrade(path: str, defaults: object, label: str) -> None:
			if not isinstance(defaults, dict) or not os.path.isfile(path):
				return
			stored = _internal_load(path)
			if not isinstance(stored, dict):
				return
			missing = {k: v for k, v in defaults.items() if k not in stored and not k.startswith("_")}
			if not missing:
				return
			_internal_save(path, { **stored, **copy.deepcopy(missing) })
			changed.append(label)
		with self._lock:
			# first, so the defaults below are added to the moved document
			for source, target, keys in SETTINGS_MOVES:
				move(source, target, keys)
			if os.path.isdir(self.storage_schemas):
				for name in sorted(os.listdir(self.storage_schemas)):
					if name.endswith(".json"):
						schema = _internal_load(os.path.join(self.storage_schemas, name)) or {}
						stem = Path(name).stem
						upgrade(os.path.join(self.storage_settings, f"{stem}-settings.json"), schema.get("default"), f"{stem}-settings.json")
			for pinfo in self.enum_plugins():
				declared = pinfo["info"].get("id")
				if declared:
					upgrade(self.plugin_manager(declared).settings_path(), (pinfo["info"].get("settings") or {}).get("default"), f"plugins/{declared}")
			for dinfo in self.enum_datasources():
				declared = dinfo["info"].get("id")
				if declared:
					upgrade(self.datasource_manager(declared).settings_path(), (dinfo["info"].get("settings") or {}).get("default"), f"datasources/{declared}")
		if changed:
			logger.info(f"Settings upgraded with new fields: {', '.join(changed)}")
			# a cached document is the old one
			with self._lock:
				cached = list(self._objectMap.values())
			for ox in cached:
				ox.evict()
		return changed

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
				# a storage seeded before the folder was created by the seeding (git keeps no empty folder) has none: the layers failed to start on it
				self.storage_schedules,
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

	def _save_settings(self, settings_file: str, settings: dict) -> None:
		with self._lock:
			try:
				_internal_save(settings_file, settings)
			except Exception as e:
				# storage reset keeps going; the failure is logged
				logger.error(f"Error saving settings '{settings_file}': {e}")

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

	AREAS = { "schedules": "schedules", "settings": "settings", "schemas": "schemas", "plugins": "plugins", "datasources": "datasources", "state": "state" }
	def area_of(self, path: str|bytes) -> str:
		"""Which part of the storage root a path is in (`schedules`, `settings`, ...), or `other` (including anything outside it)."""
		rel = os.path.relpath(os.fsdecode(path), self.STORAGE_PATH)
		first = rel.replace("\\", "/").split("/", 1)[0]
		return self.AREAS.get(first, "other") if not rel.startswith("..") else "other"

	def watch(self, type: str, moniker: str) -> None:
		"""Evicts the ConfigurationObject for the given moniker from the cache."""
		logger.info(f"ConfigurationManager.watch: type={type} moniker={moniker}")
		if moniker == None:
			return
		# Lock order: the manager's lock is only held to look the object up. Evicting waits for the object's own lock,
		# which `save()` holds across an fsync, and must not stall `obtain()` of every other moniker meanwhile.
		# Nothing takes the manager's lock while holding an object's lock, so no cycle is possible.
		with self._lock:
			ox = self._objectMap.get(moniker, None)
		if ox is not None:
			logger.info(f"ConfigurationManager.watch: evicting moniker={moniker}")
			ox.evict()

	def read_schema(self, schema_name: str) -> dict|None:
		"""The schema document of a device setting (`system`, `display`, `theme`), or None when there is none (or it does not load)."""
		if schema_name == None:
			raise ValueError("schema_name cannot be None")
		return _internal_load(os.path.join(self.storage_schemas, f"{leaf_name(schema_name)}.json"))

	def plugin_manager(self, plugin_id: str) -> PluginConfigurationManager:
		"""Returns a PluginConfigurationManager for the given plugin_id."""
		if plugin_id == None:
			raise ValueError("plugin_id cannot be None")
		with self._lock:
			manager = PluginConfigurationManager(self.storage_plugins, plugin_id, self)
			return manager

	def datasource_manager(self, datasource_id: str) -> DatasourceConfigurationManager:
		"""Returns a DatasourceConfigurationManager for the given datasource_id."""
		if datasource_id == None:
			raise ValueError("datasource_id cannot be None")
		with self._lock:
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

	def state_file(self, name: str) -> ConfigurationObject:
		"""A JSON file of the device's own state (`refresh`), by name, with the same cache, revision and atomic save as the settings. The folder is made by the first save."""
		return self.obtain(os.path.join(self.storage_state, f"{leaf_name(name)}.json"), FileConfiguration)[1]

	# --- backup and restore (#368). The archive is made and opened by `utils/backup_archive.py`, which knows no storage; what a backup may hold is decided here, the only code that
	# touches the storage root, and a restore writes by name through the objects the rest of the code reads through.

	def backup_files(self) -> dict[str, bytes]:
		"""
		The files of a backup: `{ "settings/system-settings.json": bytes, ... }`, every JSON file of the settings, schedules, plugins and data sources except what `backup_file` leaves out
		(the device password, an origin's kept answers). A file that is not a JSON object (damaged) or too large is left out and logged by name. The files are read while the device runs: each is
		whole (they are written atomically), the set is not a snapshot.
		"""
		found: dict[str, bytes] = {}
		for area in BACKUP_AREAS:
			root = os.path.join(self.STORAGE_PATH, area)
			for folder, dirs, names in os.walk(root, followlinks=False):
				dirs.sort()
				for file_name in sorted(names):
					path = os.path.join(folder, file_name)
					name = os.path.relpath(path, self.STORAGE_PATH).replace("\\", "/")
					if backup_file(name) is None or os.path.islink(path):
						continue
					try:
						if os.path.getsize(path) > BACKUP_MAX_FILE_BYTES:
							raise ValueError("too large")
						with open(path, "rb") as fx:
							content = fx.read()
						if not isinstance(json.loads(content), dict):
							raise ValueError("not an object")
					except (OSError, ValueError) as e:
						logger.warning(f"The backup leaves out '{name}': {type(e).__name__}.")
						continue
					found[name] = content
		return found

	def backup_documents(self, files: Mapping[str, bytes]) -> tuple[dict[str, dict], list[str]]:
		"""
		The documents of an opened archive: `(documents, left out)`. A name a backup may not hold, a file that is not a JSON object, one that is not UTF-8 JSON: left out by name (the names are the
		archive's, so they are listed only for the person who opened it, never logged with a value).
		"""
		documents: dict[str, dict] = {}
		left_out: list[str] = []
		for name, content in files.items():
			try:
				document = json.loads(content.decode("utf-8")) if backup_file(name) is not None and len(content) <= BACKUP_MAX_FILE_BYTES else None
			except (UnicodeDecodeError, ValueError):
				document = None
			if isinstance(document, dict):
				documents[name] = document
			else:
				left_out.append(name)
		return documents, sorted(left_out)

	def backup_target(self, name: str) -> ConfigurationObject|None:
		"""
		The configuration object a backup's file belongs to, or None when this device has no such place for it (a plugin or data source that is not installed). A plugin's or data source's folder
		is the **declared** id of the descriptor, never the archive's text.
		"""
		parsed = backup_file(name)
		if parsed is None:
			return None
		if parsed.area == "settings":
			return self.obtain(self.settings_manager().settings_path(parsed.stem.removesuffix("-settings")), FileConfiguration)[1]
		if parsed.area == "schedules":
			return self.obtain(os.path.join(self.storage_schedules, f"{parsed.stem}.json"), FileConfiguration)[1]
		declared = self._declared(self.enum_plugins() if parsed.area == "plugins" else self.enum_datasources(), parsed.owner)
		if declared is None:
			return None
		os.makedirs(self.storage_plugins if parsed.area == "plugins" else self.storage_ds, exist_ok=True)
		folder = (self.plugin_manager(declared) if parsed.area == "plugins" else self.datasource_manager(declared)).ROOT_PATH
		return self.obtain(os.path.join(folder, f"{parsed.stem}.json"), FileConfiguration)[1]

	@staticmethod
	def _declared(items: list[CollectInfoDict], ident: str|None) -> str|None:
		for item in items:
			declared = item["info"].get("id")
			if isinstance(declared, str) and declared == ident:
				return declared
		return None

	def evict_all(self) -> None:
		"""Forget every cached configuration object, so the next read comes from the files (after many files changed at once, where `watch` would evict one at a time)."""
		with self._lock:
			objects = list(self._objectMap.values())
		for cob in objects:
			cob.evict()

	def write_backup(self, documents: Mapping[str, dict]) -> list[str]:
		"""
		Write the documents of a restore over the storage, by name, each atomically. Nothing is deleted. When one fails, the ones already written are put back from the copies taken before (a file
		that did not exist is removed again), so the storage is never left half restored, and `RestoreFailed` says which one by name. The names were checked (`backup_file`) and the documents validated by
		the caller. Returns the names written.
		"""
		done: list[tuple[ConfigurationObject, dict|None]] = []
		written: list[str] = []
		try:
			for name, document in documents.items():
				target = self.backup_target(name)
				if target is None:
					continue
				with target:
					previous = _internal_load(target.moniker) if os.path.isfile(target.moniker) else None
					_internal_save(target.moniker, document)
					done.append((target, previous))
					target.evict()
				written.append(name)
		except Exception as e:
			logger.error(f"A restore could not write '{name}' ({type(e).__name__}): the files written so far are put back.")
			for target, previous in reversed(done):
				try:
					with target:
						if previous is not None:
							_internal_save(target.moniker, previous)
						elif os.path.isfile(target.moniker):
							os.remove(target.moniker)
						target.evict()
				except Exception:
					logger.error("A file written by a restore could not be put back.", exc_info=True)
			raise RestoreFailed(name) from None
		return written

	def static_manager(self) -> StaticConfigurationManager:
		"""Create a StaticConfigurationManager bound to the root path."""
		manager = StaticConfigurationManager(self.static_path)
		return manager

	def _collect_info(self, folder: str, info_file_name: str) -> list[CollectInfoDict]:
		# Iterate over all XXX folders
		item_list: list[CollectInfoDict] = []
		path = os.path.join(self.ROOT_PATH, folder)
		logger.debug(f"collect_info: {path}")
		for item in sorted(os.listdir(path)):
			item_path = os.path.join(self.ROOT_PATH, folder, item)
			if os.path.isdir(item_path) and item != "__pycache__":
				# Check if the XXX-info.json file exists
				info_file = os.path.join(item_path, info_file_name)
				if os.path.isfile(info_file):
					logger.debug(f"collect info: {info_file}")
					try:
						with open(info_file) as f:
							item_info: ItemInfoDict = json.load(f)
					except Exception as e:
						logger.error(f"Cannot read descriptor '{info_file}' (folder '{item}'), skipping it: {e}")
						continue
					if not isinstance(item_info, dict):
						logger.error(f"Descriptor '{info_file}' (folder '{item}') is not a JSON object, skipping it.")
						continue
					item_list.append({ "info": item_info, "path": item_path })
		return item_list

	def enum_plugins(self) -> list[CollectInfoDict]:
		"""Reads the plugin-info.json config JSON from each plugin folder. Excludes the base plugin."""
		# Iterate over all plugin folders
		plugins_list = self._collect_info("plugins", "plugin-info.json")
		return plugins_list

	def datasource_render_dir(self, folder: str) -> str:
		"""The `render` folder of a data source (its page templates), by the name of its folder under `datasources`: from the source root, not from where the module happens to be."""
		return os.path.join(self.ROOT_PATH, "datasources", leaf_name(folder), "render")
	def enum_datasources(self) -> list[CollectInfoDict]:
		"""Reads the datasource-info.json config JSON from each datasource folder. Excludes the base datasource."""
		# Iterate over all plugin folders
		datasources_list = self._collect_info("datasources", "datasource-info.json")
		self._resolve_tokens(datasources_list)
		return datasources_list

	@staticmethod
	def _resolve_tokens(items: list[CollectInfoDict]) -> None:
		"""
		A property that says `tokensFrom: [ids]` may use the fields those data-only sources list (their descriptor's `tokens`): they are copied into the
		property's own `tokens`, so the form (which shows them) and the server (which checks a text against them) read one list, supplied by the data behind it.
		"""
		supplied: dict[str, list] = {}
		for item in items:
			info = cast(dict, item["info"])
			if isinstance(info.get("tokens"), list):
				supplied[str(info.get("id"))] = info["tokens"]
		for item in items:
			schema = (cast(dict, item["info"]).get("instanceSettings") or {}).get("schema") or {}
			for prop in schema.get("properties") or []:
				if isinstance(prop, dict) and isinstance(prop.get("tokensFrom"), list):
					merged: dict[str, Any] = {}
					for source_id in prop["tokensFrom"]:
						for token in supplied.get(str(source_id), []):
							if isinstance(token, dict) and isinstance(token.get("name"), str):
								merged.setdefault(token["name"], copy.deepcopy(token))
					prop["tokens"] = list(merged.values())

	def _resolve(self, info_path:str, info: ItemInfoDict) -> Any|None:
		info_id = cast(str, info.get("id"))
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
		except Exception as e:
			# a module that fails for any reason (syntax error, import-time exception) costs only that plugin
			logger.error(f"Failed to load '{info_id}' (module '{info_module}'): {e}")
			return None

	def create_plugin(self, info: CollectInfoDict) -> Any|None:
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

	def load_plugins(self, infos: list[CollectInfoDict]) -> Mapping[str, Any]:
		"""Take the result of enum_plugins() and instantiate the plugin objects."""
		plugin_map = {}
		for info in infos:
			info_info = info["info"]
			plugin_id = info_info.get("id")
			try:
				plugin = self.create_plugin(info)
			except Exception as e:
				logger.error(f"Failed to create plugin '{plugin_id}', skipping it: {e}", exc_info=True)
				continue
			if plugin:
				plugin_map[plugin_id] = plugin
			pass
		return plugin_map
	
	def create_datasource(self, info: CollectInfoDict) -> DataSource|None:
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

	def load_datasources(self, infos: list[CollectInfoDict]) -> Mapping[str, DataSource]:
		"""Take the result of enum_datasources() and instantiate the datasource objects."""
		datasource_map = {}
		for info in infos:
			info_info = info["info"]
			info_id = info_info.get("id")
			try:
				datasource = self.create_datasource(info)
			except Exception as e:
				logger.error(f"Failed to create datasource '{info_id}', skipping it: {e}", exc_info=True)
				continue
			if datasource:
				# Create an instance of the item class and add it to the dictionary
				datasource_map[info_id] = datasource
		return datasource_map

	def load_routers(self, infos: list[CollectInfoDict]) -> Mapping[str, Any]:
		"""Take the result of enum_X() and resolve the optional web API routers contributed by plugins/datasources."""
		router_map = {}
		for info in infos:
			info_info = info["info"]
			info_path = info["path"]
			info_id = info_info.get("id")
			info_name = info_info.get("name")
			if info_info.get("disabled", False):
				logger.info(f"'{info_name}' (ID: {info_id}) is disabled; skipping load.")
				continue
			router_info = cast(ItemInfoDict | None, info_info.get("router", None))
			if router_info is None:
				continue
			router = self._resolve(info_path, router_info)
			if router:
				router_map[info_id] = router
		return router_map