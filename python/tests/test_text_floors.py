import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR_PX = 13
# the page's own measuring decides these: an overlay's size is chosen in Python to fit its zone (overlay_text.fit_line)
EXEMPT_FILES = { "overlay-text.html" }

def pages() -> list[str]:
	found = []
	for top in ("datasources", "static"):
		for folder, _, names in os.walk(os.path.join(ROOT, top)):
			if "waveshare_epd" in folder:
				continue
			found += [os.path.join(folder, name) for name in names if name.endswith(".html") and os.path.basename(folder) == "render" and name not in EXEMPT_FILES]
	return sorted(found)

def declarations(text: str):
	"""Each `font-size` of a page's CSS with its selector and the declarations of the same rule."""
	text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
	for rule in re.finditer(r"([^{}]*)\{([^{}]*)\}", text):
		selector, body = re.sub(r"<[^>]*>", "", rule.group(1)).strip(), rule.group(2)
		for size in re.finditer(r"(?<![-\w])font-size:\s*([^;]+?)\s*(?:;|$)", body):
			yield selector, size.group(1), body

class TestTextFloors(unittest.TestCase):
	"""With antialiasing off a one-pixel stroke is wispy: no page draws text under the floors (plugin.css: --min-text 15 px, --min-label 13 px, bold only)."""
	def test_there_are_pages_to_check(self):
		self.assertGreater(len(pages()), 8)

	def test_every_size_a_page_computes_is_floored(self):
		checked = 0
		for path in pages():
			with open(path, encoding="utf-8") as f:
				text = f.read()
			for selector, value, _ in declarations(text):
				# `html` only sets what a `rem` is; the sizes of the text on it are the elements'
				if re.fullmatch(r"html", selector):
					continue
				checked += 1
				with self.subTest(page=os.path.basename(path), selector=selector, value=value):
					literal = re.fullmatch(r"([\d.]+)px", value)
					if literal:
						self.assertGreaterEqual(float(literal.group(1)), FLOOR_PX)
					else:
						self.assertRegex(value, r"^max\(var\(--min-(text|label)\), ")
		self.assertGreater(checked, 40)

	def test_small_print_is_bold(self):
		for path in pages():
			with open(path, encoding="utf-8") as f:
				text = f.read()
			for selector, value, body in declarations(text):
				if value.startswith("max(var(--min-label)"):
					with self.subTest(page=os.path.basename(path), selector=selector):
						self.assertRegex(body, r"font-weight:\s*bold")

	def test_the_floors_are_in_the_shared_stylesheet(self):
		with open(os.path.join(ROOT, "static", "render", "plugin.css"), encoding="utf-8") as f:
			css = f.read()
		self.assertRegex(css, r"--min-text:\s*15px")
		self.assertRegex(css, r"--min-label:\s*13px")
