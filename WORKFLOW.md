# eInk Billboard: Contributor Workflow

How a real change gets from "idea" to "merged", for whoever (human or AI) is doing the work. This is process, not code conventions: see `AGENTS.md` for those.
Standing default: every real change goes through this sequence, not a direct commit to `master`.

## Expected tools

- **GitHub access that can read and write issues and PRs.** Either the GitHub CLI (`gh auth status`; `gh auth login` if it fails) or, in an agent session, the GitHub tools it was given.
  Everything below says "open a PR", "check CI", and so on; use whichever you have. If a push or API call returns 403, stop and tell the maintainer (see `AGENTS.md`).
- **Current limitation (until the maintainer sets up a GitHub token for cloud sessions):** `gh` is installed in the cloud sandbox but its `GH_TOKEN` is invalid, so every `gh` command fails
  (`gh auth status` shows it). In that situation do not try to find another token; work around it:
  - issues, labels, PRs, review replies, merging, and checking CI: use the GitHub tools the session provides (the `mcp__github__*` tools) instead of `gh`;
  - session summaries: those tools have no Discussions support, so **draft the summary** (per `SESSION_SUMMARIES.md`) and give it to the maintainer to post;
  - everything else in the sequence is unchanged.
  The maintainer may later run these sessions from the Claude Code extension, which uses the maintainer's own signed-in `gh` and can run the `gh` commands directly.
  Once a valid token is in the environment (`GH_TOKEN`, with write access to issues, pull requests, and Discussions), delete this note.
- `git`, `uv` (Python 3.13), and for web changes `node`/`npm`. CI uses `python:3.13.7-slim`; match that locally.
- Test environment prerequisites (the ignored `python/tests/.storage/`, `chromium-headless-shell`) are in `AGENTS.md`.

## The sequence

1. **Look before starting.** Read the last several session summaries and any unanswered review comments on recent PRs (see `AGENTS.md`, "Generalizing lessons"). Skip for a trivial typo.
2. **Open an issue** describing what is changing and why. Label it with existing labels that fit; do not invent a new label without asking.
3. **Branch off an up-to-date `master`** (`git fetch origin master`, then branch from `origin/master`; never from a stale local copy). Agents work on the branch the session names (`claude/<name>`).
4. **Make the change and verify it locally** before pushing: the Python tests you touched plus `test_web_api`, and for web changes `npx vite build` and the `vue-tsc` before/after comparison.
   If CI restores test data from a secret, also run the affected tests **without** `datasources/` and `plugins/` in the test storage (see `AGENTS.md`).
   Re-read your own diff adversarially, then check what is staged: `git diff --cached --name-only` must show no storage files, keys, `dist/`, or `node_modules`.
5. **Commit.** Imperative subject, a body that says *why*, and the attribution trailers the session was given. Reference the issue number in the body if it clarifies.
6. **Push** (`git push -u origin <branch>`), then **open a PR** referencing the issue. The body has a `## Summary` and a `## Test plan`; the test plan says what was actually verified and what was not run, not what should theoretically pass.
   Use `Closes #N` only when this PR is the *whole* fix (see "Partial fixes"). Label it like its issue. Reference issues and PRs as `owner/repo#N`.
7. **Wait for CI to go green before merging, always.** Required: the `unittest` job (`CI Tests (uv + Container)`) and CodeQL. Never merge on "the diff looks right" alone.
8. **Read every review comment's content**, not just whether the review check passed. Evaluate each finding and reply on its thread: fix the confirmed ones (and say which commit), and answer false positives with what you actually checked.
   A reply the next reviewer can read is what stops a settled finding from being raised again.
