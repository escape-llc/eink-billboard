"""
The Clock Chime (#918): a timer task that plays a grandfather clock's chimes and strikes on an output (python/device/outputs.py) and draws nothing.

What it plays comes from the time it wakes at, rounded to the nearest quarter hour, so a task that runs a moment late still plays its quarter. Its trigger chooses which quarters it wakes for.
The Westminster quarters are the five changes in their usual order: one at a quarter past, two at half past, three at a quarter to, four before the hour. The hour is struck with the Bell.
"""
from datetime import datetime
import logging
import threading
from typing import Any, Mapping

from ...device.cues import Steps
from ...device.player import quiet
from ...model.schedule import TimerTaskItem
from ...task.message_router import MessageRouter
from ...task.messages import OutputCue
from ..plugin_base import PluginAsync, PluginExecutionContext, TrackType

# each quarter's changes, the hour's first (the Westminster quarters)
QUARTERS: tuple[tuple[str, ...], ...] = (
	("change-2", "change-3", "change-4", "change-5"),
	("change-1",),
	("change-2", "change-3"),
	("change-4", "change-5", "change-1"),
)

def chime_steps(at: datetime, chimes: object, strike_hour: object, half_hour: object) -> tuple[int, int, Steps]:
	"""The hour (0 to 23) and quarter (0 to 3) nearest `at`, and what a clock plays then: the quarter's changes (Westminster), then the hour's strikes on the hour, or one strike at half past with no chimes."""
	quarters = round((at.hour * 60 + at.minute + at.second / 60) / 15)
	hour, quarter = (quarters // 4) % 24, quarters % 4
	westminster = chimes != "none"
	steps: list[tuple[str, int]] = [(change, 1) for change in QUARTERS[quarter]] if westminster else []
	if quarter == 0 and strike_hour is not False:
		steps.append(("bell", hour % 12 or 12))
	elif quarter == 2 and not westminster and half_hour is not False:
		steps.append(("bell", 1))
	return hour, quarter, tuple(steps)

class ClockChimeAsync(PluginAsync):
	# run by the timer layer, which never sets `context.resumed`
	resume_contract = "ignores"
	def __init__(self, id, name):
		self._id = id
		self._name = name
		self.logger = logging.getLogger(__name__)
	@property
	def id(self) -> str:
		return self._id
	@property
	def name(self) -> str:
		return self._name
	def _chime(self, context: PluginExecutionContext, track: TimerTaskItem) -> None:
		settings: Mapping[str, Any] = track.task.content
		output = settings.get("cueOutput")
		if not isinstance(output, str) or output == "":
			raise RuntimeError("No output is chosen")
		at = context.timestamp
		if quiet({ "quietFrom": settings.get("silentFrom"), "quietTo": settings.get("silentTo") }, at):
			self.logger.info(f"{self.id} '{track.title}' is silent at {at:%H:%M} (its night silence)")
			return
		hour, quarter, steps = chime_steps(at, settings.get("chimes"), settings.get("strikeHour"), settings.get("halfHour"))
		if not steps:
			self.logger.info(f"{self.id} '{track.title}' has nothing to play at {hour:02d}:{quarter * 15:02d}")
			return
		router = context.provider.required(MessageRouter)
		router.send("indicator", OutputCue(at, output, steps, f"the clock at {hour:02d}:{quarter * 15:02d}"))
	async def task_async(self, context: PluginExecutionContext, track: TrackType, done: threading.Event) -> None:
		try:
			if not isinstance(track, TimerTaskItem):
				raise RuntimeError(f"Unsupported track type: {type(track)}")
			self._chime(context, track)
		finally:
			done.set()
