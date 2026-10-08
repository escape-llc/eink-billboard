import feedparser
import logging
import re

from ...task.async_http_worker_pool import client_var

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
				"image_url": comic["url"](element),
				"title": comic["title"](entry),
				"caption": comic["caption"](element),
			}
			items.append(data)
		except Exception as e:
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

async def get_items_async(comic_name):
	comic = COMICS[comic_name]
	client = client_var.get()
	resp = await client.get(comic["feed"], follow_redirects=True)
	resp.raise_for_status()
	feed = feedparser.parse(resp.text)
	if not feed.entries:
		# a site that answers 200 with an HTML page (cookie wall, bot check, moved feed) parses as an empty "bozo" feed
		reason = "the response is not a feed" if feed.get("bozo") else "the feed has no entries"
		logger.error(f"Comic '{comic_name}': {reason} ({comic['feed']}).")
		return []
	return parse_the_feed(comic_name, comic, feed)
