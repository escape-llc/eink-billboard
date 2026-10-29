"""
Alert Takeover (#429 PR 5): a Priority Update task that takes the panel when a service alert you care about comes into force, and does nothing otherwise. It
asks the same kept answers as Service Alerts and draws its page (`transit_alerts`), so the plugin needs no change: `render_async` answers `None` unless there
is something new to show.

**Each alert is shown once per activation, whatever the task's rate**: an activation is the alert's key and the start of its period in force, so an alert that
ends and comes back (a new period) is shown again, and one in force for a day is shown once however often the task runs. The ones shown are kept by the source
(not stored: after a restart an alert in force is shown once more), and forgotten a day after they were last seen.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...model.clock_sync import ClockSync
from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ..contracts.transit import Alert, TransitApi, device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ..transit_alerts.transit_alerts import Alerts, generate_image, in_force, page_params

FORGET_AFTER = timedelta(days=1)

def activation(alert: Alert, now: datetime) -> str:
	"""Which activation of the alert is in force now: its key and the start of the period it is in ("open" for no start, or no periods)."""
	for start, end in alert.periods:
		if (start is None or start <= now) and (end is None or now < end):
			return f"{alert.key}@{start.isoformat() if start is not None else 'open'}"
	return f"{alert.key}@open"

def wanted(alerts: Alerts, effects: list[str]) -> Alerts:
	"""The alerts in force that are one of the chosen `effects` (none chosen: any effect); the severity is already applied (`in_force`)."""
	if not effects:
		return alerts
	return Alerts([s for s in alerts.found if s.alert.effect in effects], alerts.as_of, alerts.credit, alerts.stops)

class TransitTakeoverAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The panel for a new alert in force for your stops, once; nothing otherwise."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		# activation -> when it was last seen in force
		self.shown: dict[str, datetime] = {}

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		api, api_dsec = dsec.provide(TransitApi)
		chosen = params.get("stops")
		names = [n for n in chosen if isinstance(n, str)] if isinstance(chosen, list) and chosen else api.stop_names(api_dsec)
		reports = [(name, await api.open_async(api_dsec, { "stop": name, "routeAlerts": params.get("routeAlerts") is True })) for name in names]
		effects = params.get("effects")
		chosen_effects = [e for e in effects if isinstance(e, str)] if isinstance(effects, list) else []
		return [wanted(in_force(reports, device_now(dsec.timestamp), str(params.get("severity") or "severe")), chosen_effects)]

	def fresh(self, alerts: Alerts, now: datetime) -> Alerts:
		"""The alerts not yet shown in this activation; the ones still in force are seen now, and those not seen for a day forgotten."""
		for key in [k for k, seen in self.shown.items() if now - seen > FORGET_AFTER]:
			del self.shown[key]
		found = []
		for s in alerts.found:
			key = activation(s.alert, now)
			if key not in self.shown:
				found.append(s)
			else:
				self.shown[key] = now
		return Alerts(found, alerts.as_of, alerts.credit, alerts.stops)

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		# the Priority Update plugin hands over what `open_async` answered, the list
		alerts = state[0] if isinstance(state, list) and state else state
		# a clock that is not set makes "in force" mean nothing: no takeover
		if not isinstance(alerts, Alerts) or ClockSync().state() == "unsynced":
			return None
		now = device_now(dsec.timestamp)
		new = self.fresh(alerts, now)
		if not new.found:
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		_, system = scm.open("system").get()
		_, display_config = scm.open("display").get()
		# the page is Service Alerts' own
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("transit_alerts")
		template_params = page_params(new, now, { **params, "title": params.get("title") or "Service Alert" }, (system or {}).get("timeFormat") == "12h")
		result = await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), template_params, current_inputs(scm))
		if result is not None:
			for s in new.found:
				self.shown[activation(s.alert, now)] = now
		return result
