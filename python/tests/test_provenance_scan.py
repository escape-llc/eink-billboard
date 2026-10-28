"""The provenance scan (scripts/provenance_scan.py, #694): what it counts, what it lists, and when it fails. Two small trees of our own; no clone."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts import provenance_scan as scan

SHARED = [
	"def render_the_whole_page(self, dimensions, params):",
	"	template_params['height'] = dimensions[1] + margin_of(page)",
	"	return self.session.render(template_params, transparent=False)",
	"	raise RuntimeError('The thing could not be drawn at all.')",
	"	logger.info(f'rendered {dimensions} in {elapsed:.1f} seconds')",
]

def _write(root: str, path: str, lines: list[str]) -> None:
	full = os.path.join(root, *path.split("/"))
	os.makedirs(os.path.dirname(full), exist_ok=True)
	with open(full, "w", encoding="utf-8") as f:
		f.write("\n".join(lines) + "\n")


class TestCounted(unittest.TestCase):
	def test_white_space_does_not_matter_and_trivial_lines_do_not_count(self):
		lines = scan.normalized("\n".join([
			"	x  =   compute_something_long(alpha, beta)",
			"import os.path.something_long_enough",
			"from somewhere.far.away import a_long_name",
			"# a comment that is long enough to count otherwise",
			"// another comment that is long enough to count",
			"short = 1",
			"					)))]]]}}}}}};;;;;;;;;;,,,,,,,,,",
		]))
		self.assertEqual(lines, { "x = compute_something_long(alpha, beta)" })


class TestCompare(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.ours, self.theirs = os.path.join(tmp.name, "ours"), os.path.join(tmp.name, "theirs")
		_write(self.theirs, "src/render.py", SHARED + ["def something_else_entirely_of_theirs(): pass"])
		# one of ours shares all five lines (indented differently), one shares four, one is vendored
		_write(self.ours, "python/page.py", ["    " + line.strip() for line in SHARED] + ["def our_own_function_that_they_do_not_have():"])
		_write(self.ours, "python/near.py", SHARED[:4])
		_write(self.ours, "python/display/waveshare_epd/epd.py", SHARED)

	def test_a_file_sharing_the_least_counted_lines_is_listed_with_its_nearest(self):
		found = scan.compare(scan.read_tree(self.ours), scan.read_tree(self.theirs))
		self.assertEqual([(m.path, len(m.shared), m.nearest) for m in found], [("python/page.py", 5, "src/render.py")])
		self.assertEqual([(m.path, len(m.shared)) for m in scan.compare(scan.read_tree(self.ours), scan.read_tree(self.theirs), 4)], [("python/page.py", 5), ("python/near.py", 4)])

	def test_vendored_code_is_not_compared(self):
		self.assertNotIn("python/display/waveshare_epd/epd.py", scan.read_tree(self.ours))

	def test_a_file_not_accepted_fails_the_scan_and_an_accepted_one_does_not(self):
		found = scan.compare(scan.read_tree(self.ours), scan.read_tree(self.theirs))
		with contextlib.redirect_stdout(io.StringIO()) as out:
			self.assertEqual(scan.report(found, verbose=True), 1)
		self.assertIn("python/page.py", out.getvalue())
		self.assertIn(SHARED[0], out.getvalue())
		with patch.dict(scan.ACCEPTED, { "python/page.py": "reviewed" }), contextlib.redirect_stdout(io.StringIO()) as out:
			self.assertEqual(scan.report(found, verbose=False), 0)
		self.assertIn("Accepted:", out.getvalue())
		self.assertIn("(reviewed)", out.getvalue())

	def test_the_accepted_files_are_ours(self):
		for path in scan.ACCEPTED:
			with self.subTest(path=path):
				self.assertTrue(os.path.isfile(os.path.join(scan.ROOT, *path.split("/"))), "an accepted file that is gone is a stale entry")
