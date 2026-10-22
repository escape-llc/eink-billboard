"""The Credits page's list: whose data the providers and data sources show, the fonts, and the software by others (`python/web/credits.py`)."""
from fastapi import APIRouter, Depends

from ...model.configuration_manager import ConfigurationManager
from ..credits import SOFTWARE, data_credits, font_credits
from ..deps import get_cm

router = APIRouter(prefix="/credits")

@router.get("")
def get_credits(cm: ConfigurationManager = Depends(get_cm)):
	return { "data": data_credits(cm.enum_datasources()), "fonts": font_credits(), "software": SOFTWARE }
