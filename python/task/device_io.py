"""
The DeviceIO task: the single owner of every GPIO, I2C and SPI line that is not the panel's.

The display's driver stage keeps the panel's lines; whatever else is connected to the Pi (buttons now, sensors later) is opened, listened to and closed here. This task knows hardware and nothing
about what an input means: a device reports that something happened (`InputEvent`) and the Application decides what that does (python/device/bindings.py). Hardware libraries are imported by
the devices, only when they are opened.

A device calls `emit` from whatever thread its library uses; `emit` only puts an `InputEvent` on this task's queue, and everything else (forwarding it on the `device-input` route, opening and
closing devices, reading the settings) happens on the task's own thread. The settings are the `devices` document: a change is read again, after a short wait for a burst of saves to end,
and a configuration that cannot be opened leaves the previous one working.
"""
import logging
from typing import Any, Callable, Mapping

from .basic_task import DispatcherTask, handles
from .coalescer import Coalescer
from .configure_event import ConfigureEvent
from .message_router import MessageRouter
from .messages import ConfigurationChanged, InputEvent, ReloadDevices, Telemetry
from ..device.base import InputDevice
from ..device.buttons import physical_words
from ..device.pins import Panel, check_pins
from ..device.registry import available_devices
from ..model.configuration_manager import ConfigurationManager
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..plugins.plugin_base import PermanentError

SETTINGS = "devices"

