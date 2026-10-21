"""
The comics a Comic task can choose, as data, and how a strip is read from an entry of the comic's feed.

A comic is a `Comic` record: its feed, where the entry's HTML is, how its title reads and where its caption comes from. The HTML is
read with the standard library's parser (the first picture and its attributes, the text after a marker), never by searching the markup.
"""
from dataclasses import dataclass
from html.parser import HTMLParser
import logging
from typing import Any, Literal, Mapping

import feedparser

from ..content_cache import download_for
from ..data_source import DataSourceExecutionContext
from ...utils.text_utils import unescape_text

logger = logging.getLogger(__name__)

# a comic's feed changes at most daily and the site's headers can shorten this; a feed is a few hundred kilobytes at most
DEFAULT_FEED_HOURS = 0.5
MAX_FEED_BYTES = 2 * 1024 * 1024
# some hosts refuse the HTTP library's own User-Agent (webcomicname.com, on Tumblr, answers 403 to `python-httpx` and 200 to any other name)
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5" }

@dataclass(frozen=True)
class Comic:
	"""
	One comic. `body`: where an entry keeps its HTML (`summary`, which is also an RSS description, or the first `content`).
	`title`: the entry's title as it is (`entry`), the part after `title_after` (`after`), or none. `caption`: the picture's `alt` or
	`title` attribute, the text that follows `caption_after` up to the end of its paragraph (`marker`), or none.
	"""
	feed: str
	body: Literal["summary", "content"] = "summary"
	title: Literal["entry", "after", "none"] = "entry"
	title_after: str = ""
	caption: Literal["alt", "title", "marker", "none"] = "none"
	caption_after: str = ""

COMICS: dict[str, Comic] = {
	"XKCD": Comic("https://xkcd.com/atom.xml", caption="alt"),
	"Cyanide & Happiness": Comic("https://explosm-1311.appspot.com/", title="after", title_after=" - "),
	"Saturday Morning Breakfast Cereal": Comic("https://www.smbc-comics.com/comic/rss", title="after", title_after=" - ", caption="marker", caption_after="Hovertext:"),
	"The Perry Bible Fellowship": Comic("https://pbfcomics.com/feed/", caption="alt"),
	"Questionable Content": Comic("https://www.questionablecontent.net/QCRSS.xml"),
	"Poorly Drawn Lines": Comic("https://poorlydrawnlines.com/feed/", body="content"),
	"Dinosaur Comics": Comic("https://www.qwantz.com/rssfeed.php", caption="title"),
	"webcomic name": Comic("https://webcomicname.com/rss", title="none"),
}

# the tags that end a paragraph of text, for a caption that follows a marker
_PARAGRAPH_ENDS = frozenset({ "p", "div", "li", "blockquote", "figure", "figcaption", "td" })

class _EntryReader(HTMLParser):
	"""Reads an entry's HTML once: the first `<img>`'s attributes, and the text after `marker` up to the end of its paragraph."""
	def __init__(self, marker: str):
		super().__init__(convert_charrefs=True)
		self.picture: dict[str, str] | None = None
		self.marker = marker
		self._text: list[str] = []
		self._after: list[str] | None = None
		self._done = False
	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag == "img" and self.picture is None:
			self.picture = { name: value or "" for name, value in attrs }
	def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		self.handle_starttag(tag, attrs)
	def handle_endtag(self, tag: str) -> None:
		if self._after is not None and tag in _PARAGRAPH_ENDS:
			self._done = True
		elif self._after is None and tag in _PARAGRAPH_ENDS:
			self._text.clear()
	def handle_data(self, data: str) -> None:
		if self._done or not self.marker:
			return
		if self._after is not None:
			self._after.append(data)
			return
		self._text.append(data)
		seen = "".join(self._text)
		at = seen.find(self.marker)
		if at >= 0:
			self._after = [seen[at + len(self.marker):]]
	@property
	def after_marker(self) -> str | None:
		return None if self._after is None else " ".join("".join(self._after).split())

def _body(comic: Comic, entry: Mapping[str, Any]) -> str:
	if comic.body == "content":
		content = entry.get("content") or []
		return str(content[0].get("value", "")) if content else ""
	return str(entry.get("summary") or entry.get("description") or "")

def _title(comic: Comic, entry: Mapping[str, Any]) -> str:
	text = str(entry.get("title") or "")
	if comic.title == "none":
		return ""
	if comic.title == "after":
		_, found, rest = text.partition(comic.title_after)
		return rest.strip() if found else text.strip()
	return text

def read_strip(name: str, comic: Comic, entry: Mapping[str, Any]) -> dict | None:
	"""A strip of an entry (`name`, `image_url`, `title`, `caption`), or None when the entry has no picture or lacks the caption it should have."""
	reader = _EntryReader(comic.caption_after if comic.caption == "marker" else "")
	reader.feed(_body(comic, entry))
	reader.close()
	picture = reader.picture or {}
	if not picture.get("src"):
		return None
	if comic.caption in ("alt", "title"):
		caption = picture.get(comic.caption)
	elif comic.caption == "marker":
		caption = reader.after_marker
	else:
		caption = ""
	if caption is None:
		return None
	# the parser decoded each value once; a feed that escaped its text twice (qwantz.com) still holds entities, which this reads
	return {
		"name": name,
		"image_url": unescape_text(picture["src"]),
		"title": unescape_text(_title(comic, entry)),
		"caption": unescape_text(caption),
	}

def read_feed(name: str, comic: Comic, feed: feedparser.FeedParserDict) -> list[dict]:
	"""The strips of a parsed feed in its order, each with its `index` and the `count`; an entry without a picture is left out."""
	strips = [strip for strip in (read_strip(name, comic, entry) for entry in feed.entries) if strip is not None]
	for index, strip in enumerate(strips):
		strip["index"] = index
		strip["count"] = len(strips)
	return strips

async def strips_async(name: str, dsec: DataSourceExecutionContext) -> list[dict]:
	"""The strips of the named comic's feed, which is kept briefly (its headers and validators decide); a download that fails raises."""
	comic = COMICS[name]
	buffer = await download_for(dsec, comic.feed, default_hours=DEFAULT_FEED_HOURS, headers=HEADERS, max_bytes=MAX_FEED_BYTES, scope=f"feed:{name}", setting="feedCacheHours")
	feed = feedparser.parse(buffer.getvalue())
	if not feed.entries:
		# a site that answers 200 with an HTML page (cookie wall, bot check, moved feed) parses as an empty "bozo" feed
		reason = "the response is not a feed" if feed.get("bozo") else "the feed has no entries"
		logger.error(f"Comic '{name}': {reason} ({comic.feed}).")
		return []
	return read_feed(name, comic, feed)
