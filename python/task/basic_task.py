import threading
import queue
import logging
from typing import Callable, Type
from .messages import MessageSink, BasicMessage, QuitMessage

class CoreTask(threading.Thread, MessageSink):
	"""
	Core threading and message-queue logic shared by task implementations.

	Subclasses must implement `_dispatch(msg)` to handle messages pulled from the internal queue.

	`CoreTask` provides `run()`, `send()` and a default `quitMsg()` implementation used by tasks to stop gracefully.
	"""

	def __init__(self, name=None):
		super().__init__(daemon=True)
		self.msg_queue = queue.Queue()
		self.name = name or self.__class__.__name__
		self.stopped = threading.Event()
		self.logger = logging.getLogger(__name__)

	def run(self):
		self.logger.info(f"'{self.name}' start.")
		running = True
		while running:
			try:
				msg = self.msg_queue.get()
				self._dispatch(msg)
				self.msg_queue.task_done()
			except queue.ShutDown:
				self.logger.debug(f"Queue shut down")
				running = False
				self.stopped.set()
			except Exception as e:
				self.msg_queue.task_done()
				self.logger.error(f"'{self.name} unhandled", e)
		self.logger.info(f"'{self.name}' end {self.msg_queue.qsize()}.")

	def quitMsg(self, msg: QuitMessage):
		"""Default QuitMessage handling: mark stopped and log."""
		self.stopped.set()
		self.logger.info(f"'{self.name}' Quit.")

	def send(self, msg: BasicMessage):
		if self.msg_queue.is_shutdown:
			raise ValueError("Cannot send message to stopped task.")
		self.msg_queue.put(msg)
		if isinstance(msg, QuitMessage):
			self.msg_queue.shutdown()


type HandlerFunc = Callable[[BasicMessage], None]
class DispatcherTask(CoreTask):
	"""Task that dispatches messages to handlers registered by message class.

	Methods are auto-scanned in the ctor based on type hints of the first argument.
	Handlers are keyed by the exact message class, then subclasses.

	Registering a handler for `QuitMessage` (or any subclass thereof) is not allowed —
	quit messages are handled identically to `CoreTask`.
	"""
	def __init__(self, name=None):
		super().__init__(name=name)
		self.handlers: dict[Type[BasicMessage], HandlerFunc] = {}
		self._populate_registry()

	def _populate_registry(self):
		# 1. Inspect all bound methods
		for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
			if name.startswith("__"):
				continue
			if name == "quitMsg" or name == "_dispatch" or name == "send":
				continue
			# 2. Get signature (excludes 'self' for bound methods)
			sig = inspect.signature(method)
			params = list(sig.parameters.values())
			if params and len(params) == 1:
				# 3. Extract the type hint of the first argument
				param_type = params[0].annotation
				# 4. Filter and store if it matches your base type
				if inspect.isclass(param_type) and issubclass(param_type, BasicMessage) and not issubclass(param_type, QuitMessage):
					self.handlers[param_type] = method

	def _dispatch(self, msg: BasicMessage):
		if isinstance(msg, QuitMessage):
			try:
				self.quitMsg(msg)
			except Exception as e:
				self.logger.error(f"quit.unhandled '{self.name}': {e}", exc_info=True)
			return

		# Handler lookup: attempt exact class, then search superclasses up to BasicMessage
		handler = None
		matched_cls = None
		for cls in type(msg).mro():
			# stop looking once we reach BasicMessage's base classes
			if cls is object:
				break
			# only consider subclasses of BasicMessage
			try:
				issub = issubclass(cls, BasicMessage)
			except TypeError:
				issub = False
			if not issub:
				continue
			# check for a registered handler for this class
			hx = self.handlers.get(cls)
			if hx is not None:
				handler = hx
				matched_cls = cls
				break

		if handler is not None:
			try:
				handler(msg)
			except Exception as e:
				self.logger.error(f"handler.unhandled '{self.name}': {e}", exc_info=True)
		else:
			# Treat missing handler as an error
			self.logger.error(f"'{self.name}' no handler for message type: {type(msg)}")

import functools

def register_by_type(registry_key_type):
	"""Tags the method with a type key for the constructor to find."""
	def decorator(func):
		# Attach metadata to the function for registration
		func._registry_key = registry_key_type
		
		@functools.wraps(func)
		def wrapper(self, lookup_dict, *args, **kwargs):
			# args[0:] correspond to original args[2:]
			modified_args = list(args)
			for ix in range(len(modified_args)):
				val = modified_args[ix]
				# Replace based on type lookup from the config dict
				modified_args[ix] = lookup_dict.get(type(val), None)
			
			return func(self, lookup_dict, *modified_args, **kwargs)
		return wrapper
	return decorator

class MyClass:
	def __init__(self):
		self.registry = {}
		# Scan class for decorated methods to populate the local registry
		for attr_name in dir(self):
			attr = getattr(self, attr_name)
			# Check if the wrapper's underlying function was tagged
			if hasattr(attr, '__wrapped__'):
				original_func = attr.__wrapped__
				if hasattr(original_func, '_registry_key'):
					key = original_func._registry_key
					# Store the BOUND method (already has 'self')
					self.registry[key] = attr

	@register_by_type(str)
	def process_str(self, config, val_a, val_b):
		print(f"String logic executed: {val_a}, {val_b}")

	@register_by_type(int)
	def process_int(self, config, val_a, val_b):
		print(f"Int logic executed: {val_a}, {val_b}")

# --- Usage ---
obj = MyClass()
config = {str: "REPLACED", int: 777}

# Since methods are ONLY called via registry, we use the type key
# Because the constructor bound the methods, we don't pass 'obj' again
obj.registry[str](config, "original_a", "original_b")
# Output: String logic executed: REPLACED, REPLACED

obj.registry[int](config, 0, 1.5) 
# Output: Int logic executed: 777, None (1.5 is float, not in config)

import inspect
from typing import Type, Callable

class MyTargetBaseType: pass
class MySubClassA(MyTargetBaseType): pass
class MySubClassB(MyTargetBaseType): pass

class MethodMapper:
	def __init__(self):
		# Dictionary to store {ParamType: BoundMethod}
		self.method_registry: dict[Type, Callable] = {}

		# 1. Inspect all bound methods
		for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
			if name.startswith("__"):
				continue

			# 2. Get signature (excludes 'self' for bound methods)
			sig = inspect.signature(method)
			params = list(sig.parameters.values())

			if params:
				# 3. Extract the type hint of the first argument
				param_type = params[0].annotation

				# 4. Filter and store if it matches your base type
				if inspect.isclass(param_type) and issubclass(param_type, BasicMessage):
					self.method_registry[param_type] = method

	def handle_a(self, data: MySubClassA):
		print(f"Executing handle_a with {type(data).__name__}")

	def handle_b(self, data: MySubClassB):
		print(f"Executing handle_b with {type(data).__name__}")

# Example Usage
mapper = MethodMapper()
print(f"Registry: {mapper.method_registry}")

# Dynamic dispatch using the stored types
obj = MySubClassA()
if type(obj) in mapper.method_registry:
	mapper.method_registry[type(obj)](obj)
