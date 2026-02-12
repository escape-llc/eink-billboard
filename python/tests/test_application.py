from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import unittest

from .utils import ScaledTimeOfDay, ScaledTimerService, storage_path, MessageTriggerSink
from ..model.service_container import ServiceContainer
from ..model.configuration_manager import ConfigurationManager
from ..model.time_of_day import TimeOfDay
from ..task.timer import IProvideTimer
from ..task.application import Application
from ..task.messages import QuitMessage, StartEvent, StartOptions, StopEvent, Telemetry

class TestApplication(unittest.TestCase):
	def test_start_configure_stop(self):
		# stop when playlist_layer gets to the 4th track (index 3)
		stopsink = MessageTriggerSink(lambda msg: isinstance(msg, Telemetry) and msg.name == "playlist_layer" and msg.values.get("current_track_index", None) == 3)
		app = Application("TestApp", stopsink)
		app.start()
		storage = storage_path()
		time_base = ScaledTimeOfDay(datetime.now().astimezone(), 60)
		timer = ScaledTimerService(60, ThreadPoolExecutor(thread_name_prefix="ApplicationSimulation", max_workers=5))
		options = StartOptions(basePath=None, storagePath=storage, hardReset=False)
		cm = ConfigurationManager(None, storage, None)
		root = ServiceContainer()
		root.add_service(TimeOfDay, time_base)
		root.add_service(IProvideTimer, timer)
		root.add_service(ConfigurationManager, cm)
		app.accept(StartEvent(options, root, time_base.current_time()))
		# Wait for the started event to be set
		started = app.app_started.wait(timeout=1)
		self.assertTrue(started, "Application did not start as expected.")
		if started:
			# wait on the stop sink, then send QuitMessage
			sinkstopped = stopsink.stopped.wait(timeout=120)
			self.assertTrue(sinkstopped, "Stop Sink did not stop as expected.")
			app.accept(StopEvent(time_base.current_time()))
			# Wait for the stopped event to be set
			stopped = app.app_stopped.wait()
			self.assertTrue(stopped, "Application did not stop as expected.")

		app.accept(QuitMessage(time_base.current_time()))
		app.join(timeout=2)
		self.assertFalse(app.is_alive(), "Application thread did not quit as expected.")
		appstopped = app.app_stopped.is_set()
		self.assertTrue(appstopped, "Application did not set app_stopped event as expected.")
		tkstopped = app.stopped.is_set()
		self.assertTrue(tkstopped, "Application did not set stopped event as expected.")

if __name__ == "__main__":
    unittest.main()