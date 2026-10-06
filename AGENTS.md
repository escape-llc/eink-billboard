# Working on eInk Billboard

This file is for whoever (human or AI) is working **on** this repo. `CLAUDE.md` only imports it, so every agent reads the same rules.
The readme explains the architecture (layers, compositor, tasks, storage); this file is the working agreement.
Process lives in its own docs, indexed in `CONTRIBUTING.md`: **`WORKFLOW.md`** (idea to merged) and **`SESSION_SUMMARIES.md`** (how a piece of work is written up afterwards).

## What this is

An e-Ink "billboard" server for Raspberry Pi (and Windows/Linux development): a Python task-based backend (threads + `asyncio`),
a FastAPI web API, and a Vue 3 / PrimeVue settings app. It is developed on Windows and Linux; keep both working.

## Generalizing lessons in this file

Every rule below started as one specific bug in one specific place. Whoever adds the next one should write it up as the *underlying pattern*,
not just the file where it surfaced, and fold it into an existing entry when it has the same root cause rather than appending a disconnected one.
"After swapping a framework, check what it was installing for you" (below) is the model: it was found once with Flask and `jinja2`, but it applies to any dependency swap.

Before starting anything beyond a trivial change, read the last several posts of the Discussions category the session summaries go to (see `SESSION_SUMMARIES.md`)
and skim the most recent merged PRs for review comments nobody answered. A problem already found once should not be rediscovered from scratch.

## Layout

| Path | What |
|---|---|
| `python/eink-billboard.py` | Entry point (`main()`), starts the `Application` task and uvicorn |
| `python/web/` | FastAPI app: `app.py` (factory), `deps.py`, `errors.py`, `documents.py`, `routers/` |
| `python/task/` | Control plane: `Application`, `Display`, `PlaylistLayer`, `TimerLayer`, timers, message routing |
| `python/model/` | Configuration manager/watcher, schedules, time of day, service container |
| `python/datasources/`, `python/plugins/` | Each folder has a `*-info.json` descriptor (id, class, settings schema, optional `router`) |
| `python/storage/` | NVE ("factory default") schemas copied into the storage root on reset |
| `python/tests/` | `unittest` tests; `.storage/` inside is **gitignored** test data |
| `app/` | Vue web app (`npm`, Vite). Talks to the API through `src/components/ApiClient.ts` |

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
cd app && npm run e2e                      # build, then the browser tests (Playwright) against two real servers
```

- `npm run build` runs `vue-tsc -b` first, which reports **zero** errors; keep it that way (a type error fails the build).
- The built app uses hash routes (`/#/settings`), and Vite's default layout: `index.html` and `public/` files at the root, bundles in `assets/`.
- **Browser tests** (`app/e2e/`, Playwright Test): `playwright.config.ts` starts two real servers on a storage built by `scripts/e2e_storage.py` (the factory defaults plus the **synthetic** fixtures in `app/e2e/fixtures/storage`: schedules, a system settings file, a fake API key).
  No secret and none of the real test storage is involved, so they run on fork PRs. One server is open (port 8099), one requires a token (8098, `e2e-token`). They need `uv sync` and, once, `npx playwright install chromium`; in the cloud sandbox the browser is already installed and `@playwright/test` is pinned (`~1.56.1`) to match it.
  `watchProblems()` in `e2e/support.ts` fails a test on any page error, console error, failed request, or HTTP error that the test did not declare, so a page that merely renders is not enough.
  Gotchas: the app uses hash routes (`/#/settings`); PrimeVue option accessible names are not their text, so match options by visible text; the factory `location: null` leaves Save disabled, so the fixture sets one.
- CI: `.github/workflows/web.yaml` runs the `web` job (build, unit tests) and the `e2e` job (browser tests) on pull requests and pushes to `master`. They are not required checks until the maintainer adds them to the ruleset.
- Options: `--port` (default 8080 with `--dev`, else 80), `--token` or `EINK_API_TOKEN` (Bearer token on `/api`), `--app` (web bundle folder).
- Do not start the server with `pkill -f`/`pgrep -f` patterns that match your own shell command; start it in the background, record its PID, and signal that PID
  (`uv run` is a wrapper: signal the Python child, not the `uv` process).

## Test environment

