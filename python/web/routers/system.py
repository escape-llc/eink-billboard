"""What the device and its storage look like, for the System page (#390): the machine (`system_info.py`), the storage by area and by plugin and data source, and the Pi's own readings when it is one."""
from fastapi import APIRouter, Depends

from ...model.configuration_manager import ConfigurationManager
from ..deps import get_cm
from ..system_info import host_info, load_info, pi_info

router = APIRouter(prefix="/system")

@router.get("")
def get_system(cm: ConfigurationManager = Depends(get_cm)):
	"""
	Numbers and our own words only: no host name, address, user or path. `pi` is present only on a Raspberry Pi. A reading the machine cannot give is left out.
	The storage's folders are walked on every call (a few dozen small files); the page asks every ten seconds while it is open.
	"""
	return { "host": host_info(), "load": load_info(), "pi": pi_info(), "storage": cm.storage_usage() }