9. **Squash-merge and delete the branch, automatically.** The maintainer's standing preference (2026-10-04) is that a PR merges by itself once CI is green on its latest head and no review thread is waiting on you; do not wait to be asked.
   GitHub's auto-merge is enabled for this repository, and a ruleset on `master` requires a pull request (0 approvals), the `unittest` check, and CodeQL, with squash merges and head-branch deletion.
   So right after opening the PR, **turn on auto-merge for it** (`gh pr merge <N> --auto --squash`, or the GitHub tool `enable_pr_auto_merge` with `SQUASH`), and keep the PR subscribed so a red check or conflict still reaches you.
   If auto-merge cannot be enabled (the call says the PR is already mergeable, or the setting is off), merge it yourself when the green result arrives: confirm the head SHA is the one that passed and the PR is mergeable, then squash-merge pinned to that SHA.
   Anything red, conflicted, or with an open review thread is not merged: fix it first. A push to the branch restarts the checks; auto-merge stays armed for the new head.
10. **Close the issue** if the merge did not already auto-close it.
11. **Sync local `master`** (`git checkout master && git pull --ff-only`) and drop the merged local branch. A merged PR is finished; further work starts a new branch.
12. **Write up the piece of work** per `SESSION_SUMMARIES.md`: one summary per commit-worthy unit of work, posted to Discussions (or drafted for the maintainer to post), with a one-line back-link comment on the PR.

Not every one-line typo fix needs the full ceremony, but a real change (new behavior, a real bug fix, a config or infrastructure change) does, by default.
When in doubt, run the sequence: an extra issue and PR is cheap; an undocumented direct-to-`master` change leaves the next session with no idea why something is the way it is.

### Where this differs from "just ask the agent"

- Opening a PR still needs the maintainer to have asked for the change to land (an agent session may have its own rule requiring an explicit request, and that rule wins). Merging does not: once a PR exists, arm auto-merge (step 9) so it lands when green.
- Whoever works on a PR owns it until it is green and mergeable: a red check or a merge conflict is work now, not something to leave for review.

## A literal per-issue checklist, not just this file's prose

Long sessions drift away from steps they have already run a dozen times, not because the text is missing but because recalling the right step at the right moment under momentum is a different failure.
At the start of each issue, write this checklist as a file in **your own scratchpad or notes (never in the repo)**, and *update* it at each real transition (CI green, right before merging, right after posting the summary) rather than recalling it.

```markdown
- [ ] Read recent session summaries / unanswered PR review comments
- [ ] Issue filed and labeled
- [ ] Branched from a freshly fetched master
- [ ] Change made; verified locally (tests touched + test_web_api; vite build / vue-tsc comparison for web; CI-storage run)
- [ ] Staged files checked (no storage, keys, dist, node_modules)
- [ ] Committed with attribution trailers, pushed
- [ ] PR opened (Closes #N only if it is the whole fix), labeled, Summary + Test plan
- [ ] CI green on the latest head
- [ ] Review comment content read; every finding answered on its thread
- [ ] Squash-merged, branch deleted, issue closed
- [ ] Local master synced
- [ ] Session summary posted (or drafted), back-link left on the PR
```

## Boundaries this sequence has hit

- **A green-locally test can fail CI because CI's test storage is smaller than yours.** CI restores `python/tests/.storage/` from a secret that omits `datasources/` and `plugins/`. Reproduce under those conditions before pushing a test that touches them (PR #19's first run failed this way).
- **A failed check is not automatically a regression, and not automatically a flake.** First confirm the failing test has a plausible connection to your diff; if not, look for the same test passing on other recent runs with no relevant change in between.
  Only then re-run the specific failed job, once. A second failure is a different signal: investigate it. Never skip, disable, or quarantine a test to get green.
- **Failures from the previous head do not matter, failures on the latest head do.** After a fix push, CI restarts; check the run for the *current* head SHA, not an older red one.
- **A green PR can still refuse to merge** when the repository requires the branch to be up to date with `master`. Merge `master` into the branch, push, and wait for the fresh run; do not rewrite history on a shared branch.
- **Partial fixes shouldn't use `Closes #N`.** When an issue names two things and the PR does one, write `Part of #N` so merging does not silently close the remainder.
- **Repository-security changes** (branch protection, secrets, tokens) need the maintainer's explicit go-ahead for that specific change at that moment.
- **Validate files nothing else validates.** The Python tests do not parse `.github/workflows/*.yml` or the Vue types; before pushing a change to such a file, find something that parses it locally rather than making CI's run its first real validation.
