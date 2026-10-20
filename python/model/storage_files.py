"""
The only code that reads and writes the JSON files of the storage root. Everything else asks the configuration manager (`python/model/configuration_manager.py`)
and its sub-managers, which are built by their owner with a root of their own (the chain of trust on paths); `test_storage_access` fails on any other module that touches files.
"""
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

def load_json(file_path: str) -> dict|None:
	if os.path.isfile(file_path):
		try:
			with open(file_path, 'r') as fx:
				data = json.load(fx)
				return data
		except Exception as e:
			logger.error(f"Error loading file '{file_path}': {e}")
			return None
	return None

def save_json(file_path: str, data: dict) -> None:
	"""
	Atomically replace the file with the JSON document.
	Writes to a temp file in the same folder, flushes it to disk, then renames over the target,
	so a crash or power loss never leaves a truncated file. Errors propagate to the caller.
	"""
	if file_path is None:
		raise ValueError("file_path cannot be None")
	if data is None:
		raise ValueError("data cannot be None")
	folder = os.path.dirname(file_path) or "."
	# a plugin's or data source's folder exists because something was written to it, not because it might be
	os.makedirs(folder, exist_ok=True)
	fd, temp_path = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
	try:
		with os.fdopen(fd, 'w', encoding='utf-8') as fx:
			json.dump(data, fx, indent=2)
			fx.flush()
			os.fsync(fx.fileno())
		os.replace(temp_path, file_path)
	except BaseException:
		try:
			os.remove(temp_path)
		except OSError:
			pass
		logger.error(f"Error saving file '{file_path}'")
		raise

def load_bytes(file_path: str) -> bytes|None:
	"""The file's bytes, or None when it is not there or cannot be read."""
	try:
		with open(file_path, 'rb') as fx:
			return fx.read()
	except OSError:
		return None

def save_bytes(file_path: str, data: bytes) -> None:
	"""Atomically replace the file with `data` (the same temp file and rename as `save_json`). Errors propagate to the caller."""
	folder = os.path.dirname(file_path) or "."
	os.makedirs(folder, exist_ok=True)
	fd, temp_path = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".bin")
	try:
		with os.fdopen(fd, 'wb') as fx:
			fx.write(data)
			fx.flush()
			os.fsync(fx.fileno())
		os.replace(temp_path, file_path)
	except BaseException:
		try:
			os.remove(temp_path)
		except OSError:
			pass
		logger.error(f"Error saving file '{file_path}'")
		raise

def remove_file(file_path: str) -> None:
	"""Remove the file; a file that is not there is already removed."""
	try:
		os.remove(file_path)
	except FileNotFoundError:
		pass
