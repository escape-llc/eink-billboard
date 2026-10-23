"""The Credits list (the Help drawer's last section): whose data the providers and data sources show, the fonts, and the software by others (`python/web/credits.py`)."""
from fastapi import APIRouter, Depends

from ...model.configuration_manager import ConfigurationManager
from ..credits import SOFTWARE, data_credits, font_credits
from ..deps import get_cm
from ..openapi import Answer, answers

router = APIRouter(prefix="/credits")

class SoftwareCredit(Answer):
	"""A font or other software by others: whose it is, its licence, and what it does here."""
	name: str
	by: str
	license: str
	url: str | None = None
	what: str | None = None

class DataCredit(Answer):
	"""Whose data a provider or data source downloads, from its descriptor's `credit`."""
	id: str
	name: str
	text: str
	provider: bool
	license: str | None = None
	url: str | None = None

class Credits(Answer):
	data: list[DataCredit]
	fonts: list[SoftwareCredit]
	software: list[SoftwareCredit]

@router.get("", **answers(Credits))
def get_credits(cm: ConfigurationManager = Depends(get_cm)):
	return { "data": data_credits(cm.enum_datasources()), "fonts": font_credits(), "software": SOFTWARE }
