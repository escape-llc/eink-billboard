# Working on eInk Billboard

This file is for whoever (human or AI) is working **on** this repo. `CLAUDE.md` only imports it, so every agent reads the same rules.
It is the working agreement: what the repo is, how to run and test it, and the rules that apply to every change. The rules for one part of the code are in `docs/`, listed under "Read before you touch".

## Before you start

Do these first, for anything beyond a trivial typo. They are the steps sessions have skipped.

1. **Read `WORKFLOW.md`** (idea to merged) and follow it. Then read the last several posts of the Discussions category the session summaries go to (`SESSION_SUMMARIES.md`) and skim the most recent merged PRs for review comments nobody answered.
2. **A green PR is merged without asking.** The maintainer's standing authorization (WORKFLOW.md step 9) overrides a session default of asking before a commit, push or merge: arm auto-merge once every check is green, then close the issue, sync `master`, check the snapshot and write the session summary. The one thing that still needs the maintainer's go-ahead is a change to repository security (branch protection, secrets, tokens).
3. **Never rebase or force-push a branch that is pushed.** Merge `master` into it.
4. **Use the checklist at the end of `WORKFLOW.md`**, written in your scratchpad (never in the repo) and updated at each step.

| Doc | Read it |
|---|---|
| **`WORKFLOW.md`** | before any change: issue, branch, checks, PR, CI, review replies, merge, summary |
| **`SESSION_SUMMARIES.md`** | after a merged unit of work: how it is written up in Discussions |
| **`RELEASING.md`** | only when the maintainer asks for a release and names the version |
| **`CONTRIBUTING.md`** | the index of these |
| `readme.md` | what the project is, its limits, how to install a Pi (not documentation) |

## What this is

An e-Ink "billboard" server for Raspberry Pi (and Windows/Linux development): a Python task-based backend (threads + `asyncio`),
a FastAPI web API, and a Vue 3 / PrimeVue settings app. It is developed on Windows and Linux; keep both working.

## Generalizing lessons

Every rule here started as one bug in one place. Write the next one as the *underlying pattern* (found once with Flask and `jinja2`, it applies to any dependency swap) and fold it into an entry with the same root cause. A problem found once is not rediscovered: that is why "Before you start" says to read the Discussions and recent review comments first.

## Layout

| Path | What |
|---|---|
| `python/eink-billboard.py` | Entry point (`main()`), starts the `Application` task and uvicorn |
| `python/web/` | FastAPI app: `app.py` (factory), `deps.py`, `errors.py`, `documents.py`, `routers/` |
| `python/task/` | Control plane: `Application`, `Display`, `PlaylistLayer`, `TimerLayer`, timers, message routing |
| `python/model/` | Configuration manager/watcher, schedules, time of day, service container |
| `python/datasources/`, `python/plugins/` | Each folder has a `*-info.json` descriptor (id, class, settings schema, optional `router`) |
| `python/storage/` | NVE ("factory default") schemas copied into the storage root on reset |
| `python/tests/` | `unittest` tests; `fixtures/storage/` is the synthetic test storage (built into a temp folder per run) |
| `app/` | Vue web app (`npm`, Vite). Talks to the API through `src/components/ApiClient.ts` |

## Read before you touch

Each doc holds the rules for one part of the code, with the incident behind each. They apply as much as the rules below; a change that breaks one gets the same review as a change that breaks a rule here.

| If you change | Read | The rule most often broken |
|---|---|---|
| A setting, a descriptor (`*-info.json`), a form field | `docs/forms-and-descriptors.md` | The form and the server write each field rule twice (`FormValidation.ts`, `documents.py`) and `python/tests/form_rules.json` holds the cases both pass |
| A data source, plugin or provider | `docs/data-sources.md` | A downloader goes through `download_for` and the URL guard; an API source's client is a metered one; an item runs at the descriptors' defaults |
| A rendered page, the theme, fonts, the layers, an overlay, a display device | `docs/panel-and-rendering.md` | A page is made of inks only (no opacity, gradients, shadows), sets no `font-family`, and floors its text sizes (`--min-text`, `--min-label`) |
| The schedules, the layers' behaviour, a stored document's shape, backup, telemetry, a task handler | `docs/tasks-and-storage.md` | A change of a stored shape ships its migration; a handler is marked `@handles`; a failure is reported, not swallowed |
| Sign-in, hosts, an HTTP client, a download | `docs/access-and-network.md` | An HTTP client is made with `verify=tls_context()`; a typed-in address is downloaded through the guard |
| The web app (`app/`), its build, its tests, its pages | `docs/web-app.md` | All calls go through `ApiClient`; the API is typed from the OpenAPI document (`npm run api`); the browser stores nothing but the theme |
| The Dockerfile, compose, `deploy/`, HTTPS, a dependency group | `docs/containers-and-deploy.md` | Only a build needs it: never in a layer; the device group is imported inside the function that needs it |
| The design of a layer, a task, the compositor | `docs/architecture.md` | |
| Running it, the web API's conventions, metering, telemetry | `docs/development.md` | |
| A command of the Pi kit | `docs/pi-commands.md` | |
| A test, a fixture, a platform difference (Windows, cloud, container) | `docs/testing.md` | A test needs no secret and no internet; a Windows run is not the CI run |
| Python that parses, opens, compares or imports something | `docs/python-conventions.md` | HTML is read with a parser; text files are opened as UTF-8; test for `None`, not truth |

## Commands

