import asyncio
from concurrent.futures import Future
import logging
import threading
from typing import Any, Mapping, cast

from .display_messages import ComputedImage, DisplayImage, DisplaySettings, PriorityImage
from ..display.mock_display import MockDisplay
from ..display.tkinter_window import TkinterWindow
from ..display.display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..task.basic_task import DispatcherTask
from ..task.messages import AsyncTaskCompleted, BasicMessage, QuitMessage
from ..task.configure_event import ConfigureEvent
from ..task.protocols import IProvideTimer
from ..task.protocols import CreateTimerResult, IProvideTimer
from ..task.timer import TimerThreadService
from ..task.async_worker_pool import AsyncWorkerPool
from .message_router import MessageRouter
from ..utils.image_compositor import ImageCompositor
from ..utils.image_utils import apply_image_enhancement, change_orientation, resize_image

class Display(DispatcherTask):
	def __init__(self, name, router:MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm: ConfigurationManager | None = None
		self.display: DisplayBase | None = None
		self.timebase: TimeOfDay | None = None
		self.timer: IProvideTimer | None = None
		self.commit_timer: CreateTimerResult | None = None
		self.priority_timer: CreateTimerResult | None = None
		self.refresh_timer: CreateTimerResult | None = None
		self.compsitor = ImageCompositor()
		self.task_pool: AsyncWorkerPool | None = None
		self.resolution = (800, 480)
		self.commitq: asyncio.Queue[BasicMessage] | None = None
		self.priorityq: asyncio.Queue[PriorityImage] | None = None
		self.task_commit: tuple[Future, threading.Event] | None = None
		self.task_priority: tuple[Future, threading.Event] | None = None
		self.fut_render: tuple[Future, threading.Event] | None = None
		self.logger = logging.getLogger(__name__)

	def _stop_task(self, task:tuple[Future, threading.Event]):
		fut, donev = task
		if not fut.done():
			self.logger.info(f"task still running, cancel...")
			fut.cancel()
			self.logger.info(f"Waiting for task to complete...")
			donev.wait(timeout=2.0)
		else:
			self.logger.info(f"task completed.")
	def quitMsg(self, msg: QuitMessage):
		try:
			if self.task_commit is not None:
				self._stop_task(self.task_commit)
				self.task_commit = None
			if self.task_priority is not None:
				self._stop_task(self.task_priority)
				self.task_priority = None
			if self.task_render is not None:
				self._stop_task(self.task_render)
				self.task_render = None
			if self.task_pool is not None:
				self.task_pool.shutdown()
				self.task_pool = None
				self.commitq = None
				self.priorityq = None
			if self.display is not None:
				self.display.shutdown()
		except Exception as e:
			self.logger.error(f"shutdown.unhandled {str(e)}")
		finally:
			self.display = None
			super().quitMsg(msg)
		pass
	def _configure_event(self, msg: ConfigureEvent):
		try:
			self.cm = msg.content.cm
			tod = msg.content.isp.get_service(TimeOfDay)
			self.timebase = tod if tod is not None else SystemTimeOfDay()
			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			if display_settings is None:
				raise ValueError("display settings not found in configuration")
			display_type = cast(str, display_settings.get("display_type", None))
			if display_type == "mock":
				self.display = MockDisplay("mock")
			elif display_type == "tk":
				self.display = TkinterWindow("tk")
			else:
				raise ValueError(f"Unrecognized display type: '{display_type}'")
			ts = msg.content.isp.get_service(IProvideTimer)
			self.timer = ts if ts is not None else TimerThreadService(self.timebase)
			self.resolution = self.display.initialize(self.cm)
			self.logger.info(f"Loading display {display_type} {self.resolution[0]}x{self.resolution[1]}")
			self._start_tasks(self.display, self.compsitor, self.timebase, display_settings)
			msg.notify()
			self.router.send("display-settings", DisplaySettings(msg.timestamp, display_type, self.resolution[0], self.resolution[1], []))
		except Exception as e:
			self.logger.error(f"configure.unhandled: {str(e)}")
			msg.notify(True, e)
	def _start_tasks(self, display: DisplayBase, compositor: ImageCompositor, timebase: TimeOfDay, display_settings: dict) -> None:
		self.task_pool = AsyncWorkerPool()
		self.task_pool.start()
		task_future = self.task_pool.submit(self._task_create_queues(), None)
		self.commitq, renderq, self.priorityq = task_future.result()

		donev = threading.Event()
		def commit_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "commit_task", fut, donev))
		self.task_commit = (self.task_pool.submit(self._task_commit_timer(cast(asyncio.Queue[BasicMessage], self.commitq), renderq, timebase), callback=commit_callback), donev)
		donev2 = threading.Event()
		def priority_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "priority_task", fut, donev2))
		self.task_priority = (self.task_pool.submit(self._task_priority_image(cast(asyncio.Queue[PriorityImage], self.priorityq), cast(asyncio.Queue[BasicMessage], self.commitq), self.resolution, display_settings), callback=priority_callback), donev2)
		donev3 = threading.Event()
		def render_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "render_task", fut, donev3))
		self.task_render = (self.task_pool.submit(self._task_render_and_display(renderq, compositor, display, display_settings), callback=render_callback), donev3)
		pass
	async def _task_create_queues(self) -> tuple[asyncio.Queue[BasicMessage], asyncio.Queue[BasicMessage], asyncio.Queue[PriorityImage]]:
		commitq: asyncio.Queue[BasicMessage] = asyncio.Queue()
		renderq: asyncio.Queue[BasicMessage] = asyncio.Queue()
		priorityq: asyncio.Queue[PriorityImage] = asyncio.Queue()
		return (commitq, renderq, priorityq)
	async def _task_background_layer(self, commitq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, msg: DisplayImage):
		compositor.set_layer_background(msg)
		await commitq.put(BasicMessage(msg.timestamp))
	async def _task_priority_layer(self, priorityq: asyncio.Queue[PriorityImage], msg: PriorityImage):
		await priorityq.put(msg)
	async def _task_commit_timer(self, commitq: asyncio.Queue[BasicMessage], renderq: asyncio.Queue[BasicMessage], timebase: TimeOfDay):
		while True:
			self.logger.debug("Commit timer arming")
			_ = await commitq.get()
			self.logger.info("Commit timer triggered")
			commitq.task_done()
			while True:
				try:
					_ = await asyncio.wait_for(commitq.get(), timeout=2.0)
					commitq.task_done()
					self.logger.info("Commit timer extended")
				except asyncio.TimeoutError:
					self.logger.info("Commit timer ends")
					await renderq.put(BasicMessage(timebase.current_time()))
					# exit inner loop, wait for fresh message to reset commit timer
					break
				except Exception as e:
					self.logger.error(f"commit_timer.unhandled: {str(e)}")
	async def _task_render_and_display(self, taskq: asyncio.Queue[BasicMessage], compsitor: ImageCompositor, display: DisplayBase, display_settings: Mapping[str, Any]|None):
		rotate: bool = display_settings.get("rotate180", False) if display_settings is not None else False
		displayImageCount: int = 0
		while True:
			try:
				_ = await taskq.get()
				package = compsitor.commit()
				if package is None:
					self.logger.debug(f"Compositor no changes detected")
					continue
				the_image, the_title = package.render()
				if rotate: the_image = the_image.rotate(180)
				the_image = apply_image_enhancement(the_image, display_settings)

				displayImageCount += 1
				self.logger.info(f"Compositor v:{package.version} '{the_title}' ({displayImageCount})")
				display.render(the_image, displayImageCount, the_title)
				taskq.task_done()
				self.logger.debug(f"Start blanking period")
				await asyncio.sleep(60.0)
				self.logger.debug(f"End blanking period")
			except Exception as e:
				self.logger.error(f"_task_render_and_display.unhandled: {str(e)}")
		pass
	async def _task_priority_image(self, taskq: asyncio.Queue[PriorityImage], commitq: asyncio.Queue[BasicMessage], resolution: tuple[int, int], display_settings: Mapping[str, Any]|None):
		ori:str = display_settings.get("orientation", "landscape") if display_settings is not None else "landscape"
		while True:
			try:
				msg = await taskq.get()
				# Resize and adjust orientation
				image = change_orientation(msg.img, ori)
				image = resize_image(image, resolution)
				di = msg if image == msg.img else ComputedImage(msg.timestamp, msg.title, image, msg)
				self.compsitor.set_layer_priority(di)
				taskq.task_done()
				await commitq.put(BasicMessage(msg.timestamp))
				# TODO await the callback from the display task that the image was rendered before starting timer for the priority image
				await asyncio.sleep(msg.duration.total_seconds())
				self.compsitor.set_layer_priority(None)
				await commitq.put(BasicMessage(msg.timestamp))
			except Exception as e:
				self.logger.error(f"priority_image.unhandled: {str(e)}")
	def _priority_image(self, msg: PriorityImage):
		try:
			if self.cm is None:
				self.logger.error("No configuration manager available")
				return
			if self.display is None:
				self.logger.error("No driver is loaded")
				return
			if self.task_pool is None:
				self.logger.error("No task pool available")
				return
			if self.priorityq is None:
				self.logger.error("No priority queue available")
				return

			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			self.logger.info(f"Priority '{msg.title}' ({msg.duration})")

			fut  = self.task_pool.submit(self._task_priority_layer(self.priorityq, msg), None)
			fut.result();
		except Exception as e:
			self.logger.error("priorityimage.unhandled", e)
			pass
	def _display_image(self, msg: DisplayImage):
		try:
			if self.cm is None:
				self.logger.error("No configuration manager available")
				return
			if self.display is None:
				self.logger.error("No driver is loaded")
				return
			if self.task_pool is None:
				self.logger.error("No task pool available")
				return
			if self.commitq is None:
				self.logger.error("No commit queue available")
				return
			display_cob = self.cm.settings_manager().open("display")
			_, display_settings = display_cob.get()
			self.logger.info(f"Display '{msg.title}'")

			if display_settings is not None:
			# Resize and adjust orientation
				image = change_orientation(msg.img, display_settings.get("orientation", "landscape"))
				image = resize_image(image, self.resolution)
				di = msg if image == msg.img else ComputedImage(msg.timestamp, msg.title, image, msg)
				fut  = self.task_pool.submit(self._task_background_layer(self.commitq, self.compsitor, di), None)
				fut.result();
			else:
				fut  = self.task_pool.submit(self._task_background_layer(self.commitq, self.compsitor, msg), None)
				fut.result();
		except Exception as e:
			self.logger.error("displayimage.unhandled", e)
			pass
