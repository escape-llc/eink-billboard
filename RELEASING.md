# Cutting an eInk Billboard release

Read this only when the maintainer asks for a release; it is not standing context for every session (`AGENTS.md` points here).

Every merge to `master` is already a **snapshot** (`20261022143005`, made by `.github/workflows/image.yaml`): the **insider** channel follows them. A **release** (`vX.Y.Z`) is a snapshot a person has said is ready, and it is what the **stable** channel, every new Pi's, follows. Nothing is built for a release: `.github/workflows/release.yml` gives the snapshot's image the release's name, so stable runs the very image insider ran.

**Only when the maintainer asks for a release, and only the version they name.** If they did not name it, ask before step 1: never infer a version from the history.

1. **Bump the version in both places**, to the named version without the `v`: `version` in `pyproject.toml` and in `app/package.json` (and the two `version` lines at the top of `app/package-lock.json`, which `npm install --package-lock-only` rewrites). `test_snapshots` fails while they disagree, and `release.yml` refuses a tag they do not say.
2. **Verify for real**, on that branch:
   - `uv run python -m unittest discover .`, `uv run ruff check`, `uv run mypy`, and `podman compose run --rm test` (Linux, with Chromium: what CI runs);
   - `cd app && npm run build && npm test && npm run e2e`;
   - `deploy/test/pull-path.sh` in a Bookworm container (the command is at its top): the Pi's side of getting a version.
3. **Run the audits:** the `owasp-review` and `actions-injection-review` skills (`.claude/skills/`; a tool that cannot load a skill reads its `SKILL.md`). Fix what they find, or file an issue for it, before the tag.
4. **Merge the bump** through the usual `WORKFLOW.md` sequence, then **wait for its snapshot** (WORKFLOW.md step 10): `git ls-remote --tags origin` lists the new 14-digit tag on the merge commit.
5. **Try it on a real device:** the maintainer's insider Pi runs `deploy/eink-container.sh update --insider`, which goes to that snapshot, and `check` is all fine (`ok` lines, no `FIX`). Fix any real failure before tagging, not after.
6. **Tag only with the maintainer's go-ahead on that version.** This is the one step that cannot be taken back: every stable Pi moves to it on its next `update`.
   ```
   git fetch origin && git checkout <the snapshot's commit> && uv run python -m scripts.snapshots release-check --tag vX.Y.Z
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```
   The check is the one `release.yml` makes, run **before** the push: a stable Pi follows a tag as soon as it is pushed (the commit's image is there already), so the workflow can only report a wrong tag, not stop it. A tag pushed by a person starts `release.yml` (one pushed by a workflow's token would not).
7. **Watch it through:** `gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status`. It checks the tag is on `master` and agrees with both version fields, gives the commit's image the names `vX.Y.Z` and `latest`, and creates the GitHub release with the list of pull requests since the last one (`gh release view vX.Y.Z`). A failed run leaves the tag without its names and its GitHub release, but stable Pis already follow the tag: fix the cause, and if the tag itself is wrong (another commit, another version), delete it at once (`git push origin :refs/tags/vX.Y.Z`, with the maintainer's go-ahead) so stable Pis go back to the release before it on their next `update`, then tag again.
8. **Announce it** in Discussions, under **Announcements** (repository `R_kgDOPwjIug`, category `DIC_kwDOPwjIus4DHBG7`): what changed since the last release (`git log v<previous>..vX.Y.Z --oneline`), written as prose with the biggest change first, not a list of commits; and what a stable Pi will notice. Post it with `gh api graphql` (`createDiscussion`, the body from a file with `-F body=@file`).

Steps 1 to 5 can be undone. Step 6 cannot; step 8 needs no go-ahead of its own once the release is confirmed.

The snapshot cleanup never removes a release or its image, so an old release stays installable (`update vX.Y.Z`) for good.
