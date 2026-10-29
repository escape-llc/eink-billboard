"""
How the device is, as a page (#651): the same readings as the System page's Device card (its Machine row) (python/web/system_info.py), laid out for the panel. A reading that is too high is marked with a word
("High", "Low space"), so it reads on a panel with two inks. Read on the device: no network, no key. Like the System page, every value is a number or one of our own words:
no host name, address, user or path is drawn.
"""
import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Mapping

import psutil

from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import PermanentError, RenderSession
from ...web.system_info import host_info, load_info, pi_info
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

logger = logging.getLogger(__name__)

READINGS = ("system", "processor", "memory", "disk", "temperature", "uptime")

@dataclass(frozen=True)
class Row:
	"""One line of the page: a label, what it says, an optional gauge (percent used) and a warning word ("" when all is well)."""
	label: str
	value: str
	percent: float|None = None
	warning: str = ""

def chosen_readings(params: Mapping[str, Any]) -> list[str]:
	"""The readings in page order; none chosen reads as all of them. An unknown one is a PermanentError (fix the settings)."""
	chosen = params.get("readings")
	if chosen is None or chosen == []:
		return list(READINGS)
	if not isinstance(chosen, list) or any(r not in READINGS for r in chosen):
		raise PermanentError(f"Unknown reading (one of {', '.join(READINGS)})")
	return [r for r in READINGS if r in chosen]

def format_bytes(n: float) -> str:
	"""A size in the largest unit that keeps it under 1024 ("1.5 GB")."""
	size = float(n)
	for unit in ("B", "KB", "MB", "GB"):
		if size < 1024:
			return f"{size:.0f} {unit}" if unit == "B" or size >= 100 else f"{size:.1f} {unit}"
		size /= 1024
	return f"{size:.1f} TB"

def format_uptime(seconds: float) -> str:
	"""A time span in its two largest units ("3 days 4 h", "12 min")."""
	total = int(seconds)
	days, rest = divmod(total, 86400)
	hours, rest = divmod(rest, 3600)
	minutes = rest // 60
	if days > 0:
		return f"{days} {'day' if days == 1 else 'days'} {hours} h"
	if hours > 0:
		return f"{hours} h {minutes} min"
	if minutes > 0:
		return f"{minutes} min"
	return f"{total} s"

def _number(value: Any, default: float) -> float:
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

def status_rows(readings: list[str], host: Mapping[str, Any], load: Mapping[str, Any], pi: Mapping[str, Any]|None, volume: Mapping[str, Any]|None, params: Mapping[str, Any]) -> list[Row]:
	"""The lines for the chosen readings; one the machine cannot give is left out."""
	temperature_limit = _number(params.get("temperatureLimit"), 70.0)
	disk_limit = _number(params.get("diskWarnPercent"), 90.0)
	rows: list[Row] = []
	for reading in readings:
		if reading == "system":
			if pi is not None and pi.get("model"):
				rows.append(Row("Board", str(pi["model"])))
			rows.append(Row("System", f"{host.get('os', 'Unknown')} {host.get('os_release', '')} ({host.get('machine', '')})"))
		elif reading == "processor":
			cpus = int(host.get("cpus") or 0)
			text = f"{cpus} {'core' if cpus == 1 else 'cores'}"
			busy = load.get("cpu_percent")
			if isinstance(busy, (int, float)):
				text += f", {busy:.0f}% busy"
			rows.append(Row("Processor", text, float(busy) if isinstance(busy, (int, float)) else None))
		elif reading == "memory":
			memory = load.get("memory")
			if memory:
				rows.append(Row("Memory", f"{format_bytes(memory['used'])} of {format_bytes(memory['total'])}", float(memory["percent"])))
		elif reading == "disk":
			if volume:
				percent = float(volume["percent"])
				rows.append(Row("Disk", f"{format_bytes(volume['free'])} free of {format_bytes(volume['total'])}", percent, "Low space" if percent >= disk_limit else ""))
		elif reading == "temperature":
			if pi is not None and isinstance(pi.get("temperature_c"), (int, float)):
				celsius = float(pi["temperature_c"])
				# a power or heat warning from the firmware outranks a number that is only over the limit
				warning = "Throttled" if pi.get("throttled_now") else ("High" if celsius >= temperature_limit else "")
				rows.append(Row("Temperature", f"{celsius:.1f} °C", None, warning))
		elif reading == "uptime":
			if isinstance(host.get("uptime_seconds"), (int, float)):
				rows.append(Row("Machine up", format_uptime(host["uptime_seconds"])))
			if isinstance(host.get("app_uptime_seconds"), (int, float)):
				rows.append(Row("App running", format_uptime(host["app_uptime_seconds"])))
	return rows

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, rows: list[Row], settings: Mapping[str, Any], theme: ThemeInputs|None = None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	heading = settings.get("title") or "System Status"
	template_params = { "heading": heading, "rows": [{ "label": r.label, "value": r.value, "percent": r.percent, "warning": r.warning } for r in rows], "settings": settings }
	image = RenderSession(stm, render_dir, "system_status.html", theme).render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=str(heading))

class SystemStatusAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""How the device is, as one page, read when the slot is shown."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		chosen_readings(params)
		# one generated picture: the list is one empty item (an empty list is a source with nothing to show)
		return [{}]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		readings = chosen_readings(params)
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		cm = dsec.provider.required(ConfigurationManager)
		_, display_config = scm.open("display").get()
		if display_config is None:
			raise ValueError("Display settings is None")
		def read() -> list[Row]:
			# a processor's busy share needs a moment to measure (the first reading since the last call is meaningless); off the event loop
			load = load_info()
			try:
				load["cpu_percent"] = psutil.cpu_percent(interval=0.5)
			except Exception as e:
				logger.debug(f"The processor load could not be read ({type(e).__name__}).")
			return status_rows(readings, host_info(), load, pi_info(), cm.disk_volume(), params)
		rows = await asyncio.to_thread(read)
		return await asyncio.to_thread(generate_image, stm, cm.datasource_render_dir("system_status"), target_dimensions(dsec, display_config), rows, params, current_inputs(scm))