- `python/tests/.storage/` must exist and is **never committed**. CI rebuilds it from the `TEST_STORAGE_B64` secret (see `prepare-test-data.ps1`, which excludes `datasources/` and `plugins/`).
  It needs at least `schedules/`, `schemas/`, `settings/`.
  **Tests must not assume `datasources/` or `plugins/` content exists; create what you need.** A test that passed locally against a full storage failed CI for exactly this reason (the first run of PR #19).
  API tests work on a temp copy (`WebApiTestBase`) and never modify the original.
  To reproduce CI locally, move `datasources/` and `plugins/` out of `python/tests/.storage/` and run the tests, then put them back.
- The headless render tests need `chromium-headless-shell` on `PATH`. In the cloud sandbox:
  `ln -s /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell /usr/local/bin/chromium-headless-shell`.
- Several tests call the internet (comic, newspaper, Wikipedia, the slide-show variants, the layer simulations); they fail where outbound access is restricted.
  Record which ones fail **before** your change and compare, rather than assuming a failure is yours (or not yours).
- `tkinter` is mocked in `python/tests/__init__.py`. In production it is imported only for the `tk` display, so a missing Tk fails that display and nothing else.
- **Never print, log, or commit the contents of storage files**: they can hold API keys. Inspect them with a command that cannot echo values (key names only), not `cat`.

## Core rules

- Python 3.13, **tabs** for indentation, type hints, `logging` (no `print`), config in JSON. Keep changes focused; do not reformat files you are not changing.
- **The web API.** Endpoints are plain `def` (they run in uvicorn's thread pool; the configuration code is blocking and lock-based), not `async def`.
  Errors are `ApiError(status, message, id)`, and every non-2xx body is `{ success: false, message, id }` (+ `rev` on 409, `errors` on 422). Never put exception text in a response.
- **Settings documents** carry `_id` and `_rev` (a content hash); a `PUT` must echo `_rev` or gets 409. Files are written atomically by `_internal_save`; never write settings files any other way.
  Anything that watches the files must therefore also handle a *move onto* the real file (the watcher reports the destination), not only modifications.
- **IDs from URLs are untrusted.** Plugin and datasource IDs must come from `cm.enum_plugins()` / `cm.enum_datasources()`; never build a path from a raw URL parameter.
  Validating is not enough for the analyser (or a reader): what builds the path must be **our own value** (the constant from our list, the ID declared in the descriptor), not the URL's string that passed a check. Files served for a URL are resolved with `realpath` and must start with the folder's prefix (see `_file_in_bundle`), which also stops symbolic links.
  Error bodies do not echo the URL's text back. CodeQL's `py/path-injection` alerts are about exactly this; fix the flow, do not dismiss the alert.
- **Secrets.** A schema property with `"secret": true` is masked (`********`) in GET responses and kept when the mask, or nothing, is sent back. Mark any new key/token/password property that way.
- **Form field rules are written twice and must agree.** The form (`app/src/components/FormValidation.ts`) and the server (`validate_properties` in `python/web/documents.py`) apply the same rules to a descriptor's properties; the cases both must pass are in `python/tests/form_rules.json` (run by Vitest and by `test_web_api`). Change a rule in both places and add a case.

  | Property | Rule (message) |
  |---|---|
  | `required: true` | not null / not empty ("Required"). Optional properties may be `null` (unset) |
  | `string` | with `enum`, or an `items` lookup: one of the values ("Not one of the allowed values"); a URL lookup is not checked |
  | `number`, `int` | `min` / `max` inclusive, **including 0** ("Minimum N", "Maximum N"); `int` has no fraction ("Whole numbers only") |
  | `date` | `YYYY-MM-DD`, a real day ("Expected a date (YYYY-MM-DD)") |
  | `location` | `{latitude -90..90, longitude -180..180}` |
  | `schema` | a string; the form also checks it is one of the available plugins/datasources |
  | `header` | no value, never validated |
| `description` | shown under the field as help text (any property) |

  **Conditional visibility.** A property may carry `visibleIf`, a predicate over the other fields' values (`app/src/components/FormVisibility.ts`, `python/web/visibility.py`, cases in `python/tests/form_visibility.json`):
  `{ "field": "x", "eq" | "ne" | "in" | "set": ... }`, combined with `all` / `any` / `not`. Names are the form's field names (children of a `schema` field share them); unset (missing, `null`, `""`) reads as `null`.
  A hidden field is not applicable: it is not validated (a hidden `required` does not block) and is **saved as `null`**, by the form and again by the server. `test_web_api` checks every descriptor's `visibleIf` for unknown fields and cycles.
  The server's 422 body lists `errors: [{ path: [name], message }]`. Use PrimeVue components for every control the form renders (`DatePicker`, `InputNumber`, `Select`, ...).
- **Plugins and datasources can add API routes:** export an `APIRouter` and name it in the `"router"` entry of the `*-info.json`.
- **Web app.** All backend calls go through `ApiClient` (`apiJson`/`apiPut`); do not call `fetch` directly, since it sends the session cookie, signs in when the server asks, and surfaces the server's message.
- **The browser stores nothing but the theme** (`localStorage`, key `theme-...`); everything else lives on the server, which is trusted. Never put a token, a session, or any other state in `localStorage`, `sessionStorage`, or a script-readable cookie (CodeQL flags it as clear-text storage of sensitive information, and it is not needed).
  The API token is the one case that looks like it needs storage: it is sent once to `POST /api/session`, and the server keeps the session (`python/web/sessions.py`) behind an `HttpOnly`, `SameSite=Strict` cookie. The e2e tests assert that only the theme is stored.
- **After swapping a framework or library, check what it was installing for you.** Removing Flask silently removed `jinja2` (and `markupsafe`), which four modules still imported; only the tests noticed.
  Grep the imports against `pyproject.toml` and declare every third-party package you import directly.
- **A failure's cause is usually in what the change touched indirectly:** the watcher, the CI storage, a transitive dependency. Reproduce under CI conditions before concluding anything.

## Boundaries this repo has actually hit

- **A 403 on push means GitHub access is not connected for the session.** Stop and tell the maintainer; do not look for a way around it. Repository settings, secrets, and branch protection need the maintainer's explicit go-ahead for that specific change.
- **A PR's own CI can surface a real problem that passes locally** (the CI storage above). Fix it on the same branch; never skip, disable, or quarantine a test to get green.
- **A merged PR is finished.** Follow-up work goes on a fresh branch from the updated `master`, never on the merged branch.
