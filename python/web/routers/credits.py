"""The Credits list (the Help drawer's last section): whose data the providers and data sources show, the fonts, the software and the artwork by others, and what inspired the project (`python/web/credits.py`)."""
from fastapi import APIRouter, Depends

from ...model.configuration_manager import ConfigurationManager
from ..credits import ARTWORK, INSPIRATION, SOFTWARE, data_credits, font_credits
from ..deps import get_cm
from ..openapi import Answer, answers

router = APIRouter(prefix="/credits")

class SoftwareCredit(Answer):
	"""A font, other software or artwork by others (or the project that inspired this one): whose it is, its licence, and what it is here."""
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
	artwork: list[SoftwareCredit]
	inspiration: list[SoftwareCredit]

@router.get("", **answers(Credits))
def get_credits(cm: ConfigurationManager = Depends(get_cm)):
	return { "data": data_credits(cm.enum_datasources()), "fonts": font_credits(), "software": SOFTWARE, "artwork": ARTWORK, "inspiration": INSPIRATION }