class DeviceIO(DispatcherTask):
	# how long a burst of saves of the settings is waited out before they are read again
	RELOAD_DELAY_SECONDS = 2.0

	def __init__(self, name: str, router: MessageRouter, devices: Mapping[str, Callable[[], InputDevice]]|None = None):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		# what makes each device, by id (a test gives fakes)
		self._makers = dict(devices) if devices is not None else available_devices()
		self.cm: ConfigurationManager|None = None
		self.panel: Panel|None = None
		self.timebase: TimeOfDay|None = None
		# the devices that are open, by id, and the settings they were opened with
		self._open: dict[str, InputDevice] = {}
		self._config: dict[str, Any] = {}
		self._reload_coalescer = Coalescer(self.RELOAD_DELAY_SECONDS, self._request_reload)
		self.logger = logging.getLogger(__name__)

	@property
	def open_devices(self) -> tuple[str, ...]:
		"""The ids of the devices that are open (what the status says is connected)."""
		return tuple(self._open)

	def emit(self, source: str, name: str, gesture: str) -> None:
		"""What a device calls from its own thread: the event goes on this task's queue, and nothing else is done there."""
		try:
			self.accept(InputEvent((self.timebase or SystemTimeOfDay()).current_time(), source, name, gesture))
		except ValueError:
			# this task has stopped: nobody is listening any more
			self.logger.debug(f"'{self.name}' stopped before the {source} {name} {gesture}.")

	# ---- messages ---------------------------------------------------------------------------------------------------------------------------------------

	@handles(ConfigureEvent)
	def _configure_event(self, msg: ConfigureEvent):
		try:
			self.cm = msg.content.cm
			tod = msg.content.isp.get_service(TimeOfDay)
			self.timebase = tod if tod is not None else SystemTimeOfDay()
			self.panel = msg.content.isp.get_service(Panel)
			opened = self._apply(self._read_settings())
			# said where a person looks (Activity), as a reload says it: at the start too, so a button that works is seen to, and one that cannot be opened is not only in the log
			if opened:
				self._tell(f"GPIO is set up: {', '.join(opened)}.")
			msg.notify(False, { "open": list(opened) })
		except Exception as e:
			self.report_failure("The GPIO inputs could not be opened", e)
			msg.notify(True, e)

	@handles(ConfigurationChanged)
	def _configuration_changed(self, msg: ConfigurationChanged):
		# the devices' settings are in the settings area; any change there is a reason to look (the document itself is compared when it is read)
		if msg.area in ("settings", "restore") and self.cm is not None and not self.is_stopped():
			self._reload_coalescer.trigger()

	def _request_reload(self):
		"""On the coalescer's thread: hand the work to the task's own thread."""
		if self.is_stopped() or self.timebase is None:
			return
		try:
			self.accept(ReloadDevices(self.timebase.current_time()))
		except ValueError:
			self.logger.debug(f"'{self.name}' stopped before the reload.")

	@handles(ReloadDevices)
	def _reload_devices(self, msg: ReloadDevices):
		if self.cm is None:
			return
		try:
			settings = self._read_settings()
		except Exception as e:
			self.report_failure("The GPIO settings could not be read", e)
			return
		if settings == self._config:
			return
		try:
			wanted = self._plan(settings)
		except Exception as e:
			# refused before anything was touched: what works keeps working
			self.report_failure("The changed GPIO settings could not be used", e)
			return
		try:
			opened = self._open_wanted(wanted, settings)
			self.logger.info(f"'{self.name}' devices open: {', '.join(opened) or 'none'}")
			self._tell("GPIO was set up again" + (f": {', '.join(opened)}." if opened else ": nothing is connected."))
		except Exception as e:
			# the old devices were closed to make room for the new ones: put them back, so a bad save does not leave the buttons dead
			previous = self._config
			self.report_failure("The changed GPIO settings could not be used", e)
			try:
				self._apply(previous)
			except Exception as again:
				self.report_failure("The previous GPIO settings could not be restored either", again)

	@handles(InputEvent)
	def _input_event(self, msg: InputEvent):
		"""An event a device reported: said as it happened (the pin level: the web app shows the wiring works), then on to the Application, which gives it its meaning."""
		try:
			self.router.send("telemetry", Telemetry(msg.timestamp, "device-io", { "kind": "gpio", "input": msg.name, "gesture": msg.gesture, "message": physical_words(msg.name, msg.gesture) }))
		except Exception as e:
			self.logger.warning(f"The input could not be reported ({type(e).__name__}).")
		self.router.send("device-input", msg)

	def quitMsg(self, msg):
		self._reload_coalescer.cancel()
		self._close_all()
		super().quitMsg(msg)

	# ---- devices ----------------------------------------------------------------------------------------------------------------------------------------

	def _read_settings(self) -> dict[str, Any]:
		"""The `devices` document (none stored yet is none connected)."""
		assert self.cm is not None
		_, content = self.cm.settings_manager().open(SETTINGS).get()
		return dict(content) if isinstance(content, dict) else {}

	def _close_all(self) -> None:
		devices, self._open = self._open, {}
		for device_id, device in devices.items():
			try:
				device.close()
			except Exception:
				self.logger.debug(f"'{self.name}' device '{device_id}' did not close cleanly", exc_info=True)

	def _plan(self, settings: dict[str, Any]) -> dict[str, InputDevice]:
		"""
		The devices the settings ask for (a device with no pin set is not asked for: nothing is imported or claimed for it). The pins are checked against the panel's lines and against each
		other first, so nothing is opened with a clash: a `PermanentError` in our words, and nothing has been touched.
		"""
		devices = { device_id: make() for device_id, make in self._makers.items() }
		wanted = { device_id: device for device_id, device in devices.items() if device.pins(settings) }
		pins = { f"{device_id}:{name}": pin for device_id, device in wanted.items() for name, pin in device.pins(settings).items() }
		labels = { f"{device_id}:{name}": "button" for device_id, device in wanted.items() for name in device.pins(settings) }
		problems = check_pins(pins, self.panel, labels)
		if problems:
			raise PermanentError(" ".join(problems))
		return wanted

	def _apply(self, settings: dict[str, Any]) -> tuple[str, ...]:
		"""Open what the settings say, after closing what was open. Raises (our words) when it cannot be done."""
		return self._open_wanted(self._plan(settings), settings)

	def _open_wanted(self, wanted: dict[str, InputDevice], settings: dict[str, Any]) -> tuple[str, ...]:
		"""Close what is open and open `wanted`; when one cannot be opened whatever was opened is closed again and it raises."""
		self._close_all()
		try:
			for device_id, device in wanted.items():
				device.open(self.emit_for(device_id), settings)
				self._open[device_id] = device
		except Exception:
			self._close_all()
			raise
		self._config = dict(settings)
		return tuple(self._open)

	def emit_for(self, source: str) -> Callable[[str, str], None]:
		"""`emit` for one device: it says which device the event is from."""
		def emit(name: str, gesture: str) -> None:
			self.emit(source, name, gesture)
		return emit

	def _tell(self, message: str) -> None:
		"""Tell the telemetry link what happened to the devices."""
		try:
			now = (self.timebase or SystemTimeOfDay()).current_time()
			self.router.send("telemetry", Telemetry(now, "device-io", { "kind": "devices", "message": message }))
		except Exception as e:
			self.logger.warning(f"Device telemetry could not be sent ({type(e).__name__}).")
