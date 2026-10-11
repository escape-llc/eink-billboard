"""The fonts we ship, for the settings page's preview of the theme's typography."""
import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ...model.configuration_manager import FONT_FAMILIES, ConfigurationManager
from ..deps import get_cm
from ..errors import ApiError

router = APIRouter(prefix="/fonts")

@router.get("/{family}")
def get_font(family: str, weight: str = "normal", cm: ConfigurationManager = Depends(get_cm)):
	# the file is named by our own table, never by the URL: the family is only a key into it
	declared = next((name for name in FONT_FAMILIES if name == family), None)
	if declared is None:
		raise ApiError(404, "No such font.")
	variants = FONT_FAMILIES[declared]
	variant = next((v for v in variants if v["font-weight"] == weight), variants[0])
	root = os.path.realpath(os.path.join(cm.static_manager().ROOT_PATH, "fonts"))
	path = os.path.realpath(os.path.join(root, variant["file"]))
	if not path.startswith(root + os.sep) or not os.path.isfile(path):
		raise ApiError(404, "No such font.")
	return FileResponse(path, media_type="font/ttf", headers={ "Cache-Control": "public, max-age=86400" })
