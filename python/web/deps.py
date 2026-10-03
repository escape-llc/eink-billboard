"""FastAPI dependencies shared by the routers."""
import hmac
from typing import Annotated

from fastapi import Depends, Request

from ..model.configuration_manager import ConfigurationManager
from ..model.service_container import IServiceProvider
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from .errors import ApiError

def get_container(request: Request) -> IServiceProvider|None:
	return getattr(request.app.state, "root_container", None)

def get_cm(request: Request) -> ConfigurationManager:
	isp = get_container(request)
	cm = isp.get_service(ConfigurationManager) if isp is not None else None
	if cm is None:
		raise ApiError(503, "Configuration Manager not available.")
	return cm

def get_time_of_day(request: Request) -> TimeOfDay:
	isp = get_container(request)
	tod = isp.get_service(TimeOfDay) if isp is not None else None
	return tod if tod is not None else SystemTimeOfDay()

def require_token(request: Request) -> None:
	"""When the application has an API token configured, every /api request must present it as a Bearer token."""
	token: str|None = getattr(request.app.state, "api_token", None)
	if not token:
		return
	header = request.headers.get("authorization", "")
	scheme, _, presented = header.partition(" ")
	if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip().encode(), token.encode()):
		raise ApiError(401, "Missing or invalid API token.")

CM = Annotated[ConfigurationManager, Depends(get_cm)]
TOD = Annotated[TimeOfDay, Depends(get_time_of_day)]
