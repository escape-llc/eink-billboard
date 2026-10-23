import asyncio
import hashlib
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
import logging
import threading
from typing import Any, Callable, Mapping, cast

from .display_messages import BlendImage, ComputedImage, DisplayImage, DisplaySettings, OverlayImage, OverlayRevoke, PriorityImage, PriorityRevoke
from .overlay_zones import ZONE_NAMES, Zone, zones_for
from ..display.refresh_gate import RefreshState
from ..display.display_base import DisplayBase
from ..model.configuration_manager import ConfigurationManager
from ..model.theme import current_palette
from ..model.time_of_day import SystemTimeOfDay, TimeOfDay
from ..task.basic_task import DispatcherTask, handles
from ..task.messages import AsyncTaskCompleted, BasicMessage, ConfigurationChanged, QuitMessage, Telemetry
from ..task.configure_event import ConfigureEvent
from ..task.protocols import IProvideTimer
from ..task.protocols import CreateTimerResult
from ..task.timer import TimerThreadService
from ..task.async_worker_pool import AsyncWorkerPool
from .message_router import MessageRouter
from ..utils.image_compositor import ImageCompositor, ImageOverlay
from ..utils.image_utils import apply_image_enhancement, change_orientation, resize_image

class TimedLayerControl:
	"""What a timed layer (priority, blend) shows now, so a revoke can end it early, and the titles revoked while still queued. Only touched on the pool loop."""
	def __init__(self):
		self.title: str|None = None
		self.ended: asyncio.Event|None = None
		self.revoked: set[str] = set()

