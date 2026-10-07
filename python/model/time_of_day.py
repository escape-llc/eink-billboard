
from datetime import datetime, timezone, tzinfo
import logging
import os
from typing import Callable, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

@runtime_checkable
class TimeOfDay(Protocol):
	"""
	This exists primarily so we can scale (down) elapsed time during tests.
	For example, one second of "real" time may scale to one hour of "model" time.
	Likewise, any computed timedelta objects must be scaled inversely.
	For example, setting a timer for one hour will trigger after one second of "real" time.
	The system MUST NOT directly reference "datetime.datetime.now()" or variants.
	"""
	def current_time(self) -> datetime:
		...
	def current_time_utc(self) -> datetime:
		...

def _zone_from_name(name: str|None) -> tzinfo|None:
	if not name:
		return None
	name = name.strip().lstrip(":")
	try:
		return ZoneInfo(name)
	except (ZoneInfoNotFoundError, ValueError, OSError):
		return None

def local_zone() -> tzinfo|None:
	"""
	The machine's IANA zone when it can be determined without a third-party package: the TZ variable, then the
	/etc/localtime link or /etc/timezone (Linux, macOS). None (Windows, containers without either) means the caller keeps the fixed offset.
	"""
	zone = _zone_from_name(os.environ.get("TZ"))
	if zone is not None:
		return zone
	try:
		target = os.path.realpath("/etc/localtime")
		marker = "zoneinfo" + os.sep
		if marker in target:
			zone = _zone_from_name(target.split(marker, 1)[1].replace(os.sep, "/"))
			if zone is not None:
				return zone
	except OSError:
		pass
	try:
		with open("/etc/timezone", "r", encoding="utf-8") as f:
			return _zone_from_name(f.readline())
	except OSError:
		return None

class SystemTimeOfDay(TimeOfDay):
	"""
	The wall clock. The result carries a zone with rules (ZoneInfo) when one is known, so that date arithmetic and
	schedule generation stay correct across a DST change; otherwise it carries the fixed offset in force now.
	Pass `tz` to use a configured zone (e.g. the system settings' timezoneName) instead of the machine's.
	"""
	def __init__(self, tz: tzinfo|None = None):
		self._tz = tz
	def current_time(self) -> datetime:
		zone = self._tz if self._tz is not None else local_zone()
		if zone is not None:
			return datetime.now(zone)
		return datetime.now().astimezone()
	def current_time_utc(self) -> datetime:
		return datetime.now(timezone.utc)

class ConfiguredTimeOfDay(SystemTimeOfDay):
	"""
	The wall clock in the zone named by the system settings (`timezoneName`), read on every call so a change in the
	settings applies without a restart. A missing or unknown name falls back to the machine's zone.
	`name_source` returns the configured name (or None); it must not raise.
	"""
	def __init__(self, name_source: Callable[[], str|None]):
		super().__init__()
		self._name_source = name_source
	def current_time(self) -> datetime:
		try:
			self._tz = _zone_from_name(self._name_source())
		except Exception as e:
			logging.getLogger(__name__).warning(f"Could not read the system timezone setting: {e}")
			self._tz = None
		return super().current_time()
