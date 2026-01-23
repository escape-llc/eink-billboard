from datetime import datetime, timedelta
import unittest
import time
import logging

from ..task.message_router import MessageRouter, Route
from ..task.timer_tick import BasicTimer, TimerTick, TickMessage
from ..task.basic_task import DispatcherTask
from ..task.messages import QuitMessage

logging.basicConfig(
	level=logging.DEBUG,  # Or DEBUG for more detail
	format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

class DebugTimerTask(BasicTimer):
	def __init__(self, router, eventList):
		super().__init__(router)
		self.eventList = eventList
		self.logger = logging.getLogger(__name__)
	def run(self):
		self.logger.info("DebugTimerTask thread starting.")
		try:
			for event in self.eventList:
				if self.stopped.is_set():
					return
				time.sleep(0.05)
				tick = event
				self.logger.info(f"Tick {tick.tick_number}: {tick.tick_ts}")
				self.router.send("tick", tick)
		except Exception as e:
			self.logger.error(f"Exception in DebugTimerTask: {e}", exc_info=True)
		finally:
			self.logger.info("DebugTimerTask thread exiting.")

class RecordingTask(DispatcherTask):
	def __init__(self, name):
		super().__init__(name)
		self.ticks = []
		self.logger = logging.getLogger(__name__)

	def _tick_message(self, msg: TickMessage):
		self.logger.debug(f"{self.name}: {msg}")
		# Only record TickMessage
		self.ticks.append((msg.tick_ts, msg.tick_number))
		time.sleep(0.06)

class TestTimerTick(unittest.TestCase):
	#@unittest.skip("Skipping timer tick test to avoid timing issues in CI")
	def test_tick_messages_sent_to_tasks(self):
		task1 = RecordingTask("Task 1")
		task2 = RecordingTask("Task 2")
		task1.start()
		task2.start()

		router = MessageRouter()
		router.addRoute(Route("tick",[task1, task2]))

		timer = TimerTick(router, interval=0.01, align_to_minute=False)  # Fast ticks for testing
		timer.start()

		# Let it tick a few times
		time.sleep(0.1)
		timer.stop()
		timer.join()

		# Stop tasks
		task1.accept(QuitMessage(datetime.now()))
		task2.accept(QuitMessage(datetime.now()))
		task1.join()
		task2.join()

		# Assert both tasks received tick messages
		self.assertGreaterEqual(len(task1.ticks), 1, "Task 1 should have received at least one tick")
		self.assertGreaterEqual(len(task2.ticks), 1, "Task 2 should have received at least one tick")
		self.assertEqual(len(task1.ticks), len(task2.ticks), "Both tasks should have received the same number of ticks")

	def create_timer_task(self, now, count=10):
		nowx = now.replace(second=0,microsecond=0)
		eventlist = [TickMessage(nowx + timedelta(minutes=ix), ix) for ix in range(count)];
		return eventlist
	def test_debug_timer_task(self):
		task1 = RecordingTask("Task 1")
		task2 = RecordingTask("Task 2")
		task1.start()
		task2.start()

		router = MessageRouter()
		router.addRoute(Route("tick",[task1, task2]))

		TICKS = 60*24
		eventlist = self.create_timer_task(datetime.now(), TICKS)
		timer = DebugTimerTask(router, eventlist)
		timer.start()

		# run until done
		timer.join()
		# Stop tasks
		task1.accept(QuitMessage(datetime.now()))
		task2.accept(QuitMessage(datetime.now()))
		task1.join()
		task2.join()

		# Assert both tasks received tick messages
		self.assertEqual(len(task1.ticks), 1440, "Task 1 should have received 1440 messages")
		self.assertEqual(len(task2.ticks), 1440, "Task 2 should have received 1440 messages")

if __name__ == "__main__":
    unittest.main()