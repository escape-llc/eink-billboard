from dataclasses import dataclass
from datetime import datetime

from .messages import BasicMessage

@dataclass(frozen=True, slots=True)
class TickMessage(BasicMessage):
	"""Message indicating a timer tick."""
	tick_ts: datetime
	tick_number: int
