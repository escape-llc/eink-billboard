"""
A map of a place (#428): a place of the data source's settings, or the device's own location, in one of Thunderforest's styles (transport shows the bus and rail lines), at the panel's
size, with the attribution their terms ask for drawn on it. It is a picture of one (`media-image`) and a foreground page: a map has labels an overlay would cover, and its attribution
must stay in view. The key, the maps it keeps and the Static Maps call are the Thunderforest API data source's (`thunderforest-api`), asked with `dsec.use`.
"""
import asyncio
import base64
import io
import logging
from typing import Any, Mapping

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager, SettingsConfigurationManager, StaticConfigurationManager
from ...model.theme import current_inputs
from ...plugins.plugin_base import PermanentError, RenderSession
from ...utils.image_utils import to_rgb
from ...utils.upload_image import open_picture
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions
from ..thunderforest_api.thunderforest_api import ThunderforestApi

THUNDERFOREST_ID = "thunderforest-api"
ATTRIBUTION = "Maps © www.thunderforest.com, Data © www.osm.org/copyright"

logger = logging.getLogger(__name__)

def number(value: Any) -> float|None:
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def place_of(dsec: DataSourceExecutionContext, name: Any) -> tuple[str, float, float]:
	"""The named place from this data source's settings, or (no name) the device's own location from the system settings: `(title, latitude, longitude)`."""
	if isinstance(name, str) and name:
		_, settings = dsec.provider.required(DatasourceConfigurationManager).open().get()
		for entry in (settings or {}).get("places") or []:
			if isinstance(entry, dict) and entry.get("name") == name:
				where = entry.get("location")
				latitude, longitude = (number(where.get("latitude")), number(where.get("longitude"))) if isinstance(where, dict) else (None, None)
				if latitude is None or longitude is None:
					raise PermanentError(f"The place '{name}' has no location. Set it in the Thunderforest Map settings.")
				return name, latitude, longitude
		# nothing to retry: the place was renamed or removed from the settings
		raise PermanentError(f"The place '{name}' is not in the Thunderforest Map settings.")
	_, system = dsec.provider.required(SettingsConfigurationManager).open("system").get()
	where = (system or {}).get("location")
	latitude, longitude = (number(where.get("latitude")), number(where.get("longitude"))) if isinstance(where, dict) else (None, None)
	if latitude is None or longitude is None:
		raise PermanentError("The device has no location. Set it in the System settings, or choose a place.")
	return "the device's location", latitude, longitude

def _embedded(png: bytes) -> str:
	"""The map as an image the page can hold (it needs no network): decoded as an untrusted picture, then written again as PNG."""
	picture = to_rgb(open_picture(png))
	out = io.BytesIO()
	picture.save(out, "PNG")
	return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")

def generate_image(stm: StaticConfigurationManager, render_dir: str, dimensions: tuple[int, int], template_params: dict, theme=None) -> MediaRenderResult | None:
	"""Blocking (runs Chromium)."""
	image = RenderSession(stm, render_dir, "thunderforest_map.html", theme).render(dimensions, template_params)
	return None if image is None else MediaRenderResult(image=image, title=str(template_params["title"]))

class ThunderforestMapAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		# one map; where it is is the whole of the list, and the picture is fetched when it is shown
		title, latitude, longitude = place_of(dsec, params.get("place"))
		return [{ "title": title, "latitude": latitude, "longitude": longitude }]

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		if not isinstance(state, Mapping):
			return None
		size = target_dimensions(dsec)
		api, api_dsec = dsec.use(THUNDERFOREST_ID, ThunderforestApi)
		png = await api.open_async(api_dsec, { "style": params.get("style"), "latitude": state["latitude"], "longitude": state["longitude"], "zoom": params.get("zoom"), "size": size })
		try:
			picture = await asyncio.to_thread(_embedded, png)
		except ValueError as bad:
			# the picture could not be used: our own words from `open_picture`
			raise RuntimeError(f"'{self.name}' {bad}") from None
		scm = dsec.provider.required(SettingsConfigurationManager)
		stm = dsec.provider.required(StaticConfigurationManager)
		render_dir = dsec.provider.required(ConfigurationManager).datasource_render_dir("thunderforest_map")
		page = { "map": picture, "attribution": ATTRIBUTION, "title": f"Map of {state.get('title') or 'a place'}", "settings": params }
		# Chromium is slow and blocking: keep it off the event loop
		return await asyncio.to_thread(generate_image, stm, render_dir, size, page, current_inputs(scm))
