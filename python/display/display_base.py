from abc import ABC, abstractmethod
from PIL import Image

from ..model.configuration_manager import ConfigurationManager

class DisplayBase(ABC):
	def __init__(self, name: str):
		self.name = name
	@abstractmethod
	def initialize(self, cm: ConfigurationManager) -> tuple[int, int]:
		...
	@abstractmethod
	def shutdown(self) -> None:
		...
	@abstractmethod
	def render(self, img: Image.Image, id: int, title: str|None = None) -> None:
		...
