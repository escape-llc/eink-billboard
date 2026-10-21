import feedparser
import logging
import re

from ..content_cache import download_for
from ..data_source import DataSourceExecutionContext
from ...utils.text_utils import unescape_text

def _first(pattern: str, text: str) -> str:
	"""The first group of the first match; a page without the match is a malformed entry (the caller skips it)."""
	match = re.search(pattern, text)
	if match is None:
		raise ValueError(f"no match for {pattern!r}")
	return match.group(1)

COMICS = {
	"XKCD": {
		"feed": "https://xkcd.com/atom.xml",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title,
		"caption": lambda element: _first(r'<img[^>]+alt=["\"]([^"\"]+)["\"]', element),
	},
	"Cyanide & Happiness": {
		"feed": "https://explosm-1311.appspot.com/",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title.split(" - ")[1].strip(),
		"caption": lambda element: "",
	},
	"Saturday Morning Breakfast Cereal": {
		"feed": "https://www.smbc-comics.com/comic/rss",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title.split("-")[1].strip(),
		"caption": lambda element: _first(r'Hovertext:<br />(.*?)</p>', element),
	},
	"The Perry Bible Fellowship": {
		"feed": "https://pbfcomics.com/feed/",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title,
		"caption": lambda element: _first(r'<img[^>]+alt=["\"]([^"\"]+)["\"]', element),
	},
	"Questionable Content": {
		"feed": "https://www.questionablecontent.net/QCRSS.xml",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title,
		"caption": lambda element: "",
	},
	"Poorly Drawn Lines": {
		"feed": "https://poorlydrawnlines.com/feed/",
		"element": lambda entry: entry.get('content', [{}])[0].get('value', ''),
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title,
		"caption": lambda element: "",
	},
	"Dinosaur Comics": {
		"feed": "https://www.qwantz.com/rssfeed.php",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: entry.title,
		"caption": lambda element: _first(r'title="(.*?)" />', element.replace('\n', '')),
	},
	"webcomic name": {
		"feed": "https://webcomicname.com/rss",
		"element": lambda entry: entry.description,
		"url": lambda element: _first(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element),
		"title": lambda entry: "",
		"caption": lambda element: "",
	},
}

def parse_the_feed(comic_name: str, comic: dict, feed: feedparser.FeedParserDict):
	items = []
	for entry in feed.entries:
		try:
			element = comic["element"](entry)
			data = 	{
				"name": comic_name,
				"index": 0,
				"count": 0,
				# the caption and the address are cut out of the entry's HTML, so they still hold its character entities (&quot; &amp; &#039;);
				# a title is the feed's text, which may have been escaped once more (qwantz.com does)
				"image_url": unescape_text(comic["url"](element)),
				"title": unescape_text(comic["title"](entry)),
				"caption": unescape_text(comic["caption"](element)),
			}
			items.append(data)
		except Exception:
			# malformed entry, skip it
			continue
	index: int = 0
	for item in items:
		item["index"] = index
		item["count"] = len(items)
		index += 1
	return items
	pass

logger = logging.getLogger(__name__)

# a comic's feed changes at most daily and the site's headers can shorten this; a feed is a few hundred kilobytes at most
DEFAULT_FEED_HOURS = 0.5
MAX_FEED_BYTES = 2 * 1024 * 1024

# some hosts refuse the HTTP library's own User-Agent (webcomicname.com, on Tumblr, answers 403 to `python-httpx` and 200 to a browser or any other name)
HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; eink-billboard)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5" }

async def get_items_async(comic_name, dsec: DataSourceExecutionContext):
	comic = COMICS[comic_name]
	# the feed is kept briefly (its headers and validators decide); a failure raises as it always did
	buffer = await download_for(dsec, str(comic["feed"]), default_hours=DEFAULT_FEED_HOURS, headers=HEADERS, max_bytes=MAX_FEED_BYTES, scope=f"feed:{comic_name}", setting="feedCacheHours")
	feed = feedparser.parse(buffer.getvalue())
	if not feed.entries:
		# a site that answers 200 with an HTML page (cookie wall, bot check, moved feed) parses as an empty "bozo" feed
		reason = "the response is not a feed" if feed.get("bozo") else "the feed has no entries"
		logger.error(f"Comic '{comic_name}': {reason} ({comic['feed']}).")
		return []
	return parse_the_feed(comic_name, comic, feed)
