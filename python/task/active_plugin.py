from concurrent.futures import Executor, ThreadPoolExecutor
import datetime
from .messages import FutureCompleted, MessageSink

class ActivePlugin:
	def __init__(self, plugin_name:str, completion_port:MessageSink, initial_state:str="ready"):
		if plugin_name is None:
			raise ValueError("plugin_name is None")
		if completion_port is None:
			raise ValueError("completion_port is None")
		self.name = plugin_name
		# ready,sleep,future,notify
		self.state = initial_state
		self.wakeup_ts:datetime = None
		self.executor:Executor = None
		self.port = completion_port

	def alarm_clock(self, wakeup_ts:datetime):
		if self.state == "shutdown":
			raise ValueError(f"Already Shutdown '{self.state}'")
		if self.state == "future":
			raise ValueError(f"Not in state for alarm '{self.state}'")
		self.state = "sleep"
		self.wakeup_ts = wakeup_ts

	def future(self, token:str, cx:callable):
		if self.state == "shutdown":
			raise ValueError(f"Already Shutdown '{self.state}'")
		if self.state == "sleep":
			raise ValueError(f"Not in state for future '{self.state}'")
		if self.executor is None:
			self.executor = ThreadPoolExecutor(max_workers=1)

		p_future = self.executor.submit(cx)
		def _future_completed(fx):
			if fx.exception():
				self.port.accept(FutureCompleted(self.name, token, None, fx.exception()))
			else:
				self.port.accept(FutureCompleted(self.name, token, fx.result()))

		self.state = "future"
		p_future.add_done_callback(_future_completed)

	def notify_complete(self):
		if self.state == "notify":
			self.state = "ready"

	def shutdown(self,cancel_futures:bool = False):
		self.state = "shutdown"
		if self.executor is not None:
			self.executor.shutdown(cancel_futures=cancel_futures)

	def check_alarm_clock(self, schedule_ts:datetime):
		if self.state == "shutdown":
			return
		if self.state == "sleep":
			if self.wakeup_ts is None:
				self.state = "ready"
			elif schedule_ts >= self.wakeup_ts:
				self.state == "ready"
				self.wakeup_ts = None

