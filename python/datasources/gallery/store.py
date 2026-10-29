"""
The Gallery's pictures on disk (#238): the Gallery's own folder, through its `DatasourceConfigurationManager`, like every other file of the storage.

A picture is a binary file named by what is in it (`gallery-<sha256>.bin`): it never changes under its name, so there is no half-written pair to guard against and the same picture
offered twice is one. What describes the pictures is **one** JSON document, `gallery-index.json` (the title, where it came from, its size, whether it is pinned), newest first.

Every change is a read-modify-write of that document under its `ConfigurationObject`'s lock (`with cob:`): the playlist layer, the timer layer and the web app share one object for the
file, so one thread at a time changes the index and the files it names, and nothing needs a lock of its own. The bytes are written *before* the index names them, so a picture the index
lists is always there; a crash between the two leaves a file nobody lists, which `sweep` removes.

The pool is bounded (`max_pictures`, `max_bytes`): the oldest picture that is not pinned goes first. A pinned picture is never removed by the bound.
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ...model.configuration_manager import DatasourceConfigurationManager

logger = logging.getLogger(__name__)

PREFIX = "gallery-"
INDEX = "gallery-index"
# the folders tidied in this process (the first use of each); changed only with the index's lock held
_SWEPT: set[str] = set()

@dataclass(frozen=True, slots=True)
class Kept:
	"""What a `keep` did: `kept` is False for a picture that is already there (`duplicate`), bigger than the whole pool (`too-big`) or lost to an edit of the file (`changed`); `evicted` is how many went to make room."""
	kept: bool
	reason: str = ""
	id: str = ""
	evicted: int = 0
	count: int = 0
	bytes: int = 0

DEFAULT_MAX_PICTURES = 200
DEFAULT_MAX_MB = 512.0

def bounds(settings: Mapping[str, Any]|None) -> tuple[int, int]:
	"""The Gallery's limits from its settings: the most pictures, and the most bytes (a setting that is not a positive number is the default)."""
	settings = settings or {}
	pictures = settings.get("maxPictures")
	megabytes = settings.get("maxMB")
	return (pictures if isinstance(pictures, int) and not isinstance(pictures, bool) and pictures >= 1 else DEFAULT_MAX_PICTURES,
		int((megabytes if isinstance(megabytes, (int, float)) and not isinstance(megabytes, bool) and megabytes > 0 else DEFAULT_MAX_MB) * 1024 * 1024))

def picture_id(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()[:32]

def _name(item_id: str) -> str:
	return PREFIX + item_id

def _total(items: list[dict]) -> int:
	return sum(i["size"] for i in items if isinstance(i.get("size"), int))

class GalleryStore:
	def __init__(self, dscm: DatasourceConfigurationManager):
		self._dscm = dscm

	def _index(self):
		return self._dscm.file(INDEX)

	@staticmethod
	def _items(doc: Any) -> list[dict]:
		found = doc.get("items") if isinstance(doc, dict) else None
		return [i for i in found if isinstance(i, dict) and isinstance(i.get("id"), str)] if isinstance(found, list) else []

	@staticmethod
	def _own_id(items: list[dict], item_id: str) -> str|None:
		"""The index's own id for `item_id`, or None when it lists none: a file is named from this value, never from what a request said."""
		return next((i["id"] for i in items if i["id"] == item_id), None)

	def items(self) -> list[dict]:
		"""The pictures, newest first (copies: nobody changes the index through them)."""
		_, doc = self._index().get()
		return [dict(i) for i in self._items(doc)]

	def read(self, item_id: str) -> bytes|None:
		"""A picture's bytes; None when it is not there (it was removed after the list was made). `item_id` is only ever matched against our own index: the file is named from the index's own id, never the caller's string."""
		cob = self._index()
		with cob:
			own = self._own_id(self._items(cob.get()[1]), item_id)
			return self._dscm.read_blob(_name(own)) if own is not None else None

	def keep(self, data: bytes, meta: Mapping[str, Any], now: datetime, max_pictures: int, max_bytes: int) -> Kept:
		"""Keep `data` (a picture already encoded) with its description `meta` (`title`, `origin`, `prompt`, `width`, `height`), then trim the pool to its bounds."""
		item_id = picture_id(data)
		cob = self._index()
		with cob:
			self._sweep_once()
			rev, doc = cob.get()
			items = self._items(doc)
			if any(i["id"] == item_id for i in items):
				return Kept(False, "duplicate", item_id, 0, len(items), _total(items))
			if len(data) > max_bytes:
				return Kept(False, "too-big", item_id, 0, len(items), _total(items))
			self._dscm.write_blob(_name(item_id), data)
			items.insert(0, { **{ k: v for k, v in meta.items() if v is not None }, "id": item_id, "size": len(data), "added": now.isoformat(), "pinned": False })
			evicted = self._trim(items, max_pictures, max_bytes, item_id)
			saved, _ = cob.save(rev, { "items": items })
			if not saved:
				# someone edited the file by hand while we worked: this picture is not listed, so it is not kept
				self._dscm.remove_blob(_name(item_id))
				return Kept(False, "changed", item_id, 0, len(items) - 1, 0)
			for gone in evicted:
				self._dscm.remove_blob(_name(gone))
			return Kept(True, "", item_id, len(evicted), len(items), _total(items))

	@staticmethod
	def _trim(items: list[dict], max_pictures: int, max_bytes: int, just_kept: str) -> list[str]:
		"""Remove (from the list) the oldest pictures that are not pinned, never the one just kept, until the pool is in its bounds; returns their ids."""
		gone: list[str] = []
		total = _total(items)
		for item in reversed(list(items)):
			if len(items) <= max_pictures and total <= max_bytes:
				break
			if item["id"] == just_kept or item.get("pinned") is True:
				continue
			items.remove(item)
			total -= item["size"] if isinstance(item.get("size"), int) else 0
			gone.append(item["id"])
		return gone

	def pin(self, item_id: str, pinned: bool) -> bool:
		"""Pin or unpin a picture; False when there is none."""
		cob = self._index()
		with cob:
			rev, doc = cob.get()
			items = self._items(doc)
			for item in items:
				if item["id"] == item_id:
					item["pinned"] = pinned
					return cob.save(rev, { "items": items })[0]
			return False

	def remove(self, item_id: str) -> bool:
		"""Remove a picture (pinned or not); False when there is none."""
		cob = self._index()
		with cob:
			rev, doc = cob.get()
			items = self._items(doc)
			own = self._own_id(items, item_id)
			if own is None:
				return False
			if not cob.save(rev, { "items": [i for i in items if i["id"] != own] })[0]:
				return False
			self._dscm.remove_blob(_name(own))
			return True

	def _sweep_once(self) -> None:
		"""The first time the store is used in this process: files no index lists (a crash between the bytes and the index) are removed. Called with the index's lock held."""
		if self._dscm.ROOT_PATH in _SWEPT:
			return
		_SWEPT.add(self._dscm.ROOT_PATH)
		try:
			listed = { _name(i["id"]) for i in self._items(self._index().get()[1]) }
			for name in self._dscm.list_blobs(PREFIX):
				if name not in listed:
					self._dscm.remove_blob(name)
		except Exception as e:
			logger.warning(f"The Gallery could not tidy its folder ({type(e).__name__}).")