class Display(DispatcherTask):
	# how long the dispatcher waits for the pool loop to take a frame before it drops the frame
	RESULT_TIMEOUT_SECONDS = 30.0
	# pause after an unexpected error in a loop, so a persistent error cannot spin
	ERROR_BACKOFF_SECONDS = 1.0
	# how long a timed image (priority, blend) waits for the panel to show it before its time starts anyway: the commit delay and a refresh
	# (which the driver stage bounds) fit well inside it, so only a panel that never answers gets here
	DRAWN_WAIT_SECONDS = 180.0
	def __init__(self, name, router:MessageRouter):
		super().__init__(name)
		if router is None:
			raise ValueError("router is None")
		self.router = router
		self.cm: ConfigurationManager | None = None
		self.display: DisplayBase | None = None
		# when the panel was last refreshed and what it shows, kept across restarts so a restart does not refresh it again at once (see refresh_gate.py)
		self.refresh_state = RefreshState(None)
		self.timebase: TimeOfDay | None = None
		self.timer: IProvideTimer | None = None
		self.commit_timer: CreateTimerResult | None = None
		self.priority_timer: CreateTimerResult | None = None
		self.refresh_timer: CreateTimerResult | None = None
		self.compositor = ImageCompositor()
		self.task_pool: AsyncWorkerPool | None = None
		self.resolution = (800, 480)
		self.commitq: asyncio.Queue[BasicMessage] | None = None
		self.priorityq: asyncio.Queue[PriorityImage] | None = None
		self.blendq: asyncio.Queue[BlendImage] | None = None
		self.priority_control = TimedLayerControl()
		self.blend_control = TimedLayerControl()
		self.task_commit: tuple[Future, threading.Event] | None = None
		self.task_priority: tuple[Future, threading.Event] | None = None
		self.task_blend: tuple[Future, threading.Event] | None = None
		self.task_render: tuple[Future, threading.Event] | None = None
		# overlays: the zones (set at configure) and, per zone, who put up what is there (only touched on the pool loop)
		# the newest compositor version the panel has been given (drawn, or already showing), and who waits for which one (only touched on the pool loop)
		self._drawn_version = 0
		self._drawn_waiters: list[tuple[int, asyncio.Event]] = []
		self.zones: dict[str, Zone] = {}
		self.overlays: dict[str, tuple[str, ImageOverlay]] = {}
		self.logger = logging.getLogger(__name__)

	def _stop_task(self, task:tuple[Future, threading.Event]):
		fut, donev = task
		if not fut.done():
			self.logger.info("task still running, cancel...")
			fut.cancel()
			self.logger.info("Waiting for task to complete...")
			donev.wait(timeout=2.0)
		else:
			self.logger.info("task completed.")
	def _telemetry(self, kind: str, values: Mapping[str, Any]) -> None:
		"""Tell the telemetry link (the `telemetry` route) what the panel did; a failure to tell must never stop the panel."""
		try:
			now = (self.timebase or SystemTimeOfDay()).current_time()
			self.router.send("telemetry", Telemetry(now, "display", { "kind": kind, **values }))
		except Exception as e:
			self.logger.warning(f"Display telemetry could not be sent ({type(e).__name__}).")
	@handles(ConfigurationChanged)
	def _configuration_changed(self, msg: ConfigurationChanged):
		# the display settings are read when the display starts; reconfiguring it live is not supported yet
		if msg.area in ("settings", "schemas", "restore"):
			self.logger.info(f"'{self.name}' configuration changed ({msg.area}); display settings are applied at the next start.")
	def quitMsg(self, msg: QuitMessage):
		# every step runs even if an earlier one (or the configuration) failed: the pool and the display must always be shut down
		try:
			try:
				for attr in ("task_commit", "task_priority", "task_blend", "task_render"):
					task = getattr(self, attr)
					if task is not None:
						setattr(self, attr, None)
						try:
							self._stop_task(task)
						except Exception as e:
							self.logger.error(f"shutdown.stop_task {attr}: {e}", exc_info=True)
			finally:
				try:
					if self.task_pool is not None:
						pool, self.task_pool = self.task_pool, None
						self.commitq = None
						self.priorityq = None
						self.blendq = None
						pool.shutdown()
				except Exception as e:
					self.logger.error(f"shutdown.pool: {e}", exc_info=True)
				finally:
					try:
						if self.display is not None:
							self.display.shutdown()
					except Exception as e:
						self.logger.error(f"shutdown.display: {e}", exc_info=True)
		except Exception as e:
			self.logger.error(f"shutdown.unhandled {str(e)}", exc_info=True)
		finally:
			self.display = None
			super().quitMsg(msg)
	@handles(ConfigureEvent)
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
			# the display device is the installed one whose declared id the setting names (`displays/*/display-info.json`): the descriptor's id builds nothing, the setting's text only selects
			chosen = next((d for d in self.cm.enum_displays() if d["info"].get("id") == display_type), None) if isinstance(display_type, str) else None
			if chosen is None:
				raise ValueError(f"Unrecognized display type: '{display_type}'")
			# a device's own driver is imported when it is initialized (below), on the device only; the module of the class needs none (tkinter is needed by the Tk window's module: not on every system)
			self.display = self.cm.create_display(chosen)
			if self.display is None:
				raise ValueError(f"The '{display_type}' display is disabled or could not be loaded (the log says why: the 'tk' display needs tkinter, which not every system has).")
			ts = msg.content.isp.get_service(IProvideTimer)
			self.timer = ts if ts is not None else TimerThreadService(self.timebase)
			self.resolution = self.display.initialize(self.cm)
			self.refresh_state = RefreshState(self.cm)
			self.refresh_state.load()
			# a restart inside the rest after the last refresh waits out what is left of it
			self.display.gate.restore(self.refresh_state.last_end)
			self.logger.info(f"Loading display {display_type} {self.resolution[0]}x{self.resolution[1]}")
			orientation = cast(str, display_settings.get("orientation", "landscape"))
			self.zones = { zone.name: zone for zone in zones_for(self.resolution, orientation) }
			self._start_tasks(self.display, self.compositor, self.timebase, display_settings)
			msg.notify()
			self.router.send("display-settings", DisplaySettings(msg.timestamp, display_type, self.resolution[0], self.resolution[1], [zone.definition() for zone in self.zones.values()]))
		except Exception as e:
			self.logger.error(f"configure.unhandled: {str(e)}", exc_info=True)
			msg.notify(True, e)
	def _start_tasks(self, display: DisplayBase, compositor: ImageCompositor, timebase: TimeOfDay, display_settings: Mapping[str,Any]) -> None:
		self.task_pool = AsyncWorkerPool()
		self.task_pool.start()
		task_future = self.task_pool.submit(self._task_create_queues(), None)
		self.commitq, renderq, self.priorityq, self.blendq = task_future.result(timeout=self.RESULT_TIMEOUT_SECONDS)

		donev = threading.Event()
		def commit_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "commit_task", fut, donev))
		self.task_commit = (self.task_pool.submit(self._task_commit_timer(cast(asyncio.Queue[BasicMessage], self.commitq), renderq, timebase, donev), callback=commit_callback), donev)
		donev2 = threading.Event()
		def priority_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "priority_task", fut, donev2))
		self.task_priority = (self.task_pool.submit(self._task_timed_layer(cast(asyncio.Queue[DisplayImage], self.priorityq), cast(asyncio.Queue[BasicMessage], self.commitq), self.resolution, display_settings, donev2, compositor.set_layer_priority, "priority", self.priority_control), callback=priority_callback), donev2)
		donev4 = threading.Event()
		def blend_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "blend_task", fut, donev4))
		self.task_blend = (self.task_pool.submit(self._task_timed_layer(cast(asyncio.Queue[DisplayImage], self.blendq), cast(asyncio.Queue[BasicMessage], self.commitq), self.resolution, display_settings, donev4, compositor.set_layer_blend, "blend", self.blend_control), callback=blend_callback), donev4)
		donev3 = threading.Event()
		def render_callback(fut):
			if not self.is_stopped():
				self.accept(AsyncTaskCompleted(timebase.current_time(), "render_task", fut, donev3))
		self.task_render = (self.task_pool.submit(self._task_render_and_display(renderq, compositor, display, display_settings, donev3), callback=render_callback), donev3)
		pass
	async def _task_create_queues(self) -> tuple[asyncio.Queue[BasicMessage], asyncio.Queue[BasicMessage], asyncio.Queue[PriorityImage], asyncio.Queue[BlendImage]]:
		commitq: asyncio.Queue[BasicMessage] = asyncio.Queue()
		renderq: asyncio.Queue[BasicMessage] = asyncio.Queue()
		priorityq: asyncio.Queue[PriorityImage] = asyncio.Queue()
		blendq: asyncio.Queue[BlendImage] = asyncio.Queue()
		return (commitq, renderq, priorityq, blendq)
	async def _task_background_layer(self, commitq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, msg: DisplayImage):
		compositor.set_layer_background(msg)
		# a background page ends the playlist page above it: the next track, an error page or "Playback stopped" is never hidden behind it
		compositor.set_layer_forground(None)
		await commitq.put(BasicMessage(msg.timestamp))
	async def _task_foreground_layer(self, commitq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, msg: DisplayImage):
		# a blend or override page: above the background, which stays (a blend washes over it); the overlays are kept but not drawn
		compositor.set_layer_forground(msg)
		await commitq.put(BasicMessage(msg.timestamp))
	async def _task_overlay_layer(self, commitq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, msg: OverlayImage):
		zone = self.zones.get(msg.zone)
		if zone is None:
			self.logger.warning(f"Overlay '{msg.title}' asks for zone '{msg.zone}', which this display does not have; dropped.")
			return
		image = msg.img if msg.img.size == zone.size else msg.img.resize(zone.size)
		if zone.portrait:
			image = change_orientation(image, "portrait")
		# a sender owns one zone: one that moved to another zone leaves nothing behind in the old one
		for name in [name for name, (key, _) in self.overlays.items() if key == msg.key and name != zone.name]:
			del self.overlays[name]
		self.overlays[zone.name] = (msg.key, ImageOverlay(image, (zone.panel_box[0], zone.panel_box[1]), origin=msg.origin))
		self._set_overlays(compositor)
		await commitq.put(BasicMessage(msg.timestamp))
	async def _task_overlay_revoke(self, commitq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, msg: OverlayRevoke):
		owned = [name for name, (key, _) in self.overlays.items() if key == msg.key]
		if not owned:
			return
		for name in owned:
			del self.overlays[name]
		self._set_overlays(compositor)
		await commitq.put(BasicMessage(msg.timestamp))
	def _set_overlays(self, compositor: ImageCompositor) -> None:
		compositor.set_layer_overlays([self.overlays[name][1] for name in ZONE_NAMES if name in self.overlays])
	async def _task_priority_layer(self, priorityq: asyncio.Queue[PriorityImage], msg: PriorityImage):
		await priorityq.put(msg)
	async def _task_blend_layer(self, blendq: asyncio.Queue[BlendImage], msg: BlendImage):
		await blendq.put(msg)
	async def _task_priority_revoke(self, priorityq: asyncio.Queue[PriorityImage], title: str):
		control = self.priority_control
		if control.title == title and control.ended is not None:
			control.ended.set()
		elif priorityq.qsize() > 0:
			control.revoked.add(title)
	def _drawn_event(self, version: int) -> asyncio.Event:
		"""Set once the panel has been given the compositor's `version` or a newer one."""
		event = asyncio.Event()
		if self._drawn_version >= version:
			event.set()
		else:
			self._drawn_waiters.append((version, event))
		return event
	async def _until_drawn(self, version: int, ended: asyncio.Event) -> None:
		"""Waits until the panel has been given `version`, the image is revoked (`ended`), or `DRAWN_WAIT_SECONDS` have passed."""
		waits = { asyncio.ensure_future(self._drawn_event(version).wait()), asyncio.ensure_future(ended.wait()) }
		# the panel's rest comes before the draw, so it is part of what is waited for
		rest = self.display.gate.rest_seconds if self.display is not None else 0.0
		try:
			await asyncio.wait(waits, timeout=self.DRAWN_WAIT_SECONDS + rest, return_when=asyncio.FIRST_COMPLETED)
		finally:
			for wait in waits:
				wait.cancel()
	def _note_drawn(self, version: int) -> None:
		self._drawn_version = max(self._drawn_version, version)
		for waiter in [w for w in self._drawn_waiters if w[0] <= self._drawn_version]:
			self._drawn_waiters.remove(waiter)
			waiter[1].set()
	async def _task_commit_timer(self, commitq: asyncio.Queue[BasicMessage], renderq: asyncio.Queue[BasicMessage], timebase: TimeOfDay, donev: threading.Event):
		try:
			while True:
				self.logger.debug("Commit timer arming")
				_ = await commitq.get()
				self.logger.debug("Commit timer triggered")
				commitq.task_done()
				while True:
					try:
						_ = await asyncio.wait_for(commitq.get(), timeout=2.0)
						commitq.task_done()
						self.logger.debug("Commit timer extended")
					except asyncio.TimeoutError:
						self.logger.debug("Commit timer ends")
						await renderq.put(BasicMessage(timebase.current_time()))
						# exit inner loop, wait for fresh message to reset commit timer
						break
					except Exception as e:
						self.report_failure("The panel could not be updated", e)
						await asyncio.sleep(self.ERROR_BACKOFF_SECONDS)
		except asyncio.CancelledError:
			self.logger.info("commit timer task cancelled")
			raise
		finally:
			donev.set()
	async def _task_render_and_display(self, taskq: asyncio.Queue[BasicMessage], compositor: ImageCompositor, display: DisplayBase, display_settings: Mapping[str, Any]|None, donev: threading.Event):
		try:
			rotate: bool = display_settings.get("rotate180", False) if display_settings is not None else False
			displayImageCount: int = 0
			# what the panel shows now: an image that comes out identical is not drawn again (an e-ink refresh takes seconds and wears the panel); after a restart, what it showed before
			shown: bytes|None = bytes.fromhex(self.refresh_state.digest) if self.refresh_state.digest else None
			while True:
				# the version this pass takes from the compositor, for whoever waits to see it drawn (also when drawing it fails: nobody waits for ever)
				taking: int|None = None
				# whether this pass sent anything to the panel (a refresh that fails may have driven it all the same)
				last_end = display.gate.last_end_wall
				try:
					_ = await taskq.get()
					taskq.task_done()
					# the panel's rest after its last refresh (the blanking period), waited out BEFORE the next image is taken: whatever arrives meanwhile is part of it, and
					# nothing is sent to the driver during the rest (a restart or a failed refresh starts one too: the gate is in the driver stage)
					wait = display.ready_in()
					if wait > 0:
						self.logger.info(f"Blanking period: the panel rests for {wait:.0f} more seconds before the next page is drawn")
						self._telemetry("deferred", { "seconds": round(wait), "message": f"The panel is resting after its last refresh: the next page is drawn in {wait:.0f} seconds." })
						await asyncio.sleep(wait)
					# a page with no background under it shows the theme's color, read now so a theme change applies
					if self.cm is not None:
						compositor.fill = current_palette(self.cm.settings_manager()).bg_page.rgb
					package = compositor.commit()
					if package is None:
						self.logger.debug("Compositor no changes detected")
						# nothing newer than what the last pass handled: whoever waits for the current version has it
						self._note_drawn(compositor.current_version)
						continue
					taking = package.version
					shown_layers = compositor.layers()
					the_image, the_title = package.render()
					if rotate: the_image = the_image.rotate(180)
					the_image = apply_image_enhancement(the_image, display_settings)
					digest = hashlib.sha256(the_image.tobytes() + repr(the_image.size).encode()).digest()
					if digest == shown:
						self.logger.info(f"Compositor v:{package.version} '{the_title}' looks the same as what is shown, not drawing it again")
						self._telemetry("skipped", { "title": the_title, "version": package.version, "message": f"'{the_title}' looks the same as what is shown: not drawn again." })
						self._note_drawn(package.version)
						continue

					displayImageCount += 1
					self.logger.info(f"Compositor v:{package.version} '{the_title}' ({displayImageCount})")
					# render() is synchronous and slow (an e-ink refresh takes seconds): keep it off the loop; awaiting it keeps it one at a time
					await asyncio.to_thread(display.render, the_image, displayImageCount, the_title)
					shown = digest
					# the end of the refresh and what the panel shows, for a restart
					await asyncio.to_thread(self.refresh_state.save, display.gate.last_end_wall, digest.hex())
					# what the panel shows now, for the telemetry link: the hub keeps the image by its digest, the event carries the digest
					self._telemetry("shown", { "title": the_title, "version": package.version, "count": displayImageCount, "digest": digest.hex(),
						"width": the_image.width, "height": the_image.height, "layers": shown_layers, "image": the_image })
					# on the panel: a timed image's time starts now, not while the panel was still drawing it
					self._note_drawn(package.version)
					self.logger.debug(f"Blanking period starts: {display.gate.rest_seconds:g} seconds")
				except Exception as e:
					if taking is not None:
						self._note_drawn(taking)
					if display.gate.last_end_wall != last_end:
						# the driver was driven and failed: the panel's content is not known, and it rests like after any refresh
						shown = None
						await asyncio.to_thread(self.refresh_state.save, display.gate.last_end_wall, None)
					self.report_failure("The page could not be drawn on the panel", e)
					await asyncio.sleep(self.ERROR_BACKOFF_SECONDS)
		except asyncio.CancelledError:
			self.logger.info("render and display task cancelled")
			raise
		finally:
			donev.set()
	async def _task_timed_layer(self, taskq: asyncio.Queue[DisplayImage], commitq: asyncio.Queue[BasicMessage], resolution: tuple[int, int], display_settings: Mapping[str, Any]|None, donev: threading.Event,
			set_layer: Callable[[DisplayImage|None], Any], what: str, control: TimedLayerControl|None = None):
		"""Shows each queued image (priority or blend) on its layer for its `duration` (or until it is revoked), one after another, then clears the layer."""
		control = control or TimedLayerControl()
		try:
			ori:str = display_settings.get("orientation", "landscape") if display_settings is not None else "landscape"
			while True:
				try:
					msg = await taskq.get()
					if msg.title in control.revoked:
						control.revoked.discard(msg.title)
						taskq.task_done()
						continue
					# Resize and adjust orientation
					image = change_orientation(msg.img, ori)
					image = resize_image(image, resolution)
					di = msg if image == msg.img else ComputedImage(msg.timestamp, msg.title, image, msg, origin=msg.origin)
					set_layer(di)
					taskq.task_done()
					await commitq.put(BasicMessage(msg.timestamp))
					control.title, control.ended = msg.title, asyncio.Event()
					try:
						# its time starts when it is on the panel (an e-ink refresh takes tens of seconds), unless it is revoked first
						await self._until_drawn(self.compositor.current_version, control.ended)
						if not control.ended.is_set():
							await asyncio.wait_for(control.ended.wait(), cast(PriorityImage|BlendImage, msg).duration.total_seconds())
					except asyncio.TimeoutError:
						pass
					finally:
						control.title, control.ended = None, None
					set_layer(None)
					await commitq.put(BasicMessage(msg.timestamp))
				except Exception as e:
					self.report_failure(f"A {what} image could not be shown", e)
					await asyncio.sleep(self.ERROR_BACKOFF_SECONDS)
		except asyncio.CancelledError:
			self.logger.info(f"{what} image task cancelled")
			raise
		finally:
			donev.set()
	def _wait_for(self, fut: Future, what: str) -> bool:
		"""Waits (bounded) for the pool loop to take the frame; on a timeout the frame is dropped so the dispatcher (and Quit) stays responsive."""
		try:
			fut.result(timeout=self.RESULT_TIMEOUT_SECONDS)
			return True
		except FutureTimeoutError:
			fut.cancel()
			self.report_failure(f"The panel timed out after {self.RESULT_TIMEOUT_SECONDS:g}s taking {what}; the frame was dropped")
			return False
	@handles(PriorityImage)
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
			self._wait_for(fut, f"priority '{msg.title}'")
		except Exception as e:
			self.report_failure("A priority image could not be queued", e)
	@handles(PriorityRevoke)
	def _priority_revoke(self, msg: PriorityRevoke):
		if self.task_pool is None or self.priorityq is None:
			return
		fut = self.task_pool.submit(self._task_priority_revoke(self.priorityq, msg.title), None)
		self._wait_for(fut, f"priority revoke '{msg.title}'")
	@handles(BlendImage)
	def _blend_image(self, msg: BlendImage):
		"""A timer task's image that washes over the background for a while (queued like priority images)."""
		if self.task_pool is None or self.blendq is None:
			self.logger.error(f"Blend '{msg.title}': the display is not running")
			return
		self.logger.info(f"Blend '{msg.title}' ({msg.duration})")
		fut = self.task_pool.submit(self._task_blend_layer(self.blendq, msg), None)
		self._wait_for(fut, f"blend '{msg.title}'")
	@handles(OverlayImage)
	def _overlay_image(self, msg: OverlayImage):
		"""An overlay for a zone: it stays until its sender (`key`) replaces or revokes it."""
		if self.task_pool is None or self.commitq is None:
			self.logger.error(f"Overlay '{msg.title}': the display is not running")
			return
		self.logger.info(f"Overlay '{msg.title}' in '{msg.zone}'")
		fut = self.task_pool.submit(self._task_overlay_layer(self.commitq, self.compositor, msg), None)
		self._wait_for(fut, f"overlay '{msg.title}'")
	@handles(OverlayRevoke)
	def _overlay_revoke(self, msg: OverlayRevoke):
		if self.task_pool is None or self.commitq is None:
			return
		fut = self.task_pool.submit(self._task_overlay_revoke(self.commitq, self.compositor, msg), None)
		self._wait_for(fut, f"overlay revoke '{msg.key}'")
	@handles(DisplayImage)
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
			# at the start of the slot; `shown` follows when the panel has been redrawn
			self._telemetry("showing", { "title": msg.title, "layer": msg.layer, "message": f"On deck: '{msg.title}'." })

			if display_settings is not None:
			# Resize and adjust orientation
				image = change_orientation(msg.img, display_settings.get("orientation", "landscape"))
				image = resize_image(image, self.resolution)
				di = msg if image == msg.img else ComputedImage(msg.timestamp, msg.title, image, msg, layer=msg.layer, origin=msg.origin)
			else:
				di = msg
			task = self._task_background_layer if di.layer == "background" else self._task_foreground_layer
			fut  = self.task_pool.submit(task(self.commitq, self.compositor, di), None)
			self._wait_for(fut, f"display '{msg.title}' ({di.layer})")
		except Exception as e:
			self.report_failure("A page could not be shown", e)
	@handles(AsyncTaskCompleted)
	def _async_task_completed(self, msg: AsyncTaskCompleted):
		if not msg.fut.done():
			self.logger.info(f"{msg.token} task still running, cancel...")
			msg.fut.cancel()
			self.logger.info(f"Waiting for {msg.token} task to complete...")
			msg.donev.wait(timeout=2.0)
		else:
			self.logger.info(f"{msg.token} task completed.")
			rmsg = None
			if msg.fut.cancelled():
				self.logger.info(f"{msg.token} task was cancelled.")
			else:
				try:
					rmsg = msg.fut.result()
				except Exception as e:
					self.report_failure(f"The display's {msg.token} task failed", e)
			self.logger.info(f"{msg.token} task result: {rmsg}")
			if rmsg is not None:
				# handle message returned by the task
				self.accept(rmsg)
		if msg.token == "commit_task":
			self.task_commit = None
		elif msg.token == "priority_task":
			self.task_priority = None
		elif msg.token == "render_task":
			self.task_render = None
		pass
