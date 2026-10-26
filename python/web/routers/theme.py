"""The theme's inks as the device resolves them, for the settings page's swatches (the one derivation is `python/model/theme.py`)."""
from typing import Any

from fastapi import APIRouter, Body, Request

from ..openapi import Answer, answers
from ..deps import get_container
from ...model.inks import APPEARANCE, DRIVE, INK_SETS, panel_ink_set
from ...model.theme import Palette as ThemePalette, hex_of, resolve
from ...task.application import Application

router = APIRouter(prefix="/theme")

class Role(Answer):
	"""A role of the palette: its CSS class, the ink it resolved to, the exact color it is drawn with and roughly what the panel shows."""
	name: str
	ink: str
	drive: str
	appearance: str

class Palette(Answer):
	"""The roles for the panel that is attached. `confirmed` is false while the display has not started: the ink set is then the default, a guess."""
	inkSet: str
	confirmed: bool
	roles: list[Role]

@router.post("/palette", **answers(Palette))
def palette(request: Request, settings: dict[str, Any] = Body(default_factory=dict)):
	"""The roles of the palette for these theme settings (what the form holds, saved or not), resolved against the ink set of the attached panel: `[{ name, ink, drive, appearance }]`.
	Values that are not valid read as the factory defaults, as they do on the device."""
	isp = get_container(request)
	application = isp.get_service(Application) if isp is not None else None
	started = application.display.ink_set if application is not None and application.display is not None else None
	name = started if started in INK_SETS else panel_ink_set()
	computed, _, _ = resolve(settings, name)
	return { "inkSet": name, "confirmed": started is not None, "roles": [{ "name": role, "ink": computed.ink(role), "drive": hex_of(DRIVE[computed.ink(role)]), "appearance": hex_of(APPEARANCE[computed.ink(role)]) } for role in ThemePalette.roles()] }
