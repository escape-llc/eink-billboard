"""The devices this build knows, by id. A device is added here when it is written; the GPIO settings name what each is set up with."""
from typing import Callable

from .base import InputDevice
from .buttons import Buttons

def available_devices() -> dict[str, Callable[[], InputDevice]]:
	"""What makes each device, by its id."""
	return { Buttons.id: Buttons }
