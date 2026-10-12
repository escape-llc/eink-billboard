from queue import ShutDown
import threading
import logging
from datetime import datetime
from typing import Callable, List

from .protocols import MessageSink
from .messages import BasicMessage, Telemetry
from ..utils.error_image import error_detail, safe_reason
from .basic_task import TaskStoppedError

class Route:
	def __init__(self, name:str, receivers:List[MessageSink]):
		self.name = name
		self.receivers = receivers

class MessageRouter:
	def __init__(self):
		self.routes = {}
		self.logger = logging.getLogger(__name__)
		self.lock = threading.Lock()
		# where a failed delivery is reported: the telemetry route's send (set once the route exists)
		self.failure_sink: Callable[[Telemetry], None]|None = None

	def addRoute(self, route:Route):
		with self.lock:
			self.routes.setdefault(route.name, route)

	def send(self, route:str, msg: BasicMessage):
		with self.lock:
			rroute = self.routes.get(route, None)
			if rroute is not None:
				for kx in rroute.receivers:
					try:
						kx.accept(msg)
					except (ShutDown, TaskStoppedError):
						# the receiver has stopped (normal during shutdown): nothing to deliver to
						self.logger.debug(f"send: receiver of '{route}' is stopped, message dropped: {type(msg).__name__}")
					except Exception as e:
						self.logger.error(f"send.unexpected on '{route}': {e}", exc_info=True)
						if route != "telemetry" and self.failure_sink is not None:
							self.failure_sink(Telemetry(datetime.now().astimezone(), "router", { "kind": "error", "message": f"A message to '{route}' could not be delivered: {safe_reason(e)}", "detail": error_detail(e) }))
