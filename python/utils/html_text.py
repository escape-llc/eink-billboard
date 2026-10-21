"""
Reading HTML that a feed or an answer carries: its text and its pictures, with the standard library's parser, never by searching the markup.
"""
from html.parser import HTMLParser

# a block tag ends a line of text, so it is a space; an inline one (<b>, <em>, <a>) leaves the words as they were
BLOCK_TAGS = frozenset({ "p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "blockquote", "figure", "figcaption" })
# what a reader never sees as text
_HIDDEN = frozenset({ "script", "style", "template" })

class _Reader(HTMLParser):
	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.text: list[str] = []
		self.images: list[dict[str, str]] = []
		self._hidden = 0
	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag in BLOCK_TAGS:
			self.text.append(" ")
		elif tag in _HIDDEN:
			self._hidden += 1
		if tag == "img":
			self.images.append({ name: value or "" for name, value in attrs })
	def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag in _HIDDEN:
			return
		self.handle_starttag(tag, attrs)
	def handle_endtag(self, tag: str) -> None:
		if tag in BLOCK_TAGS:
			self.text.append(" ")
		elif tag in _HIDDEN and self._hidden > 0:
			self._hidden -= 1
	def handle_data(self, data: str) -> None:
		if not self._hidden:
			self.text.append(data)

def _read(markup: str) -> _Reader:
	reader = _Reader()
	reader.feed(markup)
	reader.close()
	return reader

def html_text(markup: str) -> str:
	"""The text of `markup` on one line: tags dropped (a block tag is a space), character references read, runs of white space one space."""
	return " ".join("".join(_read(markup).text).split())

def html_images(markup: str) -> list[dict[str, str]]:
	"""The attributes of each `<img>` in `markup`, in order (values with their character references read)."""
	return _read(markup).images
