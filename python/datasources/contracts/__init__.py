"""
The contracts between providers and the data sources that need them (#513), one per capability: `CONTRACTS` maps a capability (a `data-*` feature)
to its contract class. See `provider.py`.
"""
from .ai import AiImageApi, AiTextApi
from .calendar import CalendarApi
from .provider import ProviderContract
from .weather import WeatherApi

CONTRACTS: dict[str, type[ProviderContract]] = { c.capability: c for c in (WeatherApi, CalendarApi, AiTextApi, AiImageApi) }

def tokens_of(capability: str) -> list[dict[str, str]]:
	"""The fields a prompt may use for a capability's data (`tokensFrom`): its contract's `tokens`, none for an unknown capability."""
	contract = CONTRACTS.get(capability)
	return [dict(t) for t in contract.tokens] if contract is not None else []
