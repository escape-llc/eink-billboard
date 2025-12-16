import logging
from datetime import datetime, timedelta

from .messages import FutureCompleted
from ..plugins.plugin_base import PluginBase, PluginExecutionContext
from ..model.configuration_manager import ConfigurationManager
from ..model.schedule import MasterSchedule, TimedSchedule
from .application import ConfigureEvent
from .active_plugin import ActivePlugin
from .display import DisplaySettings
from .timer_tick import TickMessage
from .basic_task import DispatcherTask
from .message_router import MessageRouter

class Scheduler(DispatcherTask):
	def __init__(self, name, router: MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self._register_handler(ConfigureEvent, self._configure_event)
		self._register_handler(DisplaySettings, self._display_settings)
		self._register_handler(FutureCompleted, self._future_completed)
		self._register_handler(TickMessage, self._tick_message)
		self.router = router
		self.schedules = []
		self.master_schedule:MasterSchedule = None
		self.cm:ConfigurationManager = None
		self.plugin_info = None
		self.plugin_map = None
		self.current_schedule_state = None
		self.active_plugin:ActivePlugin = None
		self.resolution = [800,480]
		self.state = 'uninitialized'
		self.lastTickSeen:TickMessage = None
		self.logger = logging.getLogger(__name__)

	def calculate_current_state(self, schedule_ts: datetime, tick: TickMessage):
		current = self.master_schedule.evaluate(schedule_ts)
#		self.logger.info(f"Current schedule {tick.tick_ts}[{tick.tick_number}]{schedule_ts}: {current}")
		if current:
			# locate schedule from items
			self.logger.info(f"Selecting schedule: {current.name} ({current.schedule})")
			schedule = next((sx for sx in self.schedules if sx.get("name", None) and sx["name"] == current.schedule), None)
			if schedule and "info" in schedule and isinstance(schedule["info"], TimedSchedule):
				# get the active time slot
				target:TimedSchedule = schedule["info"]
				timeslot = target.current(schedule_ts)
#				self.logger.info(f"Current slot {timeslot}")
				if timeslot:
					if self.plugin_map.get(timeslot.plugin_name, None):
#						self.logger.debug(f"selecting plugin '{timeslot.plugin_name}' with args {timeslot.content}")
						plugin = self.plugin_map[timeslot.plugin_name]
						if isinstance(plugin, PluginBase):
							return { "plugin": plugin, "timeslot": timeslot, "schedule": target, "tick": tick, "schedulets": schedule_ts }
						else:
							errormsg = f"Plugin '{timeslot.plugin_name}' is not a valid PluginBase instance."
							self.logger.error(errormsg)
							return { "plugin": plugin, "timeslot": timeslot, "schedule": target, "tick": tick, "schedulets": schedule_ts, "error": errormsg }
					else:
						errormsg = f"Plugin '{timeslot.plugin_name}' is not available."
						self.logger.error(errormsg)
						return { "plugin": None, "timeslot": timeslot, "schedule": target, "tick": tick, "schedulets": schedule_ts, "error": errormsg }
				else:
					self.logger.debug("No timeslot found")
					return { "plugin":None, "timeslot": None, "schedule":target, "tick": tick, "schedulets": schedule_ts }
		return None

	def evaluate_schedule_state(self, schedule_ts: datetime, schedule_state):
#		self.logger.debug(f"'{self.name}' evaluate_schedule_state: {self.current_schedule_state} {schedule_state}")
		if self.current_schedule_state is None:
			if schedule_state is not None:
				schedule = schedule_state["schedule"]
				timeslot = schedule_state["timeslot"]
				selected = f"{schedule.id}/{timeslot.id}"
				self.logger.info(f"timeslot starting {selected}")
				if self.active_plugin is not None:
					self.active_plugin.shutdown(True)
					self.active_plugin = None
				self.active_plugin = ActivePlugin(timeslot.plugin_name, self)
				try:
					(plugin,ctx) = self.create_context(schedule_ts, schedule_state)
					plugin.timeslot_start(ctx)
					if self.active_plugin.state == "ready":
						plugin.schedule(ctx)
				except Exception as e:
					self.logger.error(f"Error executing plugin '{timeslot.plugin_name}': {e}", exc_info=True)
			else:
				self.logger.warning(f"no timeslot selected; current_schedule_state is None")
				pass
		else:
			if schedule_state is not None:
				pschedule = self.current_schedule_state["schedule"]
				ptimeslot = self.current_schedule_state["timeslot"]
				timeslot = schedule_state["timeslot"]
				schedule = schedule_state["schedule"]
				selected = f"{schedule.id}/{timeslot.id}"
				current = f"{pschedule.id}/{ptimeslot.id}"
				self.logger.debug(f"timeslots selected {selected} current {current}")
				if selected == current:
					self.logger.debug(f"same timeslot {current}")
					if self.active_plugin is not None:
						self.active_plugin.check_alarm_clock(schedule_ts)
						if self.active_plugin.state == "ready":
							try:
								(plugin,ctx) = self.create_context(schedule_ts, schedule_state)
								plugin.schedule(ctx)
							except Exception as e:
								self.logger.error(f"Error executing plugin '{timeslot.plugin_name}': {e}", exc_info=True)
				else:
					self.logger.debug(f"timeslot ending {current}")
					if self.active_plugin is not None:
						self.active_plugin.shutdown(True)
					try:
						(plugin,ctx) = self.create_context(schedule_ts, self.current_schedule_state)
						plugin.timeslot_end(ctx)
					except Exception as e:
						self.logger.error(f"Error executing plugin '{timeslot.plugin_name}': {e}", exc_info=True)
					self.logger.debug(f"timeslot starting {selected}")
					self.active_plugin = ActivePlugin(timeslot.plugin_name, self)
					try:
						(plugin,ctx) = self.create_context(schedule_ts, schedule_state)
						plugin.timeslot_start(ctx)
						if self.active_plugin.state == "ready":
							plugin.schedule(ctx)
					except Exception as e:
						self.logger.error(f"Error executing plugin '{timeslot.plugin_name}': {e}", exc_info=True)
			else:
				self.logger.warning(f"no timeslot selected; current_schedule_state is not None")
				pass
			pass
		self.current_schedule_state = schedule_state

	def create_context(self, schedule_ts: datetime, schedule_state) -> tuple[PluginBase, PluginExecutionContext]:
		if self.active_plugin is None:
			raise ValueError(f"active_plugin is None")
		if schedule_state.get("error",None) is not None:
			raise ValueError(f"'{self.name}' {schedule_state['error']}.")
		if schedule_state.get("timeslot", None) is None:
			raise ValueError(f"'{self.name}' no timeslot was selected.")
		if schedule_state.get("plugin", None) is None:
			raise ValueError(f"'{self.name}' no plugin was selected.")
		plugin = schedule_state["plugin"]
		timeslot = schedule_state["timeslot"]
		psm = self.cm.plugin_manager(timeslot.plugin_name)
		scm = self.cm.settings_manager()
		stm = self.cm.static_manager()
		ctx = PluginExecutionContext(timeslot, stm, scm, psm, self.active_plugin, self.resolution, schedule_ts, self.router)
		return (plugin, ctx)

	def _configure_event(self, msg: ConfigureEvent):
		self.cm = msg.content.cm
		try:
			plugin_info = self.cm.enum_plugins()
			plugins = self.cm.load_plugins(plugin_info)
			self.logger.info(f"Plugins loaded: {list(plugins.keys())}")
			self.plugin_info = plugin_info
			self.plugin_map = plugins
			sm = self.cm.schedule_manager()
			schedule_info = sm.load()
			sm.validate(schedule_info)
			self.master_schedule = schedule_info.get("master", None)
			self.schedules = schedule_info.get("schedules", [])
			self.logger.info(f"schedule loaded")
			self.state = 'loaded'
			msg.notify()
		except Exception as e:
			self.logger.error(f"Failed to load/validate schedules: {e}", exc_info=True)
			self.state = 'error'
			msg.notify(True, e)
	def _display_settings(self, msg: DisplaySettings):
		self.logger.info(f"'{self.name}' DisplaySettings {msg.name} {msg.width} {msg.height}.")
		self.resolution = [msg.width, msg.height]
	def _future_completed(self, msg: FutureCompleted):
		# make sure the active plugin is same as what generated this message
		self.logger.info(f"'{self.name}' FutureCompleted {msg.plugin_name}:{msg.token} {msg.is_success}.")
		if self.active_plugin is None:
			self.logger.warning(f"Message arrived late, discarded. No active plugin")
		else:
			if self.active_plugin.name == msg.plugin_name:
				if self.active_plugin.state != "future":
					self.logger.warning(f"Active plugin state mismatch. expected 'future' actual '{self.active_plugin.state}'")
				self.active_plugin.state = "notify"
				try:
					(plugin,ctx) = self.create_context(self.lastTickSeen.tick_ts, self.current_schedule_state)
					plugin.receive(ctx, msg)
					self.active_plugin.notify_complete()
				except Exception as e:
					self.logger.error(f"Error executing plugin '{self.active_plugin.name}': {e}", exc_info=True)
			else:
				self.logger.warning(f"Message arrived late, discarded. Active plugin is {self.active_plugin.name}")
	def _tick_message(self, msg: TickMessage):
		self.lastTickSeen = msg
		# Perform scheduled tasks
		if self.state != 'loaded':
			self.logger.warning(f"'{self.name}' waiting for configuration. Current state: {self.state}")
			return
		if self.master_schedule is None:
			self.logger.error(f"'{self.name}' has no schedule loaded.")
			return
		schedule_ts = msg.tick_ts.replace(second=0,microsecond=0)
		for schedule in self.schedules:
			info = schedule.get("info", None)
			if info is not None and isinstance(info, TimedSchedule):
				info.set_date_controller(lambda: schedule_ts)
		self.logger.info(f"schedule {msg.tick_ts}[{msg.tick_number}]: {schedule_ts}")
		schedule_state = self.calculate_current_state(schedule_ts, msg)
#			self.logger.info(f"schedule state {schedule_state}")
		self.evaluate_schedule_state(schedule_ts, schedule_state)
