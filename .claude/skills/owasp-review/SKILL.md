---
name: owasp-review
description: Audit the eInk Billboard codebase against the OWASP Top 10 (broken access control, injection and XSS, security misconfiguration, vulnerable components, integrity, SSRF, secret handling) across the web API, the task layers, the model, the data sources and plugins, and the Vue app. Not scoped to a diff. Use when asked for an OWASP or security audit, or "how exposed is the device on the network".
---

# OWASP Top 10 audit: whole codebase, by area

eInk Billboard is a **device on a home network**: a Python backend (threads and `asyncio`), a FastAPI web API with an optional Bearer token and a cookie session, a WebSocket (telemetry), a Vue 3 app, plugins and data sources that fetch from the internet, and pages rendered by headless Chromium. The trust model is in `AGENTS.md` (read "Core rules" first): IDs from URLs are untrusted, secrets are `writeOnly`, no exception text leaves the device (loopback excepted), every file goes through the configuration manager, the browser stores nothing but the theme.

Verify every claim against the **current** source before reporting it: grep, read the real call site, then decide. Quote `file:line`. Distinguish a **confirmed, exploitable** issue from a **theoretical** one (CONFIRMED / PLAUSIBLE); do not inflate a defense-in-depth idea into a vulnerability. The whole repository is in scope, tests and scripts included, where they parse untrusted input and reach a sensitive sink (a path, a shell, a network target).

## Areas (audit one at a time, or all)

1. **Web API** (`python/web/`): routers, `deps.py`, `errors.py`, `documents.py`, sessions.
2. **Task layer** (`python/task/`): messages, telemetry hub, error pages.
3. **Model** (`python/model/`): configuration manager, schedule store, watcher, theme.
4. **Data sources and plugins** (`python/datasources/`, `python/plugins/`, `python/utils/`): everything that fetches, parses or renders external content.
5. **Web app** (`app/src/`): the API client, forms, anything rendering a server or remote string.

## Categories and what to check here

**A01 Broken access control**
- Every router is under the token dependency except the documented exceptions (`/api/session`, the telemetry WebSocket that checks for itself). `grep -n "include_router\|APIRouter" python/web`, then confirm no route can be reached without `require_token` when a token is configured.
- The WebSocket: session or Bearer checked, `Origin` checked (4401 / 4403). A new WebSocket or SSE route needs the same.
- `detail` in telemetry is sent only for a loopback connection (`_on_device`); confirm no other route echoes it and that forwarded headers are still not trusted.
- IDs from URLs: plugin and data source IDs come from `enum_plugins()` / `enum_datasources()`; a file name is built from our own value. Any new `{id}` path parameter that reaches a path or a lookup is a finding until proven otherwise.

**A02 Cryptographic failures and secret handling**
- `writeOnly` properties are masked in every GET and in telemetry, logs and error pages. `grep -rn "apiKey\|password\|token\|secret"` in routers, logs and error text. A key in a URL (OpenWeatherMap's `appid`) must not reach a log line (`HideKey` in `weather.py`); check the same for any new source.
- Session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` only when the app sees https; token compare is `hmac.compare_digest`.
- The OAuth token file (`tokens.json`) is never served by a settings route.

**A03 Injection and XSS**
- Jinja templates for rendered pages (`render/*.html`): autoescape is on; flag any `| safe` fed from data that is not our own markup (glyph SVGs from `stat_svg` and icons are ours; an event title, a feed item or a calendar string is not).
- Page CSS and inline `style=` built from settings or remote values (colors, fonts): colors pass `safe_color` / the `color` format; family names come from `FONT_FAMILIES`.
- Vue: `grep -rn "v-html\|innerHTML" app/src`; any hit must be a static or sanitized string. Links from descriptors (`link`) are https only (`safeLink`).
- Command and SQL: there is no database; `grep -rn "subprocess\|os.system\|shell=True\|eval(\|exec(" python` and read each hit (the Chromium launch in `image_utils.py`: arguments are ours, never a setting).
- Deserialization: `grep -rn "pickle\|yaml.load\|marshal"`; XML (CalDAV) goes through `xml.etree` after the size cap.

**A04 Insecure design / path handling**
- Everything that builds a path: `test_storage_access` enforces that only the configuration manager opens files; check `leaf_name`, `_file_in_bundle`, `realpath` prefix checks in `fonts.py`, `lookups.py`, plugin/datasource static routes, and the Image Folder (user paths are read in place, read-only; confirm a task cannot name a path outside the folders in the settings).

**A05 Security misconfiguration**
- CORS: `--cors` only an explicit origin, never `*` with credentials. Default binding and the compose port (`127.0.0.1`). The no-token warning when bound to the network.
- Error bodies: `{ success, message, id }` with no exception text, no path, no URL.
- Dev switches (`--dev`) cannot weaken auth in a production start.
- Docker: no secrets in the image (`.dockerignore`), non-root where practical.

**A06 Vulnerable and outdated components**
- `uv run pip-audit` and `cd app && npm audit`. Note held-back majors (PrimeVue 5, TypeScript 7) and why.

**A07 Authentication failures**
- `POST /api/session`: constant-time compare; no rate limit is a documented tradeoff for a home device, state it, do not report it again as new.
- Sessions expire or are bounded; a session cannot be fixed by the client.

**A08 Software and data integrity**
- Workflows: run the `actions-injection-review` skill.
- Plugins and data sources are code in the repo (no dynamic loading from storage): confirm `load_routers` and the descriptor `module` / `file` fields cannot name something outside `python/`.
- Settings documents are validated by the same rules on both sides before saving.

**A09 Logging and monitoring**
- Logs hold no secrets or tokens; the telemetry ring holds only JSON scalars and our own sentences (`safe_reason`).

**A10 SSRF**
- Every outbound fetch whose address comes from a setting or a task: `grep -rn "httpx\|fetch_checked\|AsyncHttpWorkerPool"`. A user-supplied address (RSS feed, CalDAV or iCal URL, the Test buttons) must go through `python/utils/url_guard.py` (http(s) only, no loopback, link-local, unspecified, multicast or reserved; each redirect checked). Known gap: DNS rebinding. A source with a fixed host (OpenWeatherMap, Wikipedia, comics) is fine.
- CodeQL's `py/full-ssrf` alert on `url_guard.py` is expected to be a false positive: the file is the guard. Confirm it is dismissed with that reason.

## Reporting

- Per finding: category, `file:line`, a concrete exploit scenario (the request, the setting value, the page), CONFIRMED or PLAUSIBLE, and the smallest fix. File each real finding as its own issue with the `security` label and fix it through the normal branch and PR cycle; a vulnerability that is already exploitable on a default install is reported to the maintainer first, not discussed in a public issue.
- End with a per-category and per-area status table: Assessed/Clean, Assessed/Finding(s), or Out of scope (with the reason). Nothing falls through silently.
- Never put a secret, a token or the contents of a storage file in the report.
