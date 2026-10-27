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

## Generalizing lessons in this file

Every rule below started as one specific bug in one specific place. Whoever adds the next one should write it up as the *underlying pattern*,
not just the file where it surfaced, and fold it into an existing entry when it has the same root cause rather than appending a disconnected one.
"After swapping a framework, check what it was installing for you" (below) is the model: it was found once with Flask and `jinja2`, but it applies to any dependency swap.

A problem already found once should not be rediscovered from scratch: that is why "Before you start" says to read the Discussions and the recent review comments first.

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

- **No test needs a secret or a private storage.** `storage_path()` (`python/tests/utils.py`) builds one per test run in a temporary folder: the factory defaults (`hard_reset`) plus the synthetic schedules in `python/tests/fixtures/storage/` (nothing real, no keys). It is **read-only**: a test that writes copies it first (`WebApiTestBase` does), or builds its own with `temp_configuration_manager`. So the suite runs on a fork's pull request, in a cloud session and in the container with nothing to restore. The old `TEST_STORAGE_B64` secret and `prepare-test-data.ps1` are gone (#27).
  A fixture must stay valid for the data sources it names and use only ones the fake internet serves (a playlist track that fails strikes out and the layer tests then see an error). **Tests must not assume `datasources/` or `plugins/` content exists**: the factory storage makes a folder only for what has settings.
