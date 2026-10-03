# eInk Billboard: guide for Claude and other agents

An e-Ink "billboard" server for Raspberry Pi (and Windows/Linux development): Python task-based backend (threads + `asyncio`),
FastAPI web API, and a Vue 3 / PrimeVue settings app. The readme explains the architecture (layers, compositor, tasks, storage); this file is the working agreement.

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

cd app && npx vite build                   # production bundle -> app/dist (served with --app)
```

Notes:
- `npm run build` runs `vue-tsc` first and currently fails on about 32 pre-existing type errors; use `npx vite build`, and do not add new type errors (compare `npx vue-tsc -b` before/after).
- Options: `--port` (default 8080 with `--dev`, else 80), `--token` or `EINK_API_TOKEN` (Bearer token on `/api`), `--app` (web bundle folder).

## Test environment

- `python/tests/.storage/` must exist and is **never committed**. CI rebuilds it from the `TEST_STORAGE_B64` secret (see `prepare-test-data.ps1`, which excludes `datasources/` and `plugins/`). It needs at least `schedules/`, `schemas/`, `settings/`.
  So: tests must not assume `datasources/` or `plugins/` content exists; create what you need. API tests work on a temp copy (`WebApiTestBase`) and never modify the original.
- The headless render tests need `chromium-headless-shell` on `PATH`. In the cloud sandbox: `ln -s /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell /usr/local/bin/chromium-headless-shell`.
- Several tests call the internet (comic, newspaper, Wikipedia, slide-show variants and the layer simulations); they fail where outbound access is restricted. Note which ones failed before your change and compare, rather than assuming a failure is yours.
- `tkinter` is mocked in `python/tests/__init__.py`. In production it is imported only for the `tk` display.
- Never print, log or commit the contents of storage files: they can hold API keys.

## Conventions

- Python 3.13, **tabs** for indentation, type hints, `logging` (no `print`), config in JSON.
- The web API: endpoints are plain `def` (run in uvicorn's thread pool; the configuration code is blocking and lock-based), not `async def`.
  Errors are `ApiError(status, message, id)`; every non-2xx body is `{ success: false, message, id }` (+ `rev` on 409, `errors` on 422). Never put exception text in a response.
- Settings documents carry `_id` and `_rev` (content hash); a `PUT` must echo `_rev` or gets 409. Files are written atomically (`_internal_save`); do not write settings files any other way.
- Plugin/datasource IDs in URLs must come from `cm.enum_plugins()` / `cm.enum_datasources()`; never build a path from a raw URL parameter.
- A schema property with `"secret": true` is masked (`********`) in GET responses and kept when the mask or nothing is sent back.
- A plugin or datasource can add API routes: export an `APIRouter` and name it in the `"router"` entry of its `*-info.json`.
- Web app: all backend calls go through `ApiClient` (`apiJson`/`apiPut`); do not call `fetch` directly (it adds the token and surfaces server messages).
- Keep changes focused; do not reformat files you are not changing.

## Pull request workflow

1. **Branch.** Never commit to `master`. Work on the branch you were given (agents: `claude/<name>`); create it from the latest `master`.
2. **Before pushing.** Run the Python tests (at least the ones you touched plus `test_web_api`), and for web changes `npx vite build` and the `vue-tsc` comparison above. Re-read your own diff.
   Confirm no storage files, keys, `dist/`, or `node_modules` are staged (`git diff --cached --name-only`).
3. **Commit.** Imperative subject line, body explaining *why*. Agents end commits with the attribution trailers they were given.
4. **Push** with `git push -u origin <branch>`. A 403 means GitHub access is not connected for the session: stop and tell the user, do not look for a way around it.
5. **Open a PR to `master` only when the user asks** (or asks to merge). There is no PR template; use a short Summary and a Testing section that states what was and was not run. Reference issues and PRs as `owner/repo#N`.
6. **CI** (`CI Tests (uv + Container)`, the `unittest` job) runs on every push and PR and must be green before merging. If it is red, read the job log, reproduce it locally under CI conditions (see Test environment), fix it, and push. Do not skip, disable or quarantine a test.
   CodeQL also runs on PRs to `master`.
7. **Merge** only when the user has asked for it, CI is green, and there are no unresolved review threads. A merged PR is finished: follow-up work goes on a fresh branch from the updated `master`, never on the merged branch.
8. **After merging**, post an announcement for notable changes (see below) and tell the user what was merged.

## GitHub Discussion post

For user-visible or architectural changes, finish the workflow with a short post in the repository's **Announcements** discussion category. Agents without a tool that can create discussions must draft the text and give it to the user to publish; never publish on their behalf without being asked.

Template:

```
Title: <what changed, in one line>

**What changed**
<2-4 bullets, user-facing first>

**Why**
<the problem this solves>

**What you need to do**
<upgrade steps, new options or environment variables, or "nothing">

**Notes**
<known limitations, follow-ups, link to the merged PR as owner/repo#N>
```

Keep it factual, no secrets or internal paths, and say plainly what was not tested.
