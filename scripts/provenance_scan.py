"""
The lines our files share with another project's (#694): a check that no code, template or text came over from a project whose licence ours
cannot take (InkyPi is GPL-3.0; this repository is Apache-2.0).

    uv run python -m scripts.provenance_scan                                  InkyPi at the commit #694 was checked against
    uv run python -m scripts.provenance_scan --repo <git url> --commit <sha>  another project
    uv run python -m scripts.provenance_scan --tree <folder>                  a checkout that is already here
    uv run python -m scripts.provenance_scan -v                               and the shared lines themselves

The other project is cloned into a temporary folder and read as text: nothing of it is run. Each line is compared with its white space
normalized; a line shorter than MIN_LENGTH, or a trivial one (an import, a comment, a bracket), is not counted, since any two projects share
those. Our files that share at least --min lines are listed, the most first, with the other project's file they share the most with.

A file in ACCEPTED was reviewed and what it shares is functional (an API's address, standard markup): it is listed apart and does not fail the
scan. Any other file fails it (exit code 1): rewrite what it shares in our own way, or, when the match is truly unavoidable, add it to ACCEPTED
with the reason. RELEASING.md runs this before every release.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass

REPO = "https://github.com/fatihak/InkyPi.git"
COMMIT = "bfd8309"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSIONS = (".py", ".html", ".css", ".js", ".ts", ".vue", ".sh")
# not ours to compare: tools' and builds' folders, and vendored code under its own licence (the Waveshare drivers, MIT: VENDORED.md)
SKIP_FOLDERS = frozenset({ ".git", "node_modules", "dist", ".venv", "__pycache__", ".storage", ".test-output", ".mypy_cache", ".ruff_cache", "waveshare_epd" })
MIN_LENGTH = 25
MIN_SHARED = 5
# what every project has: imports, comments, a line of brackets or punctuation, a bare keyword
TRIVIAL = re.compile(r"^(import |from \S+ import |#|//|/\*|\*|\{#|<!--|[\][(){}<>/;,:.\s]+$|(pass|return|else:|try:|finally:)$)")

# our files that share lines with InkyPi for a reason, reviewed (#694): the path from the repository's root, and why
ACCEPTED = {
	"python/static/render/plugin.html": "the @font-face loop and the stylesheet links: what a page that declares its fonts and links its stylesheets is made of",
}


@dataclass(frozen=True)
class Match:
	path: str
	shared: list[str]
	counted: int
	nearest: str


def normalized(text: str) -> set[str]:
	"""The lines of a file that are counted: white space made single spaces, short and trivial lines left out."""
	lines = set()
	for raw in text.splitlines():
		line = " ".join(raw.split())
		if len(line) >= MIN_LENGTH and not TRIVIAL.match(line):
			lines.add(line)
	return lines


def read_tree(root: str) -> dict[str, set[str]]:
	"""The counted lines of every source file under `root`, by its path from `root` (with `/`)."""
	files = {}
	for folder, folders, names in os.walk(root):
		folders[:] = sorted(f for f in folders if f not in SKIP_FOLDERS)
		for name in sorted(names):
			if name.endswith(EXTENSIONS):
				path = os.path.join(folder, name)
				with open(path, encoding="utf-8", errors="replace") as f:
					files[os.path.relpath(path, root).replace(os.sep, "/")] = normalized(f.read())
	return files


def compare(ours: dict[str, set[str]], theirs: dict[str, set[str]], min_shared: int = MIN_SHARED) -> list[Match]:
	"""Our files that share at least `min_shared` counted lines with any of theirs, the most first."""
	owners: dict[str, list[str]] = defaultdict(list)
	for name, lines in theirs.items():
		for line in lines:
			owners[line].append(name)
	found = []
	for path, lines in ours.items():
		shared = sorted(line for line in lines if line in owners)
		if len(shared) >= min_shared:
			nearest = Counter(name for line in shared for name in owners[line]).most_common(1)[0][0]
			found.append(Match(path, shared, len(lines), nearest))
	return sorted(found, key=lambda m: (-len(m.shared), m.path))


def clone(repo: str, commit: str, into: str) -> None:
	"""The project at `commit`, checked out in `into` (a whole clone: a short commit id cannot be fetched by itself)."""
	subprocess.run(["git", "clone", "--quiet", "--no-checkout", "--filter=blob:none", repo, into], check=True)
	subprocess.run(["git", "-C", into, "-c", "advice.detachedHead=false", "checkout", "--quiet", commit], check=True)


def report(found: list[Match], verbose: bool) -> int:
	"""Prints the matches; 1 when one is not ACCEPTED, else 0."""
	failing = [m for m in found if m.path not in ACCEPTED]
	for title, matches in (("Shares lines (rewrite it, or accept it with a reason):", failing), ("Accepted:", [m for m in found if m.path in ACCEPTED])):
		if not matches:
			continue
		print(title)
		for m in matches:
			why = f"  ({ACCEPTED[m.path]})" if m.path in ACCEPTED else ""
			print(f"  {len(m.shared):4d} / {m.counted:4d}  {m.path}   nearest: {m.nearest}{why}")
			if verbose:
				for line in m.shared:
					print(f"        | {line[:160]}")
	print(f"{len(failing)} file(s) to look at, {len(found) - len(failing)} accepted.")
	return 1 if failing else 0


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="List our files that share lines with another project's.")
	parser.add_argument("--repo", default=REPO, help=f"the other project's git address (default {REPO})")
	parser.add_argument("--commit", default=COMMIT, help=f"its commit (default {COMMIT}, the one #694 was checked against)")
	parser.add_argument("--tree", help="a checkout of it already on this machine, instead of cloning")
	parser.add_argument("--min", type=int, default=MIN_SHARED, help=f"the fewest shared lines that list a file (default {MIN_SHARED})")
	parser.add_argument("-v", "--verbose", action="store_true", help="print the shared lines")
	args = parser.parse_args(argv)
	ours = read_tree(ROOT)
	if args.tree:
		return report(compare(ours, read_tree(args.tree), args.min), args.verbose)
	with tempfile.TemporaryDirectory(prefix="provenance-") as folder:
		clone(args.repo, args.commit, os.path.join(folder, "other"))
		return report(compare(ours, read_tree(os.path.join(folder, "other")), args.min), args.verbose)


if __name__ == "__main__":
	sys.exit(main())
