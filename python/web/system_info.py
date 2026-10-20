"""
What the machine says about itself, for the System page (#390): the operating system, uptime, processor and memory (the storage's disk is the configuration manager's: `storage_usage`), and, on a Raspberry Pi, its model, temperature, clock and power
warnings. Every value is a number or one of our own words: no host name, address, user or path leaves the device. Each reading is optional (a container sees less than a Pi, Windows less than
Linux): what cannot be read is left out, never an error.
"""
import logging
import os
import platform
import time
from typing import Any

import psutil

logger = logging.getLogger(__name__)

# the Pi's own files (the kernel's: `/proc` and `/sys` are not the storage)
PI_MODEL = "/proc/device-tree/model"
PI_TEMPERATURE = "/sys/class/thermal/thermal_zone0/temp"
PI_THROTTLED = "/sys/devices/platform/soc/soc:firmware/get_throttled"

# `get_throttled` bits (the Pi firmware's): what is wrong now, and what has been wrong since the start
THROTTLE_NOW = { 0: "Under-voltage now", 1: "Frequency capped now", 2: "Throttled now", 3: "Temperature limit now" }
THROTTLE_EVER = { 16: "Under-voltage since start", 17: "Frequency capped since start", 18: "Throttled since start", 19: "Temperature limit since start" }

def _read(path: str) -> str|None:
	try:
		with open(path, "rb") as f:
			return f.read(256).decode("utf-8", "ignore").strip("\x00\n ")
	except OSError:
		return None

def pi_model() -> str|None:
	"""The Pi's model name (`Raspberry Pi 5 Model B Rev 1.0`), or None when this is not a Raspberry Pi."""
	model = _read(PI_MODEL)
	return model if model and model.startswith("Raspberry Pi") else None

def throttle_flags(value: int) -> list[str]:
	"""What a `get_throttled` value says, in words: the ones that are true now first, then what happened since the start."""
	return [text for bit, text in { **THROTTLE_NOW, **THROTTLE_EVER }.items() if value & (1 << bit)]

def pi_info() -> dict[str, Any]|None:
	"""A Raspberry Pi's own readings, or None when this is not one."""
	model = pi_model()
	if model is None:
		return None
	info: dict[str, Any] = { "model": model }
	temperature = _read(PI_TEMPERATURE)
	if temperature is not None and temperature.lstrip("-").isdigit():
		info["temperature_c"] = round(int(temperature) / 1000, 1)
	raw = _read(PI_THROTTLED)
	if raw is not None:
		try:
			value = int(raw, 16)
			info["throttled"] = throttle_flags(value)
			info["throttled_now"] = bool(value & 0xF)
		except ValueError:
			pass
	try:
		freq = psutil.cpu_freq()
		if freq is not None:
			info["cpu_mhz"] = round(freq.current)
			if freq.max:
				info["cpu_max_mhz"] = round(freq.max)
	except Exception:
		pass
	return info

def host_info() -> dict[str, Any]:
	"""The operating system and the Python that runs the app, and how long the machine has been up."""
	commit = os.environ.get("EINK_COMMIT", "")
	info: dict[str, Any] = { "commit": commit if commit.isalnum() and len(commit) <= 40 else "unknown", "os": platform.system() or "Unknown", "os_release": platform.release(), "machine": platform.machine(), "python": platform.python_version(), "cpus": psutil.cpu_count() or 0 }
	try:
		info["uptime_seconds"] = int(time.time() - psutil.boot_time())
	except Exception:
		pass
	return info

def load_info() -> dict[str, Any]:
	"""The processor's load and the memory: the whole machine's, and this app's own."""
	info: dict[str, Any] = {}
	try:
		info["cpu_percent"] = psutil.cpu_percent(interval=None)
		if hasattr(os, "getloadavg"):
			info["load"] = [round(x, 2) for x in os.getloadavg()]
	except Exception as e:
		logger.debug(f"The processor load could not be read ({type(e).__name__}).")
	try:
		memory = psutil.virtual_memory()
		info["memory"] = { "total": memory.total, "used": memory.total - memory.available, "percent": round(memory.percent, 1) }
		info["app_memory"] = psutil.Process().memory_info().rss
	except Exception as e:
		logger.debug(f"The memory could not be read ({type(e).__name__}).")
	return info
