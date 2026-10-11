"""The theme's colors as the device computes them, for the settings page's swatches (the one derivation is `python/model/theme.py`)."""
from typing import Any

from fastapi import APIRouter, Body

from ...model.theme import inputs_from, palette_of

router = APIRouter(prefix="/theme")

@router.post("/palette")
def palette(settings: dict[str, Any] = Body(default_factory=dict)):
	"""The roles of the palette for these theme settings (what the form holds, saved or not): `[{ name, color }]`, name as the CSS class, color as `hsl()`.
	Values that are not valid read as the factory defaults, as they do on the device."""
	computed = palette_of(inputs_from(settings))
	return { "roles": [{ "name": name, "color": getattr(computed, name.replace("-", "_")).css } for name in computed.roles()] }
