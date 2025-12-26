from datetime import datetime, timedelta
import os
from pathlib import Path
import unittest
import time
import logging

from .utils import storage_path
from ..task.application import Application
from ..task.messages import QuitMessage, StartEvent, StartOptions
from ..task.timer_tick import BasicTimer, TickMessage

TICK_RATE = 0.05
TICK_RATE = 1

class DebugTimerTask(BasicTimer):
	def __init__(self, router, eventList, app):
		super().__init__(router)
		self.eventList = eventList
		self.app = app
		self.logger = logging.getLogger(__name__)
	def run(self):
		self.logger.info("DebugTimerTask thread starting.")
		try:
			for event in self.eventList:
				if self.stopped.is_set():
					return
				time.sleep(TICK_RATE)
				tick = event
				self.logger.info(f"Tick {tick.tick_number}: {tick.tick_ts}")
				self.router.send("tick", tick)
			self.app.send(QuitMessage())
		except Exception as e:
			self.logger.error(f"Exception in DebugTimerTask: {e}", exc_info=True)
		finally:
			self.logger.info("DebugTimerTask thread exiting.")

class TestApplication(unittest.TestCase):
	def create_timer_task(self, now, count=10):
		nowx = now.replace(minute=0,second=0,microsecond=0)
		eventlist = [TickMessage(nowx + timedelta(minutes=ix), ix) for ix in range(count)];
		return eventlist

#	@unittest.skip("Skipping start/stop test to avoid long waits during routine testing.")
	def test_start_configure_stop(self):
		app = Application("TestApp")
		app.start()
#		TICKS = 60*24
#		eventlist = self.create_timer_task(datetime.now(), TICKS)
		storage = storage_path()
		options = StartOptions(basePath=None, storagePath=storage, hardReset=False)
		app.send(StartEvent(options))
		# Wait for the started event to be set
		started = app.app_started.wait(timeout=1)
		self.assertTrue(started, "Application did not start as expected.")
		if started:
			# Wait for the stopped event to be set
			stopped = app.app_stopped.wait()
			self.assertTrue(stopped, "Application did not stop as expected.")

		app.join()
		self.assertFalse(app.is_alive(), "Application thread did not quit as expected.")
		appstopped = app.app_stopped.is_set()
		self.assertTrue(appstopped, "Application did not set app_stopped event as expected.")
		tkstopped = app.stopped.is_set()
		self.assertTrue(tkstopped, "Application did not set stopped event as expected.")

#		self.assertEqual(TICKS - 1, app.scheduler.lastTickSeen.tick_number, "scheduler ticks failed")
#		self.assertIsNotNone(app.display.lastTickSeen, "display lastTickSeen failed")
#		self.assertEqual(TICKS - 1, app.display.lastTickSeen.tick_number, "display ticks failed")

if __name__ == "__main__":
    unittest.main()