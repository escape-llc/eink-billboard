import threading
import logging
from datetime import datetime, timedelta

from .message_router import MessageRouter
from .messages import ExecuteMessage

class TickMessage(ExecuteMessage):
	"""Message indicating a timer tick."""
	def __init__(self, tick_ts:datetime, tick_number:int):
		super().__init__()
		self.tick_ts = tick_ts
		self.tick_number = tick_number
	def __repr__(self):
		return f"(tick_ts={self.tick_ts}, tick_number={self.tick_number})"

class BasicTimer(threading.Thread):
	def __init__(self, router: MessageRouter):
		super().__init__()
		self.router = router
		self.stopped = threading.Event()
#		self.daemon = True  # Allow program to exit even if timer is running
	def stop(self):
		self.stopped.set()
		self.logger.info("Stopping BasicTimer thread.")

class TimerTick(BasicTimer):
	def __init__(self, router: MessageRouter, interval=60, align_to_minute=True):
		"""
		:param router: MessageRouter instance to send TickMessage to.
		:param interval: Time in seconds between ticks.
		:param align_to_minute: If True, align second (and later) tick to the next minute.
		"""
		super().__init__(router)
		self.interval = interval
		self.align_to_minute = align_to_minute
		self.tick_count = 0
		self.logger = logging.getLogger(__name__)

	def run(self):
		self.logger.info("TimerTick thread starting.")
		try:
			if self.align_to_minute:
				self.logger.info("Aligning to next minute.")
				# TODO get the system-settings.timeZone
				now = datetime.now()
				next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
				sleep_seconds = (next_minute - now).total_seconds()
				tick = TickMessage(now, self.tick_count)
				self.logger.info(f"Pre-align Tick {tick.tick_number}: {tick.tick_ts}")
				self.tick_count += 1
				self.router.send("tick", tick)
				self.logger.debug(f"Sleeping for {sleep_seconds:.2f} seconds to align to minute {next_minute}.")
				if self.stopped.wait(timeout=sleep_seconds):
					return  # Exit if stop event is set

			while not self.stopped.is_set():
				now = datetime.now()
				tick = TickMessage(now, self.tick_count)
				self.tick_count += 1
				self.logger.info(f"Tick {tick.tick_number}: {tick.tick_ts}")
				self.router.send("tick", tick)
				# Align to next interval boundary
				if self.interval >= 60:
					overage = now - now.replace(second=0, microsecond=0)
					sleep_time = max(0, self.interval - overage.total_seconds())
					self.logger.debug(f"Sleeping for {sleep_time:.4f} seconds (interval={self.interval}, now={now}).")
					if self.stopped.wait(timeout=sleep_time):
						break
				elif self.interval >= 1:
					overage = now - now.replace(microsecond=0)
					sleep_time = max(0, self.interval - overage.total_seconds())
					self.logger.debug(f"Sleeping for {sleep_time:.4f} seconds (interval={self.interval}, now={now}).")
					if self.stopped.wait(timeout=sleep_time):
						break
				else:
					self.logger.debug(f"Sleeping for {self.interval:.2f}.")
					if self.stopped.wait(timeout=self.interval):
						break

		except Exception as e:
			self.logger.error(f"Exception in TimerTick thread: {e}", exc_info=True)
		finally:
			self.logger.info("TimerTick thread stopped.")
