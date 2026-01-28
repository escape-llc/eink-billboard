
import datetime
from typing import Protocol, runtime_checkable

@runtime_checkable
class TimeOfDay(Protocol):
	"""
	This exists primarily so we can scale down elapsed time during tests.
	For example, one second of "real" time may scale to one hour of "internal" time.
	Likewise, any computed timedelta objects must be scaled the same way.
	For example, setting a timer for one hour will trigger after one second of "real" time.
	The system MUST NOT directly reference "datetime.datetime.now()" or variants.
	"""
	def current_time(self) -> datetime.datetime:
		...
	def current_time_utc(self) -> datetime.datetime:
		...

class SystemTimeOfDay(TimeOfDay):
	# TODO take the zoneinfo from system settings.
	def current_time(self) -> datetime.datetime:
		return datetime.datetime.now().astimezone()
	def current_time_utc(self) -> datetime.datetime:
		return datetime.datetime.now(datetime.timezone.utc)