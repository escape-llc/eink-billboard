"""
Service Alerts (#429 PR 3): the alerts in force for your stops and their routes, as an overlay or as a page. The data comes from the device's transit provider
(`dsec.provide(TransitApi)`): a stop's own alerts come with its departures, which the Departure Board of the same stop shares, so they cost nothing more; the
routes' alerts (`routeAlerts`) are a call of their own, kept longer.

**An overlay task's settings name its zone, a Slide Show track's do not**: with one it draws outlined text in the zone (`render_overlay`), the most severe alert
first, as many as fit; without, a page that lists them. With no alert in force the overlay is taken off (`None`), so an old alert is never left up, and the page
says there are none.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from ...model.clock_sync import ClockSync
from ...model.configuration_manager import ConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import ThemeInputs, current_inputs
from ...plugins.plugin_base import RenderSession
from ..contracts.transit import SEVERITY_RANK, Alert, TransitApi, device_now
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ..overlay_text import Run, lines_that_fit, outline_factor, overlay_margin, render_overlay, zone_valign

FONT_SCALES = { "x-small": 0.7, "small": 0.85, "normal": 1.0, "large": 1.2, "x-large": 1.45 }
# the least severe alert a task shows (`severity`): `any`, or `warning` and up, or only `severe`
SHOWN_FROM = { "any": len(SEVERITY_RANK), "warning": SEVERITY_RANK["warning"], "severe": SEVERITY_RANK["severe"] }
HEADER_CHARS = 60
SEVERITY_WORDS = { "severe": "Severe", "warning": "Warning", "info": "Notice" }

@dataclass(frozen=True)
class Seen:
	"""An alert in force, and the stops it was seen at (one alert on two stops is shown once)."""
	alert: Alert
	stops: tuple[str, ...]

@dataclass
class Alerts:
	"""What a run found: the alerts in force, most severe first, when the oldest answer was asked, and the credit of the provider."""
	found: list[Seen] = field(default_factory=list)
	as_of: datetime|None = None
	credit: str = ""
	stops: tuple[str, ...] = ()

def in_force(reports: list[tuple[str, Any]], now: datetime, severity: str) -> Alerts:
	"""The alerts of the stops' reports that are active now and at least as severe as asked, each once, most severe first; the stops it was seen at named."""
	limit = SHOWN_FROM.get(severity, SHOWN_FROM["any"])
	by_key: dict[str, Seen] = {}
	result = Alerts(stops=tuple(name for name, _ in reports))
	for name, report in reports:
		result.credit = result.credit or report.credit
		result.as_of = report.fetched_at if result.as_of is None or report.fetched_at < result.as_of else result.as_of
		for alert in report.active_alerts(now):
			if alert.rank > limit:
				continue
			stops = by_key[alert.key].stops if alert.key in by_key else ()
			by_key[alert.key] = Seen(alert, stops if name in stops else stops + (name,))
	result.found = sorted(by_key.values(), key=lambda s: (s.alert.rank, s.alert.header))
	return result

def _short(text: str, chars: int = HEADER_CHARS) -> str:
	return text if len(text) <= chars else text[:chars - 1].rstrip() + "…"

def where(seen: Seen) -> str:
	"""What an alert is about, in a few words: its routes, or the stop it was seen at."""
	return ", ".join(seen.alert.routes) if seen.alert.routes else ", ".join(seen.stops)

def credit_name(credit: str) -> str:
	"""Who the data is from, in a word: "Transit data: Transitland" is "Transitland" (the terms accept the name where the whole credit does not fit)."""
	return credit.rsplit(":", 1)[-1].strip()

def overlay_lines(alerts: Alerts) -> list[list[Run]]:
	"""
	One line per alert: what it is about in the accent, then its headline. The first, the most severe, carries the provider's name: its terms ask for the credit
	next to the data, and an overlay has room for a word, not a line.
	"""
	lines: list[list[Run]] = [[(f"{where(s)}: ", "text-secondary-1"), (_short(s.alert.header), "text-primary")] for s in alerts.found]
	if lines and alerts.credit:
		lines[0].append((f" · {credit_name(alerts.credit)}", "text-secondary-2"))
	return lines

