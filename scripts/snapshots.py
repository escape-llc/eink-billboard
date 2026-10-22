"""
Snapshots of master: a tag named after the merge commit's time for every image GitHub published, and the cleanup that keeps them few (#504).

    python -m scripts.snapshots make --commit <full sha> --digest sha256:<image digest>
    python -m scripts.snapshots prune [--keep 5] [--days 7] [--apply]

Run by `.github/workflows/image.yaml` after the master image is published, with `GITHUB_TOKEN` and `GITHUB_REPOSITORY` from the job.

A snapshot is a git tag of 14 digits, the commit's committer time in UTC (`20261022143005`, no `v`), and the same name on the commit's image in
ghcr.io (the very manifest, put under a second tag, so its digest and its attestation are unchanged). A device on the insider channel goes to the
newest one. A release (`v...`) is made by a person, and is never removed here.

`make` is safe to run again: a name that is already the commit's is left as it is; a name that is another commit's is an error.

`prune` keeps the newest snapshot always, and at most `--keep` in all, the others only while they are younger than `--days`. A removed snapshot
loses its git tag and its image together. The images are removed by what they reach, not by their tags: a tagged image is an index whose image and
build attestation are untagged versions of their own, and its provenance attestation is a version tagged `sha256-<the index's hex>`. So every
version that no kept tag reaches is removed, and nothing a kept tag reaches is: a kept tag is a release, a name of our own (`edge`, `buildcache`,
`latest`, anything else that is not a commit's, a snapshot's or an attestation's), the commit of a kept snapshot or a release, and any version
younger than an hour (a build that is still pushing). Without `--apply` it only says what it would remove.

Only the standard library: the job runs it with the runner's Python, before anything is installed. It prints markdown for the job's summary
on stdout and its progress on stderr; it never prints the token.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

API = "https://api.github.com"
REGISTRY = "ghcr.io"

SNAPSHOT = re.compile(r"^[0-9]{14}$")
RELEASE = re.compile(r"^v[0-9A-Za-z._-]{1,100}$")
COMMIT_TAG = re.compile(r"^sha-([0-9a-f]{40})$")
ATTESTATION_TAG = re.compile(r"^sha256-([0-9a-f]{64})$")
STAMP = "%Y%m%d%H%M%S"
# a version this young may belong to a build that is still pushing: never removed
YOUNG = timedelta(hours=1)
# what a registry child that is itself a manifest says it is (anything else, a cache's layers, is a blob and not a version)
MANIFEST_TYPES = {
	"application/vnd.oci.image.index.v1+json",
	"application/vnd.oci.image.manifest.v1+json",
	"application/vnd.docker.distribution.manifest.list.v2+json",
	"application/vnd.docker.distribution.manifest.v2+json",
}
ACCEPT = ", ".join(sorted(MANIFEST_TYPES))

def say(text: str) -> None:
	print(text, file=sys.stderr, flush=True)

def report(text: str) -> None:
	"""A line of the job's summary (markdown)."""
	print(text, flush=True)

# --- the rules (no network) -----------------------------------------------------------------------------------------------------------------

def snapshot_name(committed: str) -> str:
	"""The snapshot's name for a commit's committer time as GitHub gives it (`2026-10-22T14:30:05Z`, or with an offset): that time in UTC."""
	when = datetime.fromisoformat(committed.replace("Z", "+00:00"))
	if when.tzinfo is None:
		raise ValueError("a committer time without a zone")
	return when.astimezone(timezone.utc).strftime(STAMP)

def snapshot_time(name: str) -> datetime|None:
	"""The time a snapshot's name stands for, or None when the name is not a snapshot's."""
	if not SNAPSHOT.match(name):
		return None
	try:
		return datetime.strptime(name, STAMP).replace(tzinfo=timezone.utc)
	except ValueError:
		return None

def snapshots_to_keep(names: Iterable[str], now: datetime, keep: int, days: float) -> tuple[list[str], list[str]]:
	"""The snapshots kept and removed, newest first: the newest always, then those younger than `days`, at most `keep` in all."""
	dated = sorted(((when, name) for name in names if (when := snapshot_time(name)) is not None), reverse=True)
	kept: list[str] = []
	removed: list[str] = []
	for index, (when, name) in enumerate(dated):
		if index == 0 or (len(kept) < keep and now - when <= timedelta(days=days)):
			kept.append(name)
		else:
			removed.append(name)
	return kept, removed

