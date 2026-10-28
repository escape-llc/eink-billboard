"""
The transit contract (`data-transit`, #429): the departures and service alerts of one stop, which the transit pages and overlays draw. A provider implements
`TransitApi`; a consumer asks `dsec.provide(TransitApi)` and imports nothing else of the provider's, so a second provider (GTFS feeds read directly, #437)
needs no change in the pages.

**This is not a real-time display.** A report is what the provider kept (its cache guards a small monthly quota), so it says when it was fetched
(`fetched_at`, drawn as "as of 12:37"), and a page drops what is already gone when it draws (`catchable`), counting the walk to the stop. Every time is an
aware `datetime` in the stop's zone.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping

from ..data_source import DataSourceExecutionContext
from .provider import ProviderContract, device_now  # noqa: F401 (a consumer's time: one definition)

# what a trip's status can be: the provider's own words mapped to these
SCHEDULED, CANCELLED, SKIPPED, ADDED = "scheduled", "cancelled", "skipped", "added"
# a departure the reader cannot take (drawn struck out, never dropped for it: a cancelled bus is news)
NOT_RUNNING = (CANCELLED, SKIPPED)
# how severe an alert is, most first (GTFS-RT's levels; `unknown` and anything else after them)
SEVERITY_RANK = { "severe": 0, "warning": 1, "info": 2 }
# what a stop that publishes intervals instead of times says (GTFS `frequencies.txt`: no departure has a time of its own)
INTERVALS_ONLY = "This stop's agency publishes intervals, not times."

@dataclass(frozen=True)
class Route:
	"""The line a trip runs on: its short name (a number, "23"), long name, and its colours as `#rrggbb` when the agency gives them."""
	short_name: str
	long_name: str
	color: str|None = None
	text_color: str|None = None

	@property
	def label(self) -> str:
		return self.short_name or self.long_name

@dataclass(frozen=True)
class Departure:
	"""
	One departure from the stop. `when` is the time to show: the live estimate when there is one (`live`), else the timetable's. `scheduled` is the timetable's;
	`delay` the seconds behind it (negative ahead, None unknown). `status` is one of SCHEDULED, CANCELLED, SKIPPED or ADDED.
	"""
	when: datetime
	scheduled: datetime
	live: bool
	delay: int|None
	headsign: str
	route: Route
	status: str = SCHEDULED
	platform: str|None = None

	@property
	def running(self) -> bool:
		return self.status not in NOT_RUNNING

@dataclass(frozen=True)
class Alert:
	"""
	A service alert in the device's language: `key` tells one alert from another across the stop, its routes and trips (the feed's id and its periods), `periods`
	are when it is active (an open end is None). `severity` is `info`, `warning`, `severe` or `unknown`; `effect` and `cause` the GTFS words in lower case;
	`routes` the labels of the routes it came with (none: it is the stop's own).
	"""
	key: str
	header: str
	description: str
	severity: str
	effect: str
	cause: str
	periods: tuple[tuple[datetime|None, datetime|None], ...] = ()
	url: str|None = None
	routes: tuple[str, ...] = ()

	@property
	def rank(self) -> int:
		"""Most severe first: severe, warning, then the rest."""
		return SEVERITY_RANK.get(self.severity, len(SEVERITY_RANK))

	def active(self, moment: datetime) -> bool:
		"""Whether it is in force at `moment` (an alert with no periods always is)."""
		if not self.periods:
			return True
		return any((start is None or start <= moment) and (end is None or moment < end) for start, end in self.periods)

@dataclass(frozen=True)
class Stop:
	"""The stop as its agency names it, the key a provider asks by, and its zone (the times a page shows are in it)."""
	key: str
	name: str
	zone: str
	platform: str|None = None

@dataclass
class TransitReport:
	"""
	A stop's departures, soonest first, and the alerts active when it was fetched (one each, however many trips carry it). `fetched_at` is when the provider asked
	(the page's "as of"); `walk_minutes` is the person's walk to the stop, from the stop's entry; `notes` are in our words (`INTERVALS_ONLY`); `credit` is the
	provider's, which its terms ask to be next to the data.
	"""
	stop: Stop
	fetched_at: datetime
	credit: str
	walk_minutes: int = 0
	departures: list[Departure] = field(default_factory=list)
	alerts: list[Alert] = field(default_factory=list)
	notes: list[str] = field(default_factory=list)

	def catchable(self, now: datetime) -> list[Departure]:
		"""The departures someone leaving now can still catch: not before `now` plus the walk. A cancelled one stays (it is struck out, not hidden)."""
		earliest = now + timedelta(minutes=self.walk_minutes)
		return [d for d in self.departures if d.when >= earliest]

	def active_alerts(self, now: datetime) -> list[Alert]:
		return [a for a in self.alerts if a.active(now)]

class TransitApi(ProviderContract):
	"""
	`open_async(dsec, { "stop": name, "routeAlerts": bool })` answers a `TransitReport` for the stop of the provider's own list (My Stops) with that name. Its alerts
	are those that come with the departures (the stop's, its trips' and the routes they run on); `routeAlerts` asks too for the alerts of every route that serves the
	stop, which can be a call of its own. A name that is not one of My Stops is a PermanentError, as a missing key is; an origin that does not answer gives the kept
	report when there is one.
	"""
	capability = "data-transit"
	noun = "transit"
	# one provider for now: the device chooses it alone (a second one, #437, adds a system setting as the weather's)
	setting = None

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> TransitReport:
		raise NotImplementedError

	def stop_names(self, dsec: DataSourceExecutionContext) -> list[str]:
		"""The names of My Stops, in their order (a task that chooses none means all of them). `dsec` is the provider's own context."""
		raise NotImplementedError
