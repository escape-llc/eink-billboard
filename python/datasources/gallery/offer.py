"""
What a data source says to the Gallery (#238): "here is a picture I drew, keep it if you can".

The Gallery is a data source like any other, so the way to it is the one data sources already have: a message addressed to it (`source_id`) and handed to the
`DataSourceManager`, which delivers it to the source that has that id and drops it when there is none (a Gallery that is disabled is not loaded). A source that
makes a picture worth keeping (one that cost money to make) calls `offer_to_gallery` and goes on: it never waits for the Gallery and never fails because of it.
"""
import logging
from dataclasses import dataclass
from PIL import Image

from ..data_source import DataSourceExecutionContext, DataSourceManager

logger = logging.getLogger(__name__)

GALLERY_ID = "gallery"
# what every Gallery event says changed: the web app's cache asks for these routes again (api/resources.ts), so an open Gallery page follows
CHANGED = [f"/api/datasource/{GALLERY_ID}"]

@dataclass(frozen=True, slots=True)
class GalleryOffer:
	"""A picture for the Gallery. `source_id` names the *receiver*, as every message of the data source manager does; `origin` is the data source that drew it."""
	source_id: str
	# the producer's own context: the services the Gallery needs (its storage, the telemetry) are reached through it
	context: DataSourceExecutionContext
	origin: str
	image: Image.Image
	title: str
	prompt: str|None = None

def offer_to_gallery(dsec: DataSourceExecutionContext, origin: str, image: Image.Image, title: str, prompt: str|None = None) -> None:
	"""
	Offer `image`, as the source drew it (before it is fitted to the panel or enhanced: the Gallery does that when it shows it), under `title`.
	The picture is copied, so the producer may go on with its own. Nothing here can fail the producer: a missing Gallery is not an error, and a refusal is a log line.
	"""
	try:
		manager = dsec.provider.get_service(DataSourceManager)
		if manager is None:
			return
		manager.accept(GalleryOffer(GALLERY_ID, dsec, origin, image.copy(), title, prompt))
	except Exception as e:
		logger.warning(f"'{origin}' could not offer a picture to the Gallery ({type(e).__name__}).")