@dataclass(frozen=True)
class Version:
	"""One version of the container package: its id (what a delete names), its digest, when it was made and its tags."""
	id: int
	digest: str
	created: datetime
	tags: tuple[str, ...]

def is_root(version: Version, kept_commits: set[str], kept_snapshots: set[str], now: datetime) -> bool:
	"""Whether a version is kept for itself (before what it reaches): see the module's text."""
	if now - version.created < YOUNG:
		return True
	for tag in version.tags:
		if (commit := COMMIT_TAG.match(tag)) is not None:
			if commit.group(1) in kept_commits:
				return True
		elif SNAPSHOT.match(tag):
			if tag in kept_snapshots:
				return True
		elif ATTESTATION_TAG.match(tag):
			# kept when what it attests is kept: decided by reaching, below
			continue
		else:
			# a release, or a name of our own
			return True
	return False

def reachable(versions: list[Version], roots: set[str], children: Callable[[str], list[str]]) -> set[str]:
	"""Every digest a root reaches: the children of an index (and theirs), and the attestation tagged after any digest reached.
	`children(digest)` answers the manifest digests a version names (an error stops the cleanup: removing on a guess is worse than not removing)."""
	attested: dict[str, list[str]] = {}
	for version in versions:
		for tag in version.tags:
			if (subject := ATTESTATION_TAG.match(tag)) is not None:
				attested.setdefault("sha256:" + subject.group(1), []).append(version.digest)
	seen: set[str] = set()
	waiting = list(roots)
	while waiting:
		digest = waiting.pop()
		if digest in seen:
			continue
		seen.add(digest)
		waiting.extend(children(digest))
		waiting.extend(attested.get(digest, []))
	return seen

def plan_versions(versions: list[Version], kept_commits: set[str], kept_snapshots: set[str], now: datetime, children: Callable[[str], list[str]]) -> list[Version]:
	"""The versions to remove, tagged ones first (so a kept name never points at a half-removed image)."""
	roots = {version.digest for version in versions if is_root(version, kept_commits, kept_snapshots, now)}
	keep = reachable(versions, roots, children)
	removed = [version for version in versions if version.digest not in keep]
	return sorted(removed, key=lambda version: (not version.tags, version.created))

def manifest_children(manifest: dict[str, Any]) -> list[str]:
	"""The digests of the manifests an index lists (an image manifest lists none: its layers are blobs)."""
	return [entry["digest"] for entry in manifest.get("manifests", []) if entry.get("mediaType") in MANIFEST_TYPES and "digest" in entry]

# --- GitHub and the registry ------------------------------------------------------------------------------------------------------------------

