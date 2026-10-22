import contextlib
import io
import json
import os
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts import snapshots
from scripts.snapshots import Http, Repo, Version, manifest_children, next_link, plan_versions, release_check, release_problems, snapshot_name, snapshot_time, snapshots_to_keep

NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"

def stamp(ago: timedelta) -> str:
	return (NOW - ago).strftime("%Y%m%d%H%M%S")

def commit(n: int) -> str:
	return f"{n:040x}"

def digest(n: int) -> str:
	return f"sha256:{n:064x}"

class TestNames(unittest.TestCase):
	"""A snapshot's name is its commit's committer time in UTC, 14 digits."""
	def test_the_name_is_the_time_in_utc(self):
		self.assertEqual(snapshot_name("2026-10-22T14:30:05Z"), "20261022143005")
		self.assertEqual(snapshot_name("2026-10-22T16:30:05+02:00"), "20261022143005")
		with self.assertRaises(ValueError):
			snapshot_name("2026-10-22T14:30:05")

	def test_only_a_real_time_of_14_digits_is_a_snapshot(self):
		self.assertEqual(snapshot_time("20261022143005"), datetime(2026, 10, 22, 14, 30, 5, tzinfo=timezone.utc))
		for name in ["v0.1.0", "2026102214300", "202610221430055", "20261399000000", "sha-abc", "edge"]:
			self.assertIsNone(snapshot_time(name), name)

class TestWhichSnapshotsStay(unittest.TestCase):
	def test_the_newest_stays_however_old(self):
		newest, older = stamp(timedelta(days=40)), stamp(timedelta(days=50))
		self.assertEqual(snapshots_to_keep([older, newest], NOW, 5, 7), ([newest], [older]))

	def test_the_others_stay_while_young_and_at_most_keep_in_all(self):
		young = [stamp(timedelta(hours=h)) for h in range(1, 8)]
		old = stamp(timedelta(days=8))
		kept, removed = snapshots_to_keep(young + [old, "v0.1.0", "edge"], NOW, 5, 7)
		self.assertEqual(kept, young[:5])
		self.assertEqual(removed, young[5:] + [old])

	def test_a_release_or_another_tag_is_never_counted(self):
		self.assertEqual(snapshots_to_keep(["v0.1.0", "latest"], NOW, 5, 7), ([], []))

class TestWhichImagesStay(unittest.TestCase):
	"""An image is an index with untagged children, and its provenance is a version tagged after the index: kept or removed together."""
	def setUp(self):
		self.tree: dict[str, list[str]] = {}
		self.versions: list[Version] = []
		self.n = 0

	def version(self, tags: tuple[str, ...] = (), created: datetime = OLD, children: list[str]|None = None) -> Version:
		self.n += 1
		made = Version(self.n, digest(self.n), created, tags)
		self.versions.append(made)
		self.tree[made.digest] = children or []
		return made

	def image(self, tags: tuple[str, ...], created: datetime = OLD) -> list[Version]:
		"""An index, its image and build attestation, and a provenance attestation (itself an index with a child)."""
		image, built = self.version(created=created), self.version(created=created)
		index = self.version(tags, created, [image.digest, built.digest])
		inner = self.version(created=created)
		proof = self.version(("sha256-" + index.digest.removeprefix("sha256:"),), created, [inner.digest])
		return [index, image, built, proof, inner]

	def plan(self, kept_commits: set[str], kept_snapshots: set[str]) -> set[int]:
		return {v.id for v in plan_versions(self.versions, kept_commits, kept_snapshots, NOW, lambda d: self.tree[d])}

	def test_a_kept_snapshot_keeps_its_whole_image_and_a_removed_one_loses_all_of_it(self):
		kept = self.image((f"sha-{commit(1)}", "20261022100000", "edge"))
		gone = self.image((f"sha-{commit(2)}", "20261001100000"))
		self.assertEqual(self.plan({commit(1)}, {"20261022100000"}), {v.id for v in gone})
		self.assertTrue(all(v.id not in self.plan({commit(1)}, {"20261022100000"}) for v in kept))

	def test_a_release_and_our_own_names_stay(self):
		release = self.image((f"sha-{commit(3)}", "v0.1.0"))
		cache = self.version(("buildcache",))
		edge = self.image((f"sha-{commit(4)}", "edge"))
		self.assertEqual(self.plan(set(), set()), set())
		self.assertEqual(len(release) + 1 + len(edge), len(self.versions))
		self.assertEqual(cache.tags, ("buildcache",))

	def test_an_old_commit_image_without_a_snapshot_goes(self):
		old = self.image((f"sha-{commit(5)}",))
		self.assertEqual(self.plan(set(), set()), {v.id for v in old})

	def test_an_orphan_goes_unless_it_is_young(self):
		orphan = self.version()
		pushing = self.version(created=NOW - timedelta(minutes=10))
		self.assertEqual(self.plan(set(), set()), {orphan.id})
		self.assertNotIn(pushing.id, self.plan(set(), set()))

	def test_tagged_versions_are_removed_first(self):
		self.image((f"sha-{commit(6)}",))
		going = plan_versions(self.versions, set(), set(), NOW, lambda d: self.tree[d])
		self.assertTrue(going[0].tags and going[1].tags)
		self.assertFalse(any(v.tags for v in going[2:]))

	def test_a_kept_commit_wins_over_an_unknown_snapshot_name(self):
		kept = self.image((f"sha-{commit(7)}", "20261001000000"))
		self.assertEqual(self.plan({commit(7)}, set()), set())
		self.assertEqual(len(kept), 5)

