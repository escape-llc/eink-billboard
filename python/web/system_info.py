"""
What the machine says about itself, for the System page (#390): the operating system, uptime, processor and memory (the storage's disk is the configuration manager's: `storage_usage`), and, on a Raspberry Pi, its model, temperature, clock, fan and power
warnings. Every value is a number or one of our own words: no host name, address, user or path leaves the device. Each reading is optional (a container sees less than a Pi, Windows less than
Linux): what cannot be read is left out, never an error.
"""
import logging
import os
import platform
import time
from typing import Any

import psutil

from ..model.clock_sync import ClockSync

logger = logging.getLogger(__name__)

# the Pi's own files (the kernel's: `/proc` and `/sys` are not the storage)
PI_MODEL = "/proc/device-tree/model"
# a container cannot read the device tree (Podman masks `/sys/firmware`, where `/proc/device-tree` points), but the kernel's `Model` line of the processor list is there too
PI_CPUINFO = "/proc/cpuinfo"
PI_TEMPERATURE = "/sys/class/thermal/thermal_zone0/temp"
PI_THROTTLED = "/sys/devices/platform/soc/soc:firmware/get_throttled"
# the kernel's sensors, each a folder `hwmonN` found by its `name` (the numbers are given in the order the drivers start): the Pi's fan is `pwmfan`
HWMON = "/sys/class/hwmon"
PI_FAN = "pwmfan"
# a Pi 5 has no `get_throttled` (on the device either), but its `rpi_volt` sensor raises `in0_lcrit_alarm` while the supply is too low
PI_VOLT = "rpi_volt"

# `get_throttled` bits (the Pi firmware's): what is wrong now, and what has been wrong since the start
THROTTLE_NOW = { 0: "Under-voltage now", 1: "Frequency capped now", 2: "Throttled now", 3: "Temperature limit now" }
THROTTLE_EVER = { 16: "Under-voltage since start", 17: "Frequency capped since start", 18: "Throttled since start", 19: "Temperature limit since start" }

def _read(path: str, limit: int = 256) -> str|None:
	try:
		with open(path, "rb") as f:
			return f.read(limit).decode("utf-8", "ignore").strip("\x00\n ")
	except OSError:
		return None

def _entries(path: str) -> list[str]:
	try:
		return sorted(os.listdir(path))
	except OSError:
		return []

def _cpuinfo_model() -> str|None:
	"""The `Model` line of `/proc/cpuinfo`, which a Raspberry Pi's kernel writes at its end."""
	for line in (_read(PI_CPUINFO, 64 * 1024) or "").splitlines():
		key, _, value = line.partition(":")
		if key.strip() == "Model":
			return value.strip()
	return None

def pi_model() -> str|None:
	"""The Pi's model name (`Raspberry Pi 5 Model B Rev 1.0`), or None when this is not a Raspberry Pi."""
	model = _read(PI_MODEL) or _cpuinfo_model()
	return model if model and model.startswith("Raspberry Pi") else None

def hwmon(name: str) -> str|None:
	"""The folder of the kernel's sensor called `name`, or None when there is none."""
	for entry in _entries(HWMON):
		folder = os.path.join(HWMON, entry)
		if _read(os.path.join(folder, "name")) == name:
			return folder
	return None

def _number(path: str) -> int|None:
	value = _read(path)
	return int(value) if value is not None and value.isdigit() else None

def voltage_info() -> dict[str, Any]:
	"""The power warnings of a Pi without `get_throttled`: under-voltage now, or none (what happened since the start is not kept by the sensor)."""
	folder = hwmon(PI_VOLT)
	alarm = _number(os.path.join(folder, "in0_lcrit_alarm")) if folder is not None else None
	if alarm is None:
		return {}
	return { "throttled": [THROTTLE_NOW[0]] if alarm else [], "throttled_now": bool(alarm) }

def fan_info() -> dict[str, Any]:
	"""The Pi's fan, when it has one: its speed, and how hard it is driven (`pwm1`, 0 to 255) as a share."""
	folder = hwmon(PI_FAN)
	if folder is None:
		return {}
	info: dict[str, Any] = {}
	rpm = _number(os.path.join(folder, "fan1_input"))
	if rpm is not None:
		info["fan_rpm"] = rpm
	pwm = _number(os.path.join(folder, "pwm1"))
	if pwm is not None:
		info["fan_percent"] = round(min(pwm, 255) / 255 * 100)
	return info

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
	else:
		info.update(voltage_info())
	info.update(fan_info())
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
	"""The operating system and the Python that runs the app, how long the machine has been up and, separately, how long the app has been running."""
	commit = os.environ.get("EINK_COMMIT", "")
	info: dict[str, Any] = { "commit": commit if commit.isalnum() and len(commit) <= 40 else "unknown", "os": platform.system() or "Unknown", "os_release": platform.release(), "machine": platform.machine(), "python": platform.python_version(), "cpus": psutil.cpu_count() or 0 }
	try:
		info["uptime_seconds"] = int(time.time() - psutil.boot_time())
	except Exception:
		pass
	try:
		# the app's own: since this process started (the machine's can be days older, and a restart of the app does not change it)
		info["app_uptime_seconds"] = max(0, int(time.time() - psutil.Process().create_time()))
	except Exception:
		pass
	# whether the network has set the clock (#785): left out when there is no timesyncd to ask
	clock = ClockSync().state()
	if clock != "unknown":
		info["clock"] = clock
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
