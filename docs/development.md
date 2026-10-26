# Development

Working on the code: running it locally and in containers, the web API, API metering, telemetry and debugging. The working agreement is [AGENTS.md](../AGENTS.md).

How to use the app (the pages, each data source's settings, the calendar sign-ins, the keys) is in the web app's **Help** drawer (`app/src/components/HelpDrawer.vue`), not here; installing a Pi is in the [readme](../readme.md).

## Kept Downloads

A data source that downloads the same thing again and again calls `download_for` (`python/datasources/content_cache.py`) instead of `stream_to_buffer`. What is kept belongs to the data source: one pool in its own folder (`blob-<hash of the address>.json` describes a download, `.bin` is its bytes; the address, which can carry a key, is in neither, and neither is in a backup). `Cache-Control` and `Expires` can shorten `contentCacheHours`, never lengthen it; a fresh download sends nothing, an expired one is asked for with `If-None-Match` / `If-Modified-Since`; the pool is bounded by `contentCacheMB` and tidied by `staleDays` and `retain(scope, urls)`. The settings are explained in the Help drawer.

## Storage Folder

You must set up a separate `.storage` folder for the application to store its state: see [Storage Architecture](architecture.md#storage-architecture).

## Run

Use the following recipe to get started with development (to run it on a Raspberry Pi, see [Set up a Raspberry Pi](../readme.md#set-up-a-raspberry-pi)):

* New Terminal 1
* `python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ./.storage`
* New Terminal 2
* `cd app && npm run dev`

The web app finds the server through `VITE_API_URL`: `http://localhost:8080/` in development (`app/.env.development`, the recipe above) and `/` in the built app, which the server serves itself (`app/.env.production`). Copy `app/.env.example` to `app/.env.local` to change it for yourself; a trailing slash is expected.

## Containers

The same checks CI runs, and the app itself, run in a container with Podman or Docker (`Dockerfile`, `compose.yaml`; with Docker, `docker compose` in place of `podman compose`):

```
podman compose run --rm test                         # ruff, mypy and the unit tests on Linux with Chromium, against your checkout
podman compose up --build app                        # the web app and API on http://localhost:8080, storage in a named volume
EINK_STORAGE=./.storage podman compose up --build -d app   # the same, on that folder of the checkout
podman compose --profile inky up --build -d app-inky       # with the Inky driver installed, on :8081
podman compose --profile waveshare up --build -d app-waveshare   # with the Waveshare drivers, on :8082
```

* `test` mounts the checkout, so an untracked file of yours is checked too; its virtual environment is `/opt/venv`, never your `.venv`. Run it before a pull request: a Windows run skips the render tests and reports POSIX-only calls in `mypy`.
* The `app` image has no display drivers; the `inky` and `waveshare` profiles do, with a storage of their own, and `EINK_FAKE_INKY` / `EINK_FAKE_WAVESHARE` (`ok`, `busy-stuck`, `spi-off`, and `unknown-board` for the Inky) pretend a board is attached (see the Display Task).
* The port is published on `127.0.0.1` only; set `EINK_API_TOKEN` before widening it. A Windows folder mounted into the container sends no file change events, so compose sets `EINK_WATCH_POLL=2` (seconds).
* **Podman on Windows** needs WSL 3.0 or later and Podman 6.1 or later (`wsl --version`, `podman version`); after upgrading Podman, recreate the machine (`podman machine rm`, `podman machine init --rootful`, `podman machine start`).

## Web API

* The API is under `/api`; interactive documentation is served at `/api/docs`.
* The OpenAPI document is also committed as `app/src/api/openapi.json`, and the web app's types (`app/src/api/schema.d.ts`) are generated from it: after changing a route or its models, run `cd app && npm run api` and commit both files (a Python and a Vitest test fail on a stale one). The web app calls typed routes through `api` in `app/src/api/client.ts`.
* Every error response has the same body: `{ "success": false, "message": "...", "id": "..." }` (plus `rev` on a `409` revision conflict, and `errors` on a `422` validation failure).
* Settings documents carry `_id` and `_rev`. A `PUT` must send back the `_rev` it loaded; if the settings changed in the meantime the server answers `409` with the current `rev`.
* Settings the schema marks `"writeOnly": true` (e.g. an API key) are returned as `********`. Sending `********` back, or omitting the field, keeps the stored value.
* **A new device is claimed, not given a default password.** Listening on the network (the default), it starts unclaimed: every `/api` route answers 401 with `setup: true` until someone enters the one-time **setup code**, which is in the log and on the e-Ink panel (`deploy/eink-container.sh code` on a Pi), and chooses the device password (at least 8 characters). `--host localhost` stays open until a password is set. `--no-auth` keeps a device open on a network you trust; `--require-auth` asks even on `localhost`; `python -m python.eink-billboard --reset-password` forgets the password (console access is ownership). Below, the API token is the credential for scripts.
* Set `--token <value>` (or the `EINK_API_TOKEN` environment variable) to require `Authorization: Bearer <value>` on every `/api` request. The web app asks for the token the first time it gets a `401` and sends it once to `POST /api/session`; the server remembers the sign-in in memory (a restart signs everyone out; sessions last seven days) and the browser keeps only an `HttpOnly`, `SameSite=Strict` cookie that scripts cannot read. The browser stores nothing else but the theme. `DELETE /api/session` signs out. A client that gets the token wrong more than three times in a row is told to wait (429, `Retry-After`; 2 s, doubling, at most 5 minutes) and each failure is logged with the client's address. The server answers only to `localhost`, IP addresses, the machine's own name and `<name>.local`; a device reached by another name needs `--allow-host <name>` (or `EINK_ALLOW_HOSTS`), otherwise the request is refused with 421 (a defence against DNS rebinding). Scripts can keep sending `Authorization: Bearer <value>`. Do this whenever the server listens on a network you do not fully trust. Behind a TLS-terminating proxy the app sees plain `http`, so the session cookie is not marked `Secure` (forwarded headers are not trusted); `/api/docs` and `/api/openapi.json` require the token like the rest of `/api`.
* `--port` overrides the listening port (default `8080` with `--dev`, otherwise `80`).
* **HTTPS is uvicorn's own** (`python/web/https.py`): `--ssl` (or `EINK_SSL=1`) serves HTTPS on the same port, with `--ssl-certfile` and `--ssl-keyfile` (or `EINK_SSL_CERTFILE`, `EINK_SSL_KEYFILE`: PEM, the key without a passphrase) or, without them, the device's own self-signed certificate (`python/utils/tls_certificate.py`: EC P-256, 397 days, for `localhost`, `127.0.0.1`, `::1`, the machine's name, `<name>.local`, its address, the public address and the allowed hosts), kept in the storage's `tls/` folder and made again when a name is missing or it is within 30 days of its end. The log names which and gives the SHA-256 fingerprint. A certificate that cannot be used stops the start (our words, never OpenSSL's): asked for HTTPS, the device never serves plain HTTP. The `tls/` folder is the device's own bookkeeping, like `state/`: not in a backup, not announced. Over HTTPS the session cookie is `Secure`. On a Pi, `deploy/eink-container.sh ssl` turns it on and mounts a certificate of one's own as Podman secrets; `deploy/test/ssl.sh` tests that in a Bookworm container.
* Plugins and datasources may contribute an API router; name it in the `"router"` entry of their `*-info.json`.
* **Push a message or a picture to the panel**, from a script (Home Assistant, cron, CI, a doorbell): it is shown over everything for a few minutes (a priority image), then the playlist is back. It needs the same sign-in as the rest of the API (the `--token` works for scripts) and a device that has been claimed (403 before that).
  * `POST /api/display/message` with `{ "text": "...", "title": "...", "minutes": 5 }` (`text` 1 to 1000 characters, line breaks kept; `title` optional, up to 80; `minutes` 1 to 60, default 5) makes a page in the device theme: `curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"Doorbell","text":"Someone is at the door","minutes":2}' http://pi.local:8080/api/display/message`.
  * `POST /api/display/image?title=...&minutes=...` takes the picture itself as the body (PNG, JPEG, GIF or WEBP, at most 10 MB and 40 million pixels; checked by its content, only the first frame of an animation, a phone's rotation applied) and shows it whole on a blurred margin of its own colors: `curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: image/jpeg" --data-binary @door.jpg "http://pi.local:8080/api/display/image?minutes=2"`.
  * Both answer `{ "success": true, "id": "...", "title": "...", "startsInSeconds": n }`: `startsInSeconds` is the least it waits (the panel's rest after its last refresh, and the commit timer); messages queue behind each other. `DELETE /api/display/message/{id}` takes one down, showing or waiting (404 when there is none: never made, or over). Twenty messages may be waiting or showing at once (429 beyond that). A title that is already about gets ` (2)`, ` (3)`, since the title is what takes a message down.

* **Backup and Restore** (the System page toolbar: Back up and Restore each open a dialog). `POST /api/backup` with `{ "passphrase": "...", "confirm": "..." }` answers the storage as one file (`application/octet-stream`, `Cache-Control: no-store`); `POST /api/restore` with `{ "archive": "<base64 of the file>", "passphrase": "...", "apply": false }` says what would change, and with `"apply": true` writes it. Both need a **claimed** device (403 otherwise) and the usual sign-in.
  * The file is a ZIP of the storage's JSON files (`settings/`, `schedules/`, `plugins/<id>/`, `datasources/<id>/`: the settings with their API keys, the schedules, OAuth tokens, a Slide Show's kept lists), **encrypted as one blob** so even the file names are hidden: AES-256-GCM, the key made from the passphrase by scrypt (N 2^15), the header authenticated. The passphrase is its own (12 to 256 characters, typed twice): **not the device password** (a password reset would make the backup unreadable), and kept nowhere. A wrong passphrase and a damaged file give the same answer (403).
  * **Never in it:** the device password (the `access` settings: a restore does not change who owns the device), the `schemas` (the code refreshes them), the panel's `state` (when it was last refreshed: it describes *this* panel) and the OpenWeatherMap/Calendar/... kept answers (`cache-*`).
  * A restore opens the file (at most 8 MB, 500 files, 32 MB unpacked, no absolute, `..` or backslash names, no links; sizes are counted as the bytes come out, never believed from the ZIP's header), checks **every document by the rules of the route that would have saved it** (a missing required value is not a reason to refuse: a device keeps an API key that is not typed in yet), and with any problem refuses the whole restore naming the file and field (`errors`, never a value). **Each document is brought up to this version first** (`migrate`, the same function the start uses: see "Versions of stored documents"), so an old backup restores current-shaped; a document from a **newer** version refuses the whole restore, naming the file. The archive carries a `MANIFEST.json` (its format, when it was made, the version each file carried); a format newer than this version refuses, a backup without one (an earlier release's) restores as before, and the preview says when it was made and how many files are upgraded. A plugin or data source this device does not have is left out and counted. Without `apply` nothing is written and the answer is the summary: each file that is new or would change, by name and kind, and how many are the same. With it, the files are written (each atomically, by name through the configuration manager); if one fails the files written before it are put back, and **nothing is ever deleted**. See "Restoring a backup" under the Application Task for the notices.
  * The files are read while the device runs: each is whole, the set is not a point-in-time snapshot. A wrong passphrase counts against the sign-in throttle (429 after a few).

## API Metering

An API data source makes its HTTP client with `metered_client("<the descriptor's id>", ...)` (`python/datasources/metering.py`), which counts every call it sends (each redirect hop and SDK retry included): per data source and per day, the calls by exact status or `timeout` / `connect` / `tls` / `error`, the body bytes each way, and the cache outcomes `cached` and `fetch_cached` report (`hit`, `miss`, `stale`, `coalesced`, `revalidated`, `bypass`). Counts only: never an address, a key, a query or a body. They are kept in memory behind a lock and written to `state/api-usage.json` (versioned, 31 days, not in a backup) about once a minute and on quit. Downloads through the shared pool count too: the pool's client is metered with no source, and `download_for` names the source for the download (`metered_as`). `test_api_metering` fails for an API data source that makes its client any other way. Not built: a quota that stops calls, and the cost of the AI sources.

## System page and Telemetry
The web app's **System** page (what it shows is in the Help drawer) reads `GET /api/status` and `GET /api/system` every 10 s, both numbers and our own words only (no host name, address, user or path), and follows the device live through the telemetry link. Its playback button follows the playlist layer's own `transport` events and asks `GET /api/transport` when the page opens or the link comes back, so a page opened while playback is stopped shows it stopped.

The web app opens one WebSocket for the whole page (`/api/telemetry/ws?since=<seq>&run=<run>`, `App.vue`; the System page follows it and leaving the page leaves it open), which reconnects on its own and resumes after the last event it had. `seq` starts again at every start of the device, so the link's first message, `hello`, names the run (and the newest `seq`: the events up to it that follow are the kept history, which the cache below does not act on): a page that followed another run gets everything kept and starts over. The link starts once the page's first request has been answered (a WebSocket cannot ask for a sign-in), and after a sign-in the page loads again. Times are the device's, not the browser's.

The link also keeps the page's data current. The answers of the API's GET routes are kept once for every view (`app/src/api/resources.ts`, Pinia Colada, keyed by the route's path), and an event that carries `changed` (a `config-changed`, a restore) marks the answers those paths cover as stale: what is shown is asked for again, the rest when it is next used. A `gap`, the link coming back after it was down and a new run mark everything stale. An answer is used for 30 s without asking, which bounds only what a page misses while its link is down. What is kept that way so far: the lists of what is installed (`useCatalog`) and the forms' lookups. The other routes:
* `GET /api/telemetry?since=<seq>`: the kept events, the last 200, newest last;
* a failure's event also carries `detail`, the exception in full, but only for a page opened on the device itself (`localhost`: the connection's address is loopback); to anyone else it is left out, since the text can hold an address with a key. In a container the published port does not look local, so read the log there;
* `GET /api/transport` / `POST /api/transport`: whether playback is stopped (`{ stopped }`) and `{ command: play | stop | next }` for the Playlist Layer. The command is accepted, not done: the layer does it on its own thread and reports a `transport` event; 503 before the application has started;
* `GET /api/status`: how bringing up the display and the two layers went, `{ ok, components: { display | playlist-layer | timer-layer: { state: ok | failed | starting, message } } }`, in our words (a failure says to see the log); the System page reads it every 10 s. A failed display is not retried when its settings change (live reconfiguration is not built): fix the settings and restart;
* `POST /api/system/locate`: the Location field's **Locate by IP** button: a rough position (about the city) from the device's public IP address, `{ ok, message, latitude?, longitude? }`, always 200 and in our words. The device asks ipapi.co (a fixed host, no key; the service sees the device's public address, and the button's tooltip says so) and **nothing is saved**: the button only fills the field, and the person saves or not. The free tier is limited per day; a refusal says so.
* `GET /api/system`: `{ host, load, pi, storage, usage }` for the System page (`usage` is the API metering below) (`pi` is `null` unless the machine is a Raspberry Pi); needs the same sign-in as the rest of `/api`;
* `GET /api/credits`: `{ data, fonts, software }` for the **Credits** section of the Help drawer: each provider's and data source's `credit` from its descriptor (`text`, `license?`, `url?`, by name), the fonts we ship with their authors, and the other software by others (`python/web/credits.py`).
* `GET /api/display/current`: the last `shown` event;
* `GET /api/display/images/<digest>?size=thumb|full`: a shown image as PNG. The device keeps the last 8, in memory only.

An event is `{ seq, ts, source, kind, message?, values }`:

| source | kinds |
|---|---|
| `playlist_layer` | `track-started`, `track-ended` (a track whose slot shows an error page is started and ended like any other, with `track-failed` between: the page is what it showed), `track-failed`, `faulted`, `transport` (`state` `halted` after a Stop, `playing` after a Play), `error` |
| `timer_layer` | `task-started`, `task-ended` (a task that fails, or whose plugin is missing, is started and ended like any other, with `task-failed` between: the error page is what it showed), `task-failed`, `waiting`, `error` |
| `display` | `showing` ("On deck": the page is ready for the compositor, not yet on the panel), `shown` (title, digest, size, layers; each layer says which playlist track or timer task made it: `origin`), `skipped` (identical to what is shown: not drawn again), `deferred` (the panel is resting after its last refresh: `seconds` until the next page is drawn), `error` |
| `application` | `config-changed` (the area, and `changed`: the paths of the API routes whose answers may differ now, never the file), `restore` (a backup was restored: `ok`, `files`, `changed` `["/api"]`), `configure-failed` and `configured` (a part of the start: the display, the playlist or the timer tasks, `component`), `running` (every part is up), `waiting-for-setup` (an unclaimed device holds the layers back), `set-up` (it was claimed: they start), `input` (a button or other input and the action it was bound to: `source`, `input`, `gesture`, `action`), `pushed` (a message or picture pushed through the API: its title and minutes) |
| `data-source` | `cache-hit` (a kept download was read from disk, nothing sent), `cache-revalidated` (asked, the origin said not modified), `cache-miss` (downloaded and kept), `cache-stale` (the origin did not answer, the old download was used: shown as a problem), `cache-bypass` (downloaded, kept nothing); each has `datasource` and `bytes`, never the address |
| `device-io` | `devices` (the devices were set up again after a change to the settings; which are open), `error` |
| `Application`, `Display`, `PlaylistLayer`, `TimerLayer`, `DeviceIO`, `router` | `error`: a failure the task swallowed to keep running (`report_failure`, below) |
| `telemetry` | `hello` (the first message of the WebSocket, no `seq`: `run` names this start of the device), `gap` (a slow client missed some), `ping` |

With `--token`, the WebSocket needs the session (or a Bearer header). It also refuses a page from another origin than the server's own or `--cors`.

## Debug

To debug the processes:

* Python - start the `eink-billboard.py` in the Debugger
	* Requires config in `launch.json` that includes the command arguments listed above
* Javascript - use your web browser Dev Tools or VS Code

The following JSON may be used to set up the launch configuration for Python debugging.

------
		{
			"name": "Python: MAIN",
			"type": "debugpy",
			"request": "launch",
			"module": "python.eink-billboard",
			"args":["--dev", "--cors", "http://localhost:5173", "--host", "localhost", "--storage", ".\/.storage"],
			"env": {
				"PYTHONPATH": "${workspaceFolder}"
			},
			"console": "integratedTerminal"
		}
------

## Note to Cloners

The tests need no secret and no private data: they build their own storage from the factory defaults and the synthetic schedules in `python/tests/fixtures/storage/`, so the `unittest.yaml` workflow works in a clone, and on a fork's pull request, as it is.
