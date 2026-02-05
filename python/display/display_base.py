from abc import ABC, abstractmethod
from PIL import Image

from ..model.configuration_manager import ConfigurationManager

class DisplayBase(ABC):
	def __init__(self, name: str):
		self.name = name
	@abstractmethod
	def initialize(self, cm: ConfigurationManager):
		pass
	@abstractmethod
	def shutdown(self):
		pass
	@abstractmethod
	def render(self, img: Image.Image, title: str|None = None):
		pass
