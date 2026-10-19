from abc import ABC, abstractmethod
from typing import Any, Mapping
from PIL import Image

from .refresh_gate import DEFAULT_REST_SECONDS, RefreshGate
from ..model.configuration_manager import ConfigurationManager

class DisplayBase(ABC):
	# the least rest this model accepts between refreshes, whatever the setting says; 0 unless a datasheet requires one
	MIN_REST_SECONDS = 0.0
	def __init__(self, name: str):
		self.name = name
		# the rest between refreshes (see refresh_gate.py); `initialize` sets it from the display settings
		self.gate = RefreshGate(DEFAULT_REST_SECONDS, self.MIN_REST_SECONDS)
	def start_gate(self, settings: Mapping[str, Any]|None) -> None:
		"""The rest after a refresh, from the display settings (`refreshInterval`, seconds); a missing or unusable value is the default. Called by `initialize`."""
		value = (settings or {}).get("refreshInterval", DEFAULT_REST_SECONDS)
		rest = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else DEFAULT_REST_SECONDS
		self.gate = RefreshGate(rest, self.MIN_REST_SECONDS)
	def ready_in(self) -> float:
		"""Seconds until the panel may be sent another image (0: now)."""
		return self.gate.ready_in()
	@abstractmethod
	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		...
	@abstractmethod
	def shutdown(self) -> None:
		...
	@abstractmethod
	def render(self, img: Image.Image, id: int, title: str|None = None) -> None:
		...