def clock(when: datetime, twelve_hour: bool) -> str:
	return f"{when.hour % 12 or 12}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}" if twelve_hour else f"{when.hour:02d}:{when.minute:02d}"

def until(alert: Alert, now: datetime, twelve_hour: bool) -> str:
	"""When the period in force ends, in words: "until 18:00", "until Fri 18:00", or nothing when it has no end."""
	for start, end in alert.periods:
		if (start is None or start <= now) and (end is None or now < end):
			if end is None:
				return ""
			end = end.astimezone(now.tzinfo)
			return f"until {clock(end, twelve_hour)}" if end.date() == now.date() else f"until {end:%a} {clock(end, twelve_hour)}"
	return ""

def page_params(alerts: Alerts, now: datetime, params: Mapping[str, Any], twelve_hour: bool, clock_state: str = "unknown") -> dict[str, Any]:
	"""What the page draws: each alert's severity, what it is about, until when, its headline and its description."""
	common = { "heading": params.get("title") or "Service Alerts", "credit": alerts.credit, "font_scale": FONT_SCALES.get(str(params.get("fontSize")), 1.0) }
	if clock_state == "unsynced":
		return { **common, "alerts": [], "message": "Waiting for the clock to be set.", "as_of": "" }
	items = [{ "severity": s.alert.severity, "word": SEVERITY_WORDS.get(s.alert.severity, "Notice"), "where": where(s), "until": until(s.alert, now, twelve_hour),
		"header": s.alert.header, "description": s.alert.description } for s in alerts.found]
	message = "" if items else f"No service alerts for {', '.join(alerts.stops)}." if alerts.stops else "No service alerts."
	return { **common, "alerts": items, "message": message, "as_of": clock(alerts.as_of, twelve_hour) if alerts.as_of is not None else "" }

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions, template_params: dict, theme: ThemeInputs|None = None) -> MediaRenderResult|None:
	"""Blocking (runs Chromium). `dimensions` is the target size (see target_dimensions)."""
	image = RenderSession(stm, render_dir, "transit-alerts.html", theme).render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=template_params["heading"])

class TransitAlertsAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The alerts in force for your stops: an overlay in a zone, or a page."""
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		api, api_dsec = dsec.provide(TransitApi)
		chosen = params.get("stops")
		names = [n for n in chosen if isinstance(n, str)] if isinstance(chosen, list) and chosen else api.stop_names(api_dsec)
		reports = [(name, await api.open_async(api_dsec, { "stop": name, "routeAlerts": params.get("routeAlerts") is True })) for name in names]
		return [in_force(reports, device_now(dsec.timestamp), str(params.get("severity") or "any"))]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		if not isinstance(state, Alerts):
			return None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		_, system = scm.open("system").get()
		twelve_hour = (system or {}).get("timeFormat") == "12h"
		theme = current_inputs(scm)
		clock_state = ClockSync().state()
		if params.get("zone"):
			# an overlay: nothing in force (or a clock that is not set, when "in force" means nothing) takes it off
			if not state.found or clock_state == "unsynced":
				return None
			lines = overlay_lines(state)
			texts = ["".join(text for text, _ in runs) for runs in lines]
			outline, weight, valign, margin = outline_factor(params), str(params.get("weight") or "bold"), zone_valign(params), overlay_margin(params)
			shown = await asyncio.to_thread(lines_that_fit, stm, theme, dsec.dimensions, texts, outline, weight, valign, margin)
			image = await asyncio.to_thread(render_overlay, stm, theme, dsec.dimensions, lines[:shown], outline, weight, valign, margin)
			return MediaRenderResult(image=image, title=" · ".join(texts[:shown]))
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("transit_alerts")
		_, display_config = scm.open("display").get()
		template_params = page_params(state, device_now(dsec.timestamp), params, twelve_hour, clock_state)
		return await asyncio.to_thread(generate_image, stm, render_dir, target_dimensions(dsec, display_config), template_params, theme)