class Http:
	"""The few requests this needs, with the job's token; an error says the method, the path and the status, never the token."""
	def __init__(self, token: str) -> None:
		self._token = token
		self._registry: dict[str, str] = {}

	def _send(self, request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
		try:
			with urllib.request.urlopen(request, timeout=60) as answer:
				return answer.status, dict(answer.headers.items()), answer.read()
		except urllib.error.HTTPError as error:
			return error.code, dict(error.headers.items()), error.read()

	def api(self, method: str, path: str, body: dict[str, Any]|None = None) -> tuple[int, Any, dict[str, str]]:
		data = None if body is None else json.dumps(body).encode()
		request = urllib.request.Request(path if path.startswith("https://") else API + path, data=data, method=method)
		request.add_header("Authorization", f"Bearer {self._token}")
		request.add_header("Accept", "application/vnd.github+json")
		request.add_header("X-GitHub-Api-Version", "2022-11-28")
		if data is not None:
			request.add_header("Content-Type", "application/json")
		status, headers, raw = self._send(request)
		return status, (json.loads(raw) if raw else None), headers

	def api_ok(self, method: str, path: str, body: dict[str, Any]|None = None) -> Any:
		status, answer, _ = self.api(method, path, body)
		if status >= 300:
			raise RuntimeError(f"{method} {urllib.parse.urlsplit(path).path} answered {status}")
		return answer

	def api_pages(self, path: str) -> list[Any]:
		"""Every item of a paged list (it follows the `next` link)."""
		items: list[Any] = []
		url: str|None = path
		while url is not None:
			status, answer, headers = self.api("GET", url)
			if status >= 300:
				raise RuntimeError(f"GET {urllib.parse.urlsplit(url).path} answered {status}")
			items.extend(answer)
			url = next_link(headers.get("Link") or headers.get("link") or "")
		return items

	def _registry_token(self, repository: str, actions: str) -> str:
		"""A registry token for the repository's image (`pull`, or `pull,push`), got with the job's token."""
		key = f"{repository}:{actions}"
		if key not in self._registry:
			query = urllib.parse.urlencode({ "scope": f"repository:{repository}:{actions}", "service": REGISTRY })
			request = urllib.request.Request(f"https://{REGISTRY}/token?{query}")
			basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
			request.add_header("Authorization", f"Basic {basic}")
			status, _, raw = self._send(request)
			if status >= 300:
				raise RuntimeError(f"the registry's token for {actions} answered {status}")
			self._registry[key] = json.loads(raw)["token"]
		return self._registry[key]

	def manifest(self, repository: str, reference: str) -> tuple[bytes, str]:
		"""A manifest exactly as the registry keeps it, and its media type."""
		request = urllib.request.Request(f"https://{REGISTRY}/v2/{repository}/manifests/{reference}")
		request.add_header("Authorization", f"Bearer {self._registry_token(repository, 'pull')}")
		request.add_header("Accept", ACCEPT)
		status, headers, raw = self._send(request)
		if status >= 300:
			raise RuntimeError(f"the manifest {reference} answered {status}")
		kind = headers.get("Content-Type") or headers.get("content-type") or json.loads(raw).get("mediaType", "")
		return raw, kind

	def put_manifest(self, repository: str, tag: str, raw: bytes, kind: str) -> None:
		"""The same manifest under another tag: the same bytes, so the same digest."""
		request = urllib.request.Request(f"https://{REGISTRY}/v2/{repository}/manifests/{tag}", data=raw, method="PUT")
		request.add_header("Authorization", f"Bearer {self._registry_token(repository, 'pull,push')}")
		request.add_header("Content-Type", kind)
		status, _, _ = self._send(request)
		if status >= 300:
			raise RuntimeError(f"tagging the image {tag} answered {status}")

def next_link(header: str) -> str|None:
	"""The `next` address of a `Link` header, or None."""
	for part in header.split(","):
		match = re.match(r'\s*<([^>]+)>\s*;\s*rel="next"', part)
		if match is not None:
			return match.group(1)
	return None

@dataclass(frozen=True)
class Repo:
	"""Where things are: the repository (`owner/name`), its image's registry name (lower case) and the packages API path of that image."""
	slug: str
	image: str
	packages: str

def repo_of(http: Http, slug: str) -> Repo:
	owner, name = slug.split("/", 1)
	kind = http.api_ok("GET", f"/repos/{slug}")["owner"]["type"]
	where = "orgs" if kind == "Organization" else "users"
	image = slug.lower()
	return Repo(slug, image, f"/{where}/{owner}/packages/container/{urllib.parse.quote(name.lower(), safe='')}")

def tag_commits(http: Http, repo: Repo) -> dict[str, str]:
	"""Every git tag and the commit it names (an annotated tag is followed to its commit)."""
	found: dict[str, str] = {}
	for ref in http.api_pages(f"/repos/{repo.slug}/git/matching-refs/tags/?per_page=100"):
		name = ref["ref"].removeprefix("refs/tags/")
		target = ref["object"]
		while target["type"] == "tag":
			target = http.api_ok("GET", f"/repos/{repo.slug}/git/tags/{target['sha']}")["object"]
		if target["type"] == "commit":
			found[name] = target["sha"]
	return found

def package_versions(http: Http, repo: Repo) -> list[Version]:
	versions = []
	for item in http.api_pages(f"{repo.packages}/versions?per_page=100"):
		created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
		tags = tuple(item.get("metadata", {}).get("container", {}).get("tags", []))
		versions.append(Version(item["id"], item["name"], created, tags))
	return versions

# --- the commands -------------------------------------------------------------------------------------------------------------------------

def make(http: Http, repo: Repo, commit: str, digest: str) -> str:
	"""Name the commit's image and the commit itself after the commit's time; answers the name."""
	if not re.match(r"^[0-9a-f]{40}$", commit) or not re.match(r"^sha256:[0-9a-f]{64}$", digest):
		raise ValueError("a full commit and an image digest are needed")
	name = snapshot_name(http.api_ok("GET", f"/repos/{repo.slug}/commits/{commit}")["commit"]["committer"]["date"])
	raw, kind = http.manifest(repo.image, digest)
	# the commit's image first, so a snapshot's git tag never names a commit whose image has not got the name
	http.put_manifest(repo.image, name, raw, kind)
	status, answer, _ = http.api("POST", f"/repos/{repo.slug}/git/refs", { "ref": f"refs/tags/{name}", "sha": commit })
	if status == 422:
		# there already: fine when it is this commit's (a job run again), an error when it is another's
		existing = http.api_ok("GET", f"/repos/{repo.slug}/git/ref/tags/{name}")["object"]
		if existing["type"] != "commit" or existing["sha"] != commit:
			raise RuntimeError(f"the snapshot {name} is already another commit's")
	elif status >= 300:
		raise RuntimeError(f"making the tag {name} answered {status}")
	say(f"Snapshot {name}: commit {commit[:7]}, image {digest}")
	report(f"Snapshot `{name}`: commit `{commit[:7]}`, image `{digest}`.")
	return name

def prune(http: Http, repo: Repo, keep: int, days: float, apply: bool, now: datetime|None = None) -> None:
	now = now or datetime.now(timezone.utc)
	tags = tag_commits(http, repo)
	kept, removed = snapshots_to_keep(tags.keys(), now, keep, days)
	releases = [name for name in tags if RELEASE.match(name)]
	kept_commits = {tags[name] for name in kept} | {tags[name] for name in releases}
	versions = package_versions(http, repo)

	def children(digest: str) -> list[str]:
		raw, _ = http.manifest(repo.image, digest)
		return manifest_children(json.loads(raw))

	going = plan_versions(versions, kept_commits, set(kept), now, children)
	verb = "Removed" if apply else "Would remove (dry run)"
	report(f"Snapshots kept: {', '.join(f'`{name}`' for name in kept) or 'none'}; releases kept: {len(releases)}.")
	report(f"{verb}: {len(removed)} snapshot tags, {len(going)} of {len(versions)} image versions.")
	for name in removed:
		report(f"- tag `{name}` (commit `{tags[name][:7]}`)")
	for version in going:
		report(f"- image version {version.id} `{version.digest[:19]}` {', '.join(version.tags) or '(untagged)'}")
	if not apply:
		return
	for version in going:
		status, _, _ = http.api("DELETE", f"{repo.packages}/versions/{version.id}")
		if status >= 300 and status != 404:
			raise RuntimeError(f"removing image version {version.id} answered {status}")
	for name in removed:
		status, _, _ = http.api("DELETE", f"/repos/{repo.slug}/git/refs/tags/{name}")
		if status >= 300 and status != 422:
			raise RuntimeError(f"removing the tag {name} answered {status}")

def main(argv: list[str]) -> int:
	parser = argparse.ArgumentParser(prog="python -m scripts.snapshots", description="Snapshots of master and their cleanup (#504).")
	commands = parser.add_subparsers(dest="command", required=True)
	making = commands.add_parser("make", help="name a published commit's image and the commit after the commit's time")
	making.add_argument("--commit", required=True)
	making.add_argument("--digest", required=True)
	pruning = commands.add_parser("prune", help="remove the snapshots and images not kept")
	pruning.add_argument("--keep", type=int, default=5)
	pruning.add_argument("--days", type=float, default=7)
	pruning.add_argument("--apply", action="store_true", help="remove them (without it: only say what would go)")
	args = parser.parse_args(argv)
	token = os.environ.get("GITHUB_TOKEN", "")
	slug = os.environ.get("GITHUB_REPOSITORY", "")
	if not token or "/" not in slug:
		say("GITHUB_TOKEN and GITHUB_REPOSITORY (owner/name) are needed")
		return 2
	http = Http(token)
	repo = repo_of(http, slug)
	if args.command == "make":
		make(http, repo, args.commit, args.digest)
	else:
		if args.keep < 1:
			say("--keep is at least 1: the newest snapshot is always kept")
			return 2
		prune(http, repo, args.keep, args.days, args.apply)
	return 0

if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
