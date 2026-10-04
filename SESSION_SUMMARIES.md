# eInk Billboard: Session Summaries (for this repo's Discussions)

A reusable prompt to get an agent to self-report a clean, Discussion-ready summary of one piece of contributor work: a feature, a bug fix, a refactor.
Its most valuable part is the friction: what was not obvious from `AGENTS.md` or the readme, because that feeds directly back into this repo's docs and backlog.

## When to write one

**Not** once at the end of a long, multi-commit session: early friction has fallen out of context by then, and unrelated pieces of work get flattened into one unfocused post.
Write one at each natural checkpoint, right before or after the PR that represents "this piece is done and works". Skip trivial or mechanical changes (typos, formatting).

Rule of thumb: **one summary per commit-worthy unit of work, written while it is still the freshest thing in context, not one summary per session.**

- **Merge before posting** when the Outcome links to a PR or commit, so the link is live for readers.
- **Back-link from the PR.** After posting, add a one-line comment on the PR the Outcome names ("Session summary: <discussion URL>"), not a copy of the summary.
  Someone who lands on the PR directly after the branch is gone then has a breadcrumb. For a multi-PR piece of work, comment on the PR the summary calls the outcome, not every PR along the way.

## Where it goes

Post to a Discussions category named **AI Session Summaries**. If Discussions or that category does not exist yet, the maintainer creates it in the repository settings (an agent cannot).
An agent without a tool that can create discussions drafts the text and hands it to the maintainer to post; it never posts on the maintainer's behalf unless asked.
These are maintainer-directed build-in-public notes; let them read as what they are.

## The prompt

Paste this in immediately after a checkpoint, before moving on to the next distinct task:

```
Write a summary of the work we just completed, formatted for a GitHub Discussion post. Scope it to only this piece of work; if we touched something
unrelated earlier in this session, leave it out, it gets its own post.

Include, as headers:

1. **Goal**: one line, what was being built or fixed.
2. **Surface touched**: an explicit list of what was added or modified (files, endpoints, settings, options), plus any existing pattern you followed
   (for example "the `ApiError` handlers as the precedent for a new error"). If you reached for something that did not fit and fell back to another approach, say so.
3. **Approach**: the instructions that got this working, condensed to the essential ask, not the full back-and-forth.
4. **Outcome**: what the result looks like, with a link to the merged PR (only once it is merged), and what was verified versus not run
   (which tests, which were network-dependent and could not run, whether the UI was exercised in a browser).
5. **Friction**: anything that took extra turns, was not obvious from AGENTS.md/the readme, or required guessing. Be specific and honest, even when it reflects a gap
   in the docs or the code: this section is the most valuable part of the post.
6. **Review and CI**: for every review comment and every red CI run on the PR, say whether it was a real defect (and the fix) or a false positive (and why),
   and note anything a later pass caught that the review missed. "Reported nothing, correctly" is a valid entry.

Keep it tight: a maintainer should be able to read the whole thing in under a minute. Skip anything not directly relevant to contributing to this repo.
Never include secrets, key material, or the contents of storage files.
```

## Maintainer-side handling

- **Batch, then review before posting.** Several short summaries from one session are reviewed together and posted individually (or as a short thread), not merged into one post.
- **Filter for signal.** Not every checkpoint needs to go public: post the ones that show a reusable pattern or surface a real friction point. Routine ones can stay local.
- **Fold what repeats back into `AGENTS.md`**, at the level of the underlying pattern (see "Generalizing lessons" there), so the next session finds it without searching Discussions.