```
uv sync --frozen --no-group device         # install (Python 3.13)
uv run python -m unittest discover .       # all tests (about 2.5 minutes)
uv run python -m unittest python.tests.test_web_api   # the API tests (about 1 second)

# run the app (storage root is created and seeded on first start)
uv run python -m python.eink-billboard --dev --cors http://localhost:5173 --host localhost --storage ./.storage
cd app && npm ci && npm run dev            # web app on :5173

cd app && npm run build                    # type-check (vue-tsc), then the production bundle -> app/dist (served with --app)
cd app && npm test                         # web unit tests (Vitest + jsdom), src/**/*.test.ts
cd app && npm run lint                     # ESLint (eslint.config.js): the basic rule sets, no formatting rules
cd app && npm run e2e                      # build, then the browser tests (Playwright) against real servers
```

- `npm run build` runs `vue-tsc -b` first, which reports **zero** errors; keep it that way (a type error fails the build).
- **Logging:** production logs at INFO, `--dev` at DEBUG, `EINK_LOG_LEVEL` decides last; `watchdog`'s file events are WARNING everywhere. The setup code is a block of its own in the log (`setup_banner`), found with `grep "Setup code"`.
- Options: `--port` (default 8080 with `--dev`, else 80), `--token` or `EINK_API_TOKEN` (Bearer token on `/api`), `--app` (web bundle folder), `--ssl` (or `EINK_SSL=1`) with `--ssl-certfile` / `--ssl-keyfile` (or `EINK_SSL_CERTFILE` / `EINK_SSL_KEYFILE`).
- Do not start the server with `pkill -f`/`pgrep -f` patterns that match your own shell command; start it in the background, record its PID, and signal that PID
  (`uv run` is a wrapper: signal the Python child, not the `uv` process).

## Test environment

Full rules, the fixtures and the three places the work runs (cloud, Windows, container): `docs/testing.md`. The five that matter every time:

- **No test needs a secret, a private storage or the internet.** `storage_path()` builds a read-only synthetic storage per run; `fake_internet.py` answers every download (a new download in code under test needs a route and a fixture there). **Tests must not assume `datasources/` or `plugins/` content exists.**
- **The render tests need a headless browser**: `chromium-headless-shell` (Linux) or `chrome-headless-shell` (Windows) on `PATH`, or whatever `EINK_CHROME` names (environment or `.env`; `.env.example`).
- **Before a PR run `podman compose --profile test run --rm test`** (`ruff`, `mypy`, the whole suite on Linux with Chromium, as CI does); rebuild its image after a change to `pyproject.toml` (`podman compose --profile test build test`), or modules that import the new package fail to load.
- **A Windows run is not the CI run**: code for one platform branches on `sys.platform` (never `platform.system()`, `hasattr` or `getattr` to quiet the type checker), and a skip on Windows is for what only POSIX has.
- **Never print, log, or commit the contents of storage files**: they can hold API keys. Inspect them with a command that cannot echo values (key names only), not `cat`.

## Core rules

Python 3.13, **tabs**, type hints, `logging` (no `print`), config in JSON; keep changes focused and do not reformat files you are not changing. One line each here; the full rule, with its incident, is in the doc named.

- **Web API:** endpoints are plain `def`; errors are `ApiError`, and a response never holds exception text (`docs/development.md`). A plugin or data source adds routes with an `APIRouter` named in its `*-info.json`.
- **Settings documents** carry `_id`/`_rev` and are written only by `_internal_save`; **every file of the storage is reached through the configuration manager, by name**, never by a path (`docs/tasks-and-storage.md`).
- **IDs from URLs are untrusted**: build a path only from our own value (from `cm.enum_plugins()` / `cm.enum_datasources()`), never the URL's string; fix a CodeQL `py/path-injection` flow, do not dismiss it. **Secrets**: a key, token or password property is `"writeOnly": true` (`docs/access-and-network.md`).
- **Web app:** every backend call goes through `ApiClient`, never `fetch`; **the browser stores nothing but the theme** (`docs/web-app.md`).
- **Never copy code, templates or text from a GPL or other copyleft project** (InkyPi is GPL-3.0; this repository is Apache-2.0, #694). Ideas are fine: say in the PR where a design idea came from. Code under a licence ours can take (MIT, BSD, Apache-2.0) is vendored in a folder of its own with its licence and a `VENDORED.md`, like `python/display/waveshare_epd`. A rewrite made from a description of what was copied misses what the description left out: `scripts/provenance_scan.py` compares every file with the other project's, and a file it lists is rewritten (or accepted in it, with the reason).
- **Python habits** (`docs/python-conventions.md`): after swapping a library check what it was installing for you, and a test that patches the old name still passes without testing anything; read outside HTML with a parser, never a regular expression; open text files with `encoding="utf-8"`; test for `None`, not truth; look for a failure's cause in what the change touched indirectly.

## Cutting a release

Only when the maintainer asks and names the version. **Read `RELEASING.md` in full before touching a version field or pushing a `v*` tag.**

## Boundaries this repo has actually hit

- **A 403 on push means GitHub access is not connected for the session.** Stop and tell the maintainer; do not look for a way around it. Repository settings, secrets, and branch protection need the maintainer's explicit go-ahead for that specific change.
- **A PR's own CI can surface a real problem that passes locally** (`docs/testing.md`). Fix it on the same branch; never skip, disable, or quarantine a test to get green.
- **A merged PR is finished.** Follow-up work goes on a fresh branch from the updated `master`, never on the merged branch.
