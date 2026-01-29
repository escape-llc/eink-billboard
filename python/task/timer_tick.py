from datetime import datetime

from .messages import BasicMessage

class TickMessage(BasicMessage):
	"""Message indicating a timer tick."""
	def __init__(self, tick_ts:datetime, tick_number:int):
		super().__init__(tick_ts)
		self.tick_ts = tick_ts
		self.tick_number = tick_number
	def __repr__(self):
		return f"(tick_ts={self.tick_ts}, tick_number={self.tick_number})"