class TestRegistryShapes(unittest.TestCase):
	def test_an_index_names_its_manifests_and_a_cache_names_blobs(self):
		index = { "manifests": [{ "mediaType": MANIFEST, "digest": digest(1) }, { "mediaType": INDEX, "digest": digest(2) }] }
		cache = { "manifests": [{ "mediaType": "application/vnd.buildkit.cacheconfig.v0", "digest": digest(3) }] }
		self.assertEqual(manifest_children(index), [digest(1), digest(2)])
		self.assertEqual(manifest_children(cache), [])
		self.assertEqual(manifest_children({ "layers": [{ "digest": digest(4) }] }), [])

	def test_the_next_page(self):
		header = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
		self.assertEqual(next_link(header), "https://api.github.com/x?page=2")
		self.assertIsNone(next_link('<https://api.github.com/x?page=1>; rel="prev"'))
		self.assertIsNone(next_link(""))

class FakeHttp(Http):
	"""GitHub and the registry as `prune` and `make` ask them: what was asked to change is recorded, nothing is sent."""
	def __init__(self, refs: dict[str, str], versions: list[dict[str, Any]], tree: dict[str, list[str]]) -> None:
		super().__init__("")
		self.refs = refs
		self.versions = versions
		self.tree = tree
		self.sent: list[tuple[str, str]] = []
		self.tagged: list[tuple[str, bytes]] = []
		self.missing: set[str] = set()

	def api(self, method: str, path: str, body: dict[str, Any]|None = None) -> tuple[int, Any, dict[str, str]]:
		self.sent.append((method, path))
		if method == "POST" and path.endswith("/git/refs") and body is not None:
			name = body["ref"].removeprefix("refs/tags/")
			if name in self.refs:
				return 422, None, {}
			self.refs[name] = body["sha"]
			return 201, {}, {}
		return 204, None, {}

	def api_ok(self, method: str, path: str, body: dict[str, Any]|None = None) -> Any:
		if "/commits/" in path:
			return { "commit": { "committer": { "date": "2026-10-22T14:30:05Z" } } }
		if "/git/ref/tags/" in path:
			return { "object": { "type": "commit", "sha": self.refs[path.rsplit("/", 1)[1]] } }
		raise AssertionError(path)

	def api_pages(self, path: str) -> list[Any]:
		if "matching-refs" in path:
			return [{ "ref": f"refs/tags/{name}", "object": { "type": "commit", "sha": sha } } for name, sha in self.refs.items()]
		return self.versions

	def manifest(self, repository: str, reference: str) -> tuple[bytes, str]:
		if reference in self.missing:
			raise RuntimeError(f"the manifest {reference} answered 404")
		return json.dumps({ "manifests": [{ "mediaType": MANIFEST, "digest": d } for d in self.tree.get(reference, [])] }).encode(), INDEX

	def put_manifest(self, repository: str, tag: str, raw: bytes, kind: str) -> None:
		self.tagged.append((tag, raw))

REPO = Repo("owner/name", "owner/name", "/users/owner/packages/container/name")

def listed(n: int, tags: list[str], created: datetime = OLD) -> dict[str, Any]:
	return { "id": n, "name": digest(n), "created_at": created.isoformat().replace("+00:00", "Z"), "metadata": { "container": { "tags": tags } } }

