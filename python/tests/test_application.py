from datetime import datetime, timedelta
import threading
from typing import Callable
import unittest
import time
import logging

from .utils import storage_path, MessageTriggerSink
from ..task.application import Application
from ..task.messages import BasicMessage, MessageSink, QuitMessage, StartEvent, StartOptions, StopEvent, Telemetry
from ..task.timer_tick import BasicTimer, TickMessage

TICK_RATE = 0.05
TICK_RATE = 1

logging.basicConfig(
	level=logging.DEBUG,  # Or DEBUG for more detail
	format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

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
		# stop when playlist_layer gets to the 4th track (index 3)
		stopsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and msg.name == "playlist_layer" and msg.values.get("current_track_index", None) == 3)
		app = Application("TestApp", stopsink)
		app.start()
		storage = storage_path()
		options = StartOptions(basePath=None, storagePath=storage, hardReset=False)
		app.send(StartEvent(options))
		# Wait for the started event to be set
		started = app.app_started.wait(timeout=1)
		self.assertTrue(started, "Application did not start as expected.")
		if started:
			# wait on the stop sink, then send QuitMessage
			sinkstopped = stopsink.stopped.wait(timeout=120)
			self.assertTrue(sinkstopped, "Stop Sink did not stop as expected.")
			app.send(StopEvent())
			# Wait for the stopped event to be set
			stopped = app.app_stopped.wait()
			self.assertTrue(stopped, "Application did not stop as expected.")

		app.send(QuitMessage())
		app.join(timeout=2)
		self.assertFalse(app.is_alive(), "Application thread did not quit as expected.")
		appstopped = app.app_stopped.is_set()
		self.assertTrue(appstopped, "Application did not set app_stopped event as expected.")
		tkstopped = app.stopped.is_set()
		self.assertTrue(tkstopped, "Application did not set stopped event as expected.")

if __name__ == "__main__":
    unittest.main()