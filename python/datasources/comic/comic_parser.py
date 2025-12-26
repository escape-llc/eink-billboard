import feedparser
import re

COMICS = {
	"XKCD": {
		"feed": "https://xkcd.com/atom.xml",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title,
		"caption": lambda element: re.search(r'<img[^>]+alt=["\"]([^"\"]+)["\"]', element).group(1),
	},
	"Cyanide & Happiness": {
		"feed": "https://explosm-1311.appspot.com/",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title.split(" - ")[1].strip(),
		"caption": lambda element: "",
	},
	"Saturday Morning Breakfast Cereal": {
		"feed": "http://www.smbc-comics.com/comic/rss",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title.split("-")[1].strip(),
		"caption": lambda element: re.search(r'Hovertext:<br />(.*?)</p>', element).group(1),
	},
	"The Perry Bible Fellowship": {
		"feed": "https://pbfcomics.com/feed/",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title,
		"caption": lambda element: re.search(r'<img[^>]+alt=["\"]([^"\"]+)["\"]', element).group(1),
	},
	"Questionable Content": {
		"feed": "http://www.questionablecontent.net/QCRSS.xml",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title,
		"caption": lambda element: "",
	},
	"Poorly Drawn Lines": {
		"feed": "https://poorlydrawnlines.com/feed/",
		"element": lambda entry: entry.get('content', [{}])[0].get('value', ''),
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title,
		"caption": lambda element: "",
	},
	"Dinosaur Comics": {
		"feed": "https://www.qwantz.com/rssfeed.php",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: entry.title,
		"caption": lambda element: re.search(r'title="(.*?)" />', element.replace('\n', '')).group(1),
	},
	"webcomic name": {
		"feed": "https://webcomicname.com/rss",
		"element": lambda entry: entry.description,
		"url": lambda element: re.search(r'<img[^>]+src=["\"]([^"\"]+)["\"]', element).group(1),
		"title": lambda entry: "",
		"caption": lambda element: "",
	},
}

def get_items(comic_name):
	comic = COMICS[comic_name]
	feed = feedparser.parse(comic["feed"])
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
