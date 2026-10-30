"""What the display is, for the routes that offer or check the header's pins (the GPIO settings): the panel the display settings choose, with the size of the one that is running."""
from fastapi import Request

from ..device.pins import Panel, panel_for
from ..model.configuration_manager import ConfigurationManager
from .deps import get_container

def running_panel(request: Request) -> Panel|None:
	"""What the display is, once it has started (the Application keeps it); none before that, or when the app is not running the usual way."""
	from ..task.application import Application
	isp = get_container(request)
	application = isp.get_service(Application) if isp is not None else None
	return application.panel if application is not None else None

def chosen_panel(request: Request, cm: ConfigurationManager) -> Panel|None:
	"""The panel the display settings choose now, which a change of display makes before the display restarts (`panel_for`)."""
	_, display = cm.settings_manager().open("display").get()
	kind = display.get("display_type") if isinstance(display, dict) else None
	return panel_for(kind if isinstance(kind, str) else None, running_panel(request))
