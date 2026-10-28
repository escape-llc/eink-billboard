"""
The Gallery (#238): the pictures worth keeping (one a paid service drew), kept on the device and shown again, as a list for a Slide Show.

Other data sources hand it pictures with `offer_to_gallery` (a message to this source, delivered by the `DataSourceManager`: `accept`). `accept` returns at once: the picture is encoded
and kept on a worker of its own (`store.py` has the rules of the files), one offer at a time in the order they came, so a slide never waits for the disk. Every outcome is told to the
web app as telemetry (`gallery-kept`, `gallery-evicted`...), which the Gallery page uses to know when to ask again.

As a list it is a source like the Image Folder: `open_async` lists the pictures and the Slide Show keeps the list (`keepsList`). A picture is kept as it was drawn and fitted to the panel,
and enhanced, when it is shown, so the display settings of the day apply.
"""
import asyncio
import io
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Mapping

from PIL import Image

from ...model.configuration_manager import ConfigurationManager, DatasourceConfigurationManager
from ...model.time_of_day import TimeOfDay
from ...plugins.plugin_base import PermanentError
from ...task.message_router import MessageRouter
from ...task.messages import Telemetry
from ...utils.image_utils import blurred_margin, to_rgb
from ..data_source import DataSource, DataSourceExecutionContext, DataSourceMessage, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions, enhanced
from .offer import GalleryOffer
from .store import GalleryStore, Kept, bounds

logger = logging.getLogger(__name__)

MAX_TITLE = 200
MAX_PROMPT = 1000
# one worker for every Gallery in the process (the playlist and the timer layers each load one): the offers are kept in the order they came
_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gallery")

KEPT_WORDS = "The Gallery kept a picture from '{origin}' ({size}); it holds {count}."
EVICTED_WORDS = "The Gallery let {evicted} older picture(s) go to stay within its limits."

def _kb(size: int) -> str:
	return f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} bytes"

def encode(image: Image.Image) -> bytes:
	"""A picture as the Gallery keeps it: a JPEG at high quality (a drawn picture or a photograph; a PNG of it would be several times as large)."""
	out = io.BytesIO()
	to_rgb(image).save(out, "JPEG", quality=92)
	return out.getvalue()

class GalleryAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def accept(self, msg: DataSourceMessage) -> None:
		"""A picture offered by another data source: kept in the background. Anything else is not for us."""
		if isinstance(msg, GalleryOffer):
			_WORKER.submit(self._keep, msg)

	def flush(self) -> None:
		"""Wait until every offer made so far has been dealt with (the tests, and a shutdown that would lose none)."""
		_WORKER.submit(lambda: None).result(timeout=60)

	def _keep(self, offer: GalleryOffer) -> None:
		try:
			# the producer's services, and this data source's own folder (by its own id: the offer is addressed to it, and it is never a name from outside)
			context = offer.context
			dscm = context.provider.required(ConfigurationManager).datasource_manager(self.id)
			_, settings = dscm.open().get()
			settings = settings or {}
			maximum, max_bytes = bounds(settings)
			clock = context.provider.get_service(TimeOfDay)
			now = clock.current_time() if clock is not None else datetime.now().astimezone()
			data = encode(offer.image)
			meta = { "title": offer.title[:MAX_TITLE], "origin": offer.origin, "prompt": offer.prompt[:MAX_PROMPT] if offer.prompt else None,
				"width": offer.image.width, "height": offer.image.height }
			result = GalleryStore(dscm).keep(data, meta, now, maximum, max_bytes)
			self._tell(context, now, offer.origin, result)
		except Exception as e:
			logger.warning(f"The Gallery could not keep a picture from '{offer.origin}' ({type(e).__name__}).")

	def _tell(self, context: DataSourceExecutionContext, now: datetime, origin: str, result: Kept) -> None:
		"""What happened, for the web app (the data source and the sizes, never a prompt)."""
		router = context.provider.get_service(MessageRouter)
		if router is None or not result.kept:
			if result.reason not in ("", "duplicate"):
				logger.info(f"The Gallery did not keep a picture from '{origin}' ({result.reason}).")
			return
		try:
			router.send("telemetry", Telemetry(now, "data-source", { "kind": "gallery-kept", "datasource": origin, "bytes": result.bytes, "count": result.count,
				"message": KEPT_WORDS.format(origin=origin, size=_kb(result.bytes), count=result.count) }))
			if result.evicted:
				router.send("telemetry", Telemetry(now, "data-source", { "kind": "gallery-evicted", "datasource": self.id, "count": result.count,
					"message": EVICTED_WORDS.format(evicted=result.evicted) }))
		except Exception as e:
			logger.warning(f"A Gallery event could not be sent ({type(e).__name__}).")

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		items = await asyncio.to_thread(GalleryStore(dscm).items)
		if params.get("pinnedOnly") is True:
			items = [i for i in items if i.get("pinned") is True]
		if not items:
			raise PermanentError("The Gallery has no pictures yet." if params.get("pinnedOnly") is not True else "The Gallery has no pinned pictures.")
		if params.get("order") != "Newest first":
			random.shuffle(items)
		return items

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult|None:
		if not isinstance(state, dict) or not isinstance(state.get("id"), str):
			return None
		dscm = dsec.provider.required(DatasourceConfigurationManager)
		data = await asyncio.to_thread(GalleryStore(dscm).read, state["id"])
		if data is None:
			# removed after the list was made: nothing to show for it
			return None
		size = target_dimensions(dsec)
		def fit() -> Image.Image:
			with Image.open(io.BytesIO(data)) as opened:
				return blurred_margin(to_rgb(opened), size)
		picture = await asyncio.to_thread(fit)
		return MediaRenderResult(image=enhanced(dsec, picture), title=str(state.get("title") or "Gallery"), layer="background")