class TestCommands(unittest.TestCase):
	def setUp(self):
		# the commands write the job's summary on stdout
		quiet = contextlib.redirect_stdout(io.StringIO())
		quiet.__enter__()
		self.addCleanup(quiet.__exit__, None, None, None)

	def fake(self) -> FakeHttp:
		new, old = stamp(timedelta(hours=1)), stamp(timedelta(days=9))
		refs = { new: commit(1), old: commit(2), "v0.1.0": commit(3) }
		versions = [listed(1, [f"sha-{commit(1)}", new]), listed(2, [f"sha-{commit(2)}", old]), listed(3, [f"sha-{commit(3)}", "v0.1.0"]), listed(4, []), listed(5, ["buildcache"])]
		return FakeHttp(refs, versions, { digest(2): [digest(4)] })

	def test_a_dry_run_changes_nothing(self):
		http = self.fake()
		snapshots.prune(http, REPO, 5, 7, apply=False, now=NOW)
		self.assertEqual([m for m, _ in http.sent if m != "GET"], [])

	def test_apply_removes_the_old_snapshot_its_image_and_its_tag(self):
		http = self.fake()
		snapshots.prune(http, REPO, 5, 7, apply=True, now=NOW)
		deleted = [path for method, path in http.sent if method == "DELETE"]
		self.assertEqual(deleted, [f"{REPO.packages}/versions/2", f"{REPO.packages}/versions/4", f"/repos/{REPO.slug}/git/refs/tags/{stamp(timedelta(days=9))}"])

	def test_make_tags_the_image_then_the_commit_and_can_run_again(self):
		http = FakeHttp({}, [], {})
		for _ in range(2):
			self.assertEqual(snapshots.make(http, REPO, commit(9), digest(9)), "20261022143005")
		self.assertEqual(http.refs, { "20261022143005": commit(9) })
		self.assertEqual([tag for tag, _ in http.tagged], ["20261022143005", "20261022143005"])

	def test_make_refuses_a_name_that_is_another_commits(self):
		http = FakeHttp({ "20261022143005": commit(8) }, [], {})
		with self.assertRaises(RuntimeError):
			snapshots.make(http, REPO, commit(9), digest(9))
		with self.assertRaises(ValueError):
			snapshots.make(http, REPO, "abc", digest(9))

class TestReleases(unittest.TestCase):
	"""A release is v and a version that both version fields say, and it is the snapshot's image under another name, never a new build."""
	def test_the_name_and_the_versions_must_agree(self):
		self.assertEqual(release_problems("v0.1.0", "0.1.0", "0.1.0"), [])
		self.assertEqual(release_problems("v1.2.0-rc.1", "1.2.0-rc.1", "1.2.0-rc.1"), [])
		self.assertEqual(len(release_problems("v0.2.0", "0.1.0", "0.2.0")), 1)
		self.assertEqual(len(release_problems("v0.2.0", "0.1.0", "0.1.0")), 2)
		for name in ["0.1.0", "v0.1", "v0.1.0.1", "20261022143005", "vnext", "v0.1.0-"]:
			self.assertNotEqual(release_problems(name, "0.1.0", "0.1.0"), [], name)

	def test_the_repository_says_one_version(self):
		root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
		with open(os.path.join(root, "pyproject.toml"), "rb") as f:
			python_version = tomllib.load(f)["project"]["version"]
		with open(os.path.join(root, "app", "package.json"), encoding="utf-8") as f:
			app_version = json.load(f)["version"]
		self.assertEqual(python_version, app_version, "pyproject.toml and app/package.json must say the same version (RELEASING.md)")
		self.assertEqual(release_check(f"v{python_version}", root), [])

	def setUp(self):
		quiet = contextlib.redirect_stdout(io.StringIO())
		quiet.__enter__()
		self.addCleanup(quiet.__exit__, None, None, None)

	def test_promote_names_the_commits_image_after_the_release_and_latest(self):
		http = FakeHttp({}, [], {})
		snapshots.promote(http, REPO, "v0.1.0", commit(9))
		self.assertEqual([tag for tag, _ in http.tagged], ["v0.1.0", "latest"])
		self.assertEqual(len({raw for _, raw in http.tagged}), 1)

	def test_promote_refuses_a_commit_without_an_image(self):
		http = FakeHttp({}, [], {})
		http.missing.add(f"sha-{commit(9)}")
		with self.assertRaises(RuntimeError):
			snapshots.promote(http, REPO, "v0.1.0", commit(9))
		self.assertEqual(http.tagged, [])
		with self.assertRaises(ValueError):
			snapshots.promote(http, REPO, "20261022143005", commit(9))

if __name__ == "__main__":
	unittest.main()
