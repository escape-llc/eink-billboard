import logging

from ...task.messages import BasicMessage
from ..plugin_base import BasicExecutionContext2, PluginProtocol, TrackType


class DebugPlugin(PluginProtocol):
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

	def start(self, context: BasicExecutionContext2, track: TrackType) -> None:
		self.logger.info(f"'{self.name}' start '{track.title}'")
	def stop(self, context: BasicExecutionContext2, track: TrackType) -> None:
		self.logger.info(f"'{self.name}' stop '{track.title}'")
	def receive(self, context: BasicExecutionContext2, track: TrackType, msg: BasicMessage) -> None:
		self.logger.info(f"'{self.name}' '{track.title}' receive: {msg}")
