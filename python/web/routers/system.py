"""What the device and its storage look like, for the System page (#390): the machine (`system_info.py`), the storage by area and by plugin and data source, and the Pi's own readings when it is one."""
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request

from ...datasources.metering import METER, quotas_of
from ...model.configuration_manager import ConfigurationManager
from ...device.pins import pin_choices
from ..deps import get_cm
from ..locate import locate
from ..panel import chosen_panel
from ..openapi import Answer, answers
from ..system_info import host_info, load_info, pi_info

router = APIRouter(prefix="/system")

class Host(Answer):
	commit: str
	os: str
	os_release: str
	machine: str
	python: str
	cpus: int
	uptime_seconds: int | None = None
	app_uptime_seconds: int | None = None
	# `synced` once the network has set the clock, `unsynced` until then (#785); left out when the machine has no timesyncd to ask
	clock: Literal["synced", "unsynced"] | None = None

class Memory(Answer):
	total: int
	used: int
	percent: float

class Load(Answer):
	"""Each reading only when the machine gives it."""
	cpu_percent: float | None = None
	load: list[float] | None = None
	memory: Memory | None = None
	app_memory: int | None = None

class Pi(Answer):
	"""A Raspberry Pi's own readings: the model always, the others when the Pi gives them."""
	model: str
	temperature_c: float | None = None
	throttled: list[str] | None = None
	throttled_now: bool | None = None
	cpu_mhz: int | None = None
	cpu_max_mhz: int | None = None
	fan_rpm: int | None = None
	fan_percent: int | None = None

class Area(Answer):
	name: str
	files: int
	bytes: int

class Owner(Answer):
	"""A plugin's or a data source's folder: `kept_bytes` are its kept downloads and answers."""
	id: str
	files: int
	bytes: int
	kept_bytes: int

class Volume(Answer):
	total: int
	used: int
	free: int
	percent: float

class Storage(Answer):
	areas: list[Area]
	plugins: list[Owner]
	datasources: list[Owner]
	volume: Volume | None

class Period(Answer):
	"""A data source's calls in a period: by status (or why there was none), the bytes, and what its cache did."""
	calls: int
	status: dict[str, int]
	sent: int
	received: int
	cache: dict[str, int]
	cacheBytes: dict[str, int]
	hitRate: float | None
	bytesSaved: int

class QuotaUse(Answer):
	"""The plan the user says they have, against this period's calls (#586): the period starts on `resetDay` of each month, `since` and `resets` are its first day and the next one's."""
	limit: int
	resetDay: int
	used: int
	percent: float
	since: str
	resets: str

class Usage(Answer):
	id: str
	name: str
	today: Period
	week: Period
	month: Period
	lastLimited: str | None
	quota: QuotaUse | None

class SystemInfo(Answer):
	host: Host
	load: Load
	pi: Pi | None
	storage: Storage
	usage: list[Usage]

class Located(Answer):
	"""A rough position, or our words for why there is none."""
	ok: bool
	message: str
	latitude: float | None = None
	longitude: float | None = None

def usage_report(cm: ConfigurationManager) -> list[dict]:
	"""What the API data sources have asked of their services (`datasources/metering.py`), each named from its descriptor (an id with no descriptor, a source removed since, keeps its id)."""
	names = { str(item["info"].get("id")): str(item["info"].get("name") or item["info"].get("id")) for item in cm.enum_datasources() }
	return [{ **entry, "name": names.get(entry["id"], entry["id"]) } for entry in METER.report(quotas_of(cm))]

@router.get("", **answers(SystemInfo))
def get_system(cm: ConfigurationManager = Depends(get_cm)):
	"""
	Numbers and our own words only: no host name, address, user or path. `pi` is present only on a Raspberry Pi. A reading the machine cannot give is left out.
	The storage's folders are walked on every call (a few dozen small files); the page asks every ten seconds while it is open.
	"""
	return { "host": host_info(), "load": load_info(), "pi": pi_info(), "storage": cm.storage_usage(), "usage": usage_report(cm) }

class PinChoice(Answer):
	"""One pin of the header, for the GPIO settings' drop-down: what it shows, the number it stores, and `disabled` when the panel uses it."""
	name: str
	value: int
	disabled: bool

@router.get("/gpio-pins", **answers(list[PinChoice]))
def get_gpio_pins(request: Request, cm: ConfigurationManager = Depends(get_cm)):
	"""
	The header's GPIO pins (BCM numbers) a button may be wired to, for the GPIO settings' pin field: the lines the panel uses are `disabled` and say what for, so the choice follows the
	display type the settings choose now. A pin on a bus is offered with a note. The same rule refuses them at a save.
	"""
	return [{ "name": c.name, "value": c.pin, "disabled": not c.available } for c in pin_choices(chosen_panel(request, cm))]

@router.post("/locate", **answers(Located))
def locate_by_ip():
	"""A rough position from the device's public IP address, for the Location field's button: `{ ok, message, latitude?, longitude? }`. Nothing is saved; always 200, in our words."""
	try:
		# a plain `def`, in the thread pool: no event loop is running here
		return asyncio.run(locate())
	except Exception as e:
		logging.getLogger(__name__).warning(f"The location lookup failed ({type(e).__name__}).")
		return { "ok": False, "message": "The location could not be looked up." }
