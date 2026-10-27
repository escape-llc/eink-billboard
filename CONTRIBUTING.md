# Contributing to eInk Billboard

This repo is meant to be worked on through an AI-guided session as much as by hand: point a coding agent (Claude Code or an equivalent) at it and it works from the
instructions already written into the repo, which a human contributor should follow too.

- **[AGENTS.md](AGENTS.md)**: the working agreement. What to do before starting, layout, commands, the test environment (including the ignored test storage and what CI does differently),
  the core rules for the web API, settings, and secrets, and the boundaries this repo has already hit. `CLAUDE.md` imports it.
- **[WORKFLOW.md](WORKFLOW.md)**: how a real change gets from idea to merged: issue, branch, local checks, PR, CI green, review replies, squash-merge, close, sync,
  summary. Includes the per-issue checklist.
- **[SESSION_SUMMARIES.md](SESSION_SUMMARIES.md)**: how a piece of work is written up afterwards in Discussions, including the friction, so the next session has a real record.
- **[RELEASING.md](RELEASING.md)**: how a snapshot of `master` becomes a release the stable channel follows; read only when the maintainer asks for a release.
- **[readme.md](readme.md)**: what the project is, its known limitations and how to install a Pi.
- **[docs/](docs/)**: [architecture.md](docs/architecture.md) (display layers, compositor, tasks, storage), [development.md](docs/development.md) (running it, containers, the web API conventions, metering, telemetry) and [pi-commands.md](docs/pi-commands.md) (the Pi kit's commands).
  The rules for one part of the code, moved out of `AGENTS.md` so it stays short: [forms-and-descriptors.md](docs/forms-and-descriptors.md), [data-sources.md](docs/data-sources.md), [panel-and-rendering.md](docs/panel-and-rendering.md), [tasks-and-storage.md](docs/tasks-and-storage.md), [access-and-network.md](docs/access-and-network.md), [web-app.md](docs/web-app.md) and [containers-and-deploy.md](docs/containers-and-deploy.md). `AGENTS.md` says which to read before touching what.