- The headless render tests need the headless browser: `chromium-headless-shell` on `PATH` (Linux), `chrome-headless-shell` on `PATH` (Windows), or whatever `EINK_CHROME` names (a path or a name on `PATH`, set in the environment or in a `.env` file at the repository root, see `.env.example`; no machine's path is in the code; `chrome_command()` in `image_utils.py`, read on every render). In the cloud sandbox:
  `ln -s /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell /usr/local/bin/chromium-headless-shell`.
- **No test needs the internet.** `python/tests/__init__.py` makes every `AsyncHttpWorkerPool` talk to `python/tests/fake_internet.py`, which answers the comic feeds, the Wikipedia API and the newspaper covers from text fixtures in `python/tests/fixtures/http/` and generated images (real ones are copyrighted); any other URL is a `ConnectError` naming it. A new download in the code under test needs a route there (and a fixture), not a real request.
  The text fixtures are hand-written in the sites' shapes; `uv run python -m scripts.record_http_fixtures` (needs the internet) replaces them with real answers, and `EINK_TEST_LIVE=1` runs the tests against the real network (the opt-in live check).
- `tkinter` is mocked in `python/tests/__init__.py`. In production it is imported only for the `tk` display, so a missing Tk fails that display and nothing else.
- **Never print, log, or commit the contents of storage files**: they can hold API keys. Inspect them with a command that cannot echo values (key names only), not `cat`.

## Where the work runs: cloud, local, container

The same repo is worked on from three places. The rules above are the same everywhere; only the setup differs.

| | Cloud sandbox (Claude Code on the web) | Local (Windows, Claude Code in the IDE) | Local container (Podman or Docker) |
|---|---|---|---|
| OS | Linux | Windows | Linux, Debian image as CI |
| Headless Chromium | preinstalled; symlink it (see Test environment) | point `EINK_CHROME` in `.env` at a `chrome-headless-shell.exe` (Playwright's, under `%LOCALAPPDATA%\ms-playwright`, will do): then **5 skip**, all POSIX-only or a machine setting (tzset, a drive path, symbolic links); without it the render tests skip too | installed in the image: nothing skips but 3 |
| `gh` / GitHub | needs a valid `GH_TOKEN` with write access to issues, PRs and Discussions; without one, draft session summaries for the maintainer (`SESSION_SUMMARIES.md`) | the maintainer's signed-in `gh`; reads and writes issues, PRs, Discussions | not needed |
| Browser tests | `npx playwright install chromium` (its preinstalled browser may not match) | `npx playwright install chromium` once per Playwright version | not covered; run on the host |
| Shell | bash | PowerShell, or Git Bash for POSIX syntax | bash |

- **A test of process handling fakes the browser portably** (`TestChromeRender._browser` in `test_image_utils.py`, #441): a Python script, made runnable by a shebang on POSIX and a `.cmd` shim on Windows, patched in through `chrome_command` (an `EINK_CHROME` would otherwise win), so the Windows branch (`CREATE_NEW_PROCESS_GROUP`, `taskkill /T`) is tested as well as `killpg`; a render test checks for the browser with `chrome_command()`, never the platform's bare name. A skip on Windows is for what only POSIX has, not for a test written in shell.
- **A Windows run is not the CI run.** The render tests are skipped without a browser, and the POSIX-only tests always. `mypy` is clean on both: **code for one platform branches on `sys.platform`** (`if sys.platform == "win32":`), which the type checker reads and so checks each branch only on its own platform; `platform.system()`, `hasattr` and a skip decorator it cannot read, so they left `os.killpg`, `signal.SIGKILL` and `time.tzset` as errors on Windows (#474). Never reach an attribute through `getattr(obj, "name")` to quiet the checker: narrow the type (`isinstance`, a platform branch) so it knows the attribute is there.
  Before a PR, run `podman compose run --rm test` (the containers, the Pi kit and Podman on Windows are in `docs/containers-and-deploy.md`): it does what `.github/workflows/unittest.yaml` does (`ruff`, `mypy`, `coverage run -m unittest discover .`) on Linux with Chromium.

## Core rules

- Python 3.13, **tabs** for indentation, type hints, `logging` (no `print`), config in JSON. Keep changes focused; do not reformat files you are not changing.
- **The web API.** Endpoints are plain `def` (they run in uvicorn's thread pool; the configuration code is blocking and lock-based), not `async def`.
  Errors are `ApiError(status, message, id)`, and every non-2xx body is `{ success: false, message, id }` (+ `rev` on 409, `errors` on 422). Never put exception text in a response.
- **Settings documents** carry `_id` and `_rev` (a content hash); a `PUT` must echo `_rev` or gets 409. Files are written atomically by `_internal_save`; never write settings files any other way.
  Anything that watches the files must therefore also handle a *move onto* the real file (the watcher reports the destination), not only modifications.
- **IDs from URLs are untrusted.** Plugin and datasource IDs must come from `cm.enum_plugins()` / `cm.enum_datasources()`; never build a path from a raw URL parameter.
  Validating is not enough for the analyser (or a reader): what builds the path must be **our own value** (the constant from our list, the ID declared in the descriptor), not the URL's string that passed a check. Files served for a URL are resolved with `realpath` and must start with the folder's prefix (see `_file_in_bundle`), which also stops symbolic links.
  Error bodies do not echo the URL's text back. CodeQL's `py/path-injection` alerts are about exactly this; fix the flow, do not dismiss the alert.
- **Secrets.** A schema property with `"writeOnly": true` is masked (`********`) in GET responses and kept when the mask, or nothing, is sent back. Mark any new key/token/password property that way.

- **Every file of the storage goes through the configuration manager, by name.** `ConfigurationManager` is the only holder of the storage root; it builds the sub-managers (settings, schedules, plugin, data source) and each gets a **local root** from it: the chain of trust on paths. A caller names a file (`dsm.file("tokens")`, `schedule_manager().read("tasks-x.json")`, `cm.read_schema("theme")`), never a path, and a name is checked to be a leaf (`leaf_name`), so nothing outside a sub-manager's root can be reached. Only `model/storage_files.py` (`save_json`: atomic; `load_json`), `configuration_manager.py` and `schedule_manager.py` open, write or delete files; `test_storage_access` fails on any other module that does (the few non-storage uses are listed in it: render scratch files, `/etc/timezone`, the log configuration, the mock display's output in the system temp folder). **A folder exists because something was written to it:** `save_json` makes the parent folder, a lookup or a read makes none, so a plugin or data source without settings or files has no folder. Folders the **user supplies** (the Image Folder's) are read in place, read-only, and are not storage. The calendar's `tokens.json` was the case that broke the rule (its own `open`, `makedirs`, private save); a new data source that needs a file of its own asks its `DatasourceConfigurationManager`.
- **Plugins and datasources can add API routes:** export an `APIRouter` and name it in the `"router"` entry of the `*-info.json`.
- **Web app.** All backend calls go through `ApiClient` (`apiJson`/`apiPut`); do not call `fetch` directly, since it sends the session cookie, signs in when the server asks, and surfaces the server's message.
- **The browser stores nothing but the theme** (`localStorage`, key `theme-...`); everything else lives on the server, which is trusted. Never put a token, a session, or any other state in `localStorage`, `sessionStorage`, or a script-readable cookie (CodeQL flags it as clear-text storage of sensitive information, and it is not needed).
  The API token is the one case that looks like it needs storage: it is sent once to `POST /api/session`, and the server keeps the session (`python/web/sessions.py`) behind an `HttpOnly`, `SameSite=Strict` cookie. The e2e tests assert that only the theme is stored.
  The cookie is `Secure` only when the app itself sees `https`, which it does when it serves HTTPS itself (`--ssl`); behind a TLS-terminating proxy it would see plain `http` and not mark it (forwarded headers are deliberately not trusted), which is one reason HTTPS is the app's own. There is no rate limiting on `POST /api/session`; that is a documented tradeoff for a home-network device.
- **After swapping a framework or library, check what it was installing for you.** Removing Flask silently removed `jinja2` (and `markupsafe`), which four modules still imported; only the tests noticed.
  Grep the imports against `pyproject.toml` and declare every third-party package you import directly.
  The same goes for the tests: **a test that patches the old name keeps passing without testing anything** once the code makes its object another way (the pool's client became a `MeteredClient`, and two robustness tests still patched `httpx.AsyncClient`: one failed, the other went on passing with no failing client in it). Grep the tests for the old name, and make such a test assert that its stand-in is the one in use.
- **HTML from outside is read with a parser, never searched with a regular expression** (#489). A feed's or an answer's markup goes through `html.parser`: `python/utils/html_text.py` (`html_text`: the text on one line, a block tag a space, scripts and styles not text; `html_images`: each `<img>`'s attributes) or a reader of its own on the same parser (the Comic's `strips.py` reads the text after a marker). The regular expressions they replaced ran paragraphs together, ate a `<` that opened no tag, kept a script's text and skipped an `alt=""`. A comic is a `Comic` record in `strips.py` (its feed, where the HTML is, how the title and caption are read), not code.
- **A text file is opened with `encoding="utf-8"`** (`test_storage_access` checks every `open` of ours that is not binary). The default is the platform's: UTF-8 on a Pi and in CI, cp1252 on Windows, so `load_json` wrote UTF-8 and read a schema's `°C` back as `Â°C` on Windows only. Anything that differs between the device and the development machine (encodings, line endings, paths, the shell) is fixed in the code, never left to the platform.
- **Test an object for `None`, not for truth.** A class with `__len__` is falsy while empty: `if self.sink:` dropped every message to a hub that had no events yet, including the first failure (found building `GET /api/status`). Use `is not None`.
- **A failure's cause is usually in what the change touched indirectly:** the watcher, the CI storage, a transitive dependency. Reproduce under CI conditions before concluding anything.

## Cutting a release

Only when the maintainer asks for one and names the version. **Before touching a version field or pushing a `v*` tag, read `RELEASING.md` in full**: it is the procedure (bump both version fields, verify, audit, merge, try the snapshot on a Pi, tag only on the maintainer's go-ahead for that version, watch `release.yml`, announce). It is kept out of this file because it is needed at one rare moment.

## Boundaries this repo has actually hit

- **A 403 on push means GitHub access is not connected for the session.** Stop and tell the maintainer; do not look for a way around it. Repository settings, secrets, and branch protection need the maintainer's explicit go-ahead for that specific change.
- **A PR's own CI can surface a real problem that passes locally** (the CI storage above). Fix it on the same branch; never skip, disable, or quarantine a test to get green.
- **A merged PR is finished.** Follow-up work goes on a fresh branch from the updated `master`, never on the merged branch.
