from typing_extensions import Protocol
from typing import TypeVar, Type, Optional, runtime_checkable
import threading

T = TypeVar('T')

@runtime_checkable
class IServiceProvider(Protocol):
	def get_service(self, service_type: Type[T]) -> Optional[T]:
		...
	def required(self, service_type: Type[T]) -> T:
		"""
		Return the requested service instance, raising ValueError if not available.
		
		:param self: Description
		:param service_type: Description
		:type service_type: Type[T]
		:return: Description
		:rtype: T
		"""
		inst = self.get_service(service_type)
		if inst is None:
			raise ValueError(f"Required service {service_type} is not available.")
		return inst

@runtime_checkable
class IServiceContainer(IServiceProvider, Protocol):
	def add_service(self, service_type: Type[T], service_instance: T) -> None:
		...

class ServiceContainer(IServiceContainer):
	def __init__(self, parent: IServiceProvider | None = None):
		self._services: dict[Type, object] = {}
		self._parent = parent
		# Reentrant lock to allow safe concurrent access to this container's registry
		self._lock = threading.RLock()

	def get_service(self, service_type: Type[T]) -> Optional[T]:
		# First, check local registry under lock
		with self._lock:
			inst = self._services.get(service_type, None)
			if inst is not None:
				return inst  # type: ignore[return-value]
		# If not found locally, delegate to parent without holding our lock
		if self._parent is not None:
			return self._parent.get_service(service_type)
		return None

	def add_service(self, service_type: Type[T], service_instance: T) -> None:
		if service_instance is None:
			raise ValueError("service_instance cannot be None.")
		with self._lock:
			if service_type in self._services:
				raise ValueError(f"Service of type {service_type} is already registered.")
			self._services[service_type] = service_instance