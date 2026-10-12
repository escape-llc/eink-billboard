# eInk Billboard

This is a project to use the [InkyPi](https://github.com/fatihak/InkyPi) project to:

* Learn Python
* Play with Raspberry Pi
* Play with e-Ink technology

We have a reMarkable tablet, and enjoy it very much.  Also a long-standing fascination with e-Ink technology.

# Goals

> Disclaimer: this is not a judgment on the original source code!

After reviewing the code of the [InkyPi](https://github.com/fatihak/InkyPi) project, we got a plan:

* Support Windows-based development
	* Exercise Python's multi-platform capabilities
* Task-based architecture with Message Passing
	* Explore the multi-thread capabilities of Python
	* Explore Python's `async`/`await`
	* We actually build Real Production Apps this way!
* Unit test coverage of the Python code
* Playlist scheduling model
	* Provides images for the main background display (see below)
	* No concept of time-of-day
* "Day-planner" scheduling model
	* Time/date sensitive tasks
	* Tasks have day/time "trigger"
	* Tasks run plugins
		* Different settings per task
	* Multiple tasks may trigger at the same time
* Replace Jinja with a modern web front end toolchain
	* Vite
	* Vue JS
	* Descriptor-based UI
* Different architecture for settings, etc.
	* Described in JSON configuration
	* Web settings UI automatically build themselves
* Color theme
	* Device-wide algorithmic color scheme
	* Unified colors for all components
* Re-implement existing plugins as `async` data sources
	* The existing plugins just render one/list of image(s)
	* Encapsulate the notion of "list of images"
	* Data sources may use other data sources
* Plugins now "render" data sources to display layers (see below)
	* Handles any data source with matching "features"
	* Fewer and simpler plugins
* Re-implement plugins as `async`
	* Plugins are general-purpose "media player" like a slide-show
	* Same plugin handles many data sources
	* Tied to the display policy (see below) instead of the data
* Re-implement with `async` tasks
	* Self-hosting `async` loops for isolation between different tasks
	* Easy cancellation during shutdown or re-configuration
	* Greatly simplifies implementations
* Support same displays
	* Pimoroni
	* Waveshare
	* Mock
	* Tk
* Components do not require web authoring (for configuration) unless they need custom UI
	* This is separate from plugins rendering content via `chromium-headless-shell`
	* Schema descriptors provide the web application with metadata to build UI automatically
* Plugins and Data Sources have more infrastructure support
	* Set timers (for slideshows, etc.)
	* Schedule async operations, e.g. HTTP
	* Plugin (temporary) state (saved as JSON)

> Some of the Goals may seem "Enterprise-y" or over-complicated for a "hobby" project, but that is just how we roll!

# Display Architecture

After struggling with different ideas, we arrive at the following architecture, based on "layers".  These are the layers, back to front:

* Background layer
	* Playlist Layer provides images for the background layer.
	* Like a Digital Picture Frame.
	* Determined by the Data Source.
* Overlay layer
	* Timer Layer provides images for the overlay layer.
	* Semi-transparent image "overlays" are composited onto the background (`ImageOverlay`: an image at a position, optionally with a "wash": a blurred halo, in the shape of what it draws, that lightens the background around the text; `text_overlay()` makes a centered text box).
	* The Compositor draws them; the Foreground and Priority layers hide them.
	* The screen has six overlay **zones**, three across the top and three across the bottom (`top-left` ... `bottom-right`), laid out as the viewer sees the screen; the Display announces them at startup (`DisplaySettings.overlays`).
	* The **Overlay** plugin runs as a timer task: it asks its data source (one with the `layer-overlay` feature; it makes a single image, `media-image`) for an image the size of its zone, and the overlay stays until the task's next run replaces it.
	  When the data source has nothing to show, the overlay is taken down (revoked); so is the overlay of a task that is disabled or removed. A failing overlay task shows its error in its zone.
	* The **Today** data source draws the date (formats `long`, `full`, `short`, `numeric`, or a custom strftime pattern) in the theme's colors, the weekday highlighted.
	  A good timer task: plugin Overlay, data source Today, zone `top-right`, triggered on startup and every day at 0:00 (the midnight run replaces yesterday's date; the startup run covers a restart, since overlays are not kept across restarts).
	* Similar behavior to device Lock Screen, e.g. Date/weather/reminders/etc.
	* Persistent (date/weather) or time-sensitive (reminders).
	* Determined by the Data Source.
* Foreground layer
	* Playlist Layer provides images for the foreground layer, and the Timer Layer can too (blend).
	* Content that is HTML-rendered, usually text, not expected to be overlaid with other information, e.g. RSS Feed, Calendar.
	* Comes in two varieties:
		* **override**: a playlist page that covers everything under it (only a Priority image is drawn over it). Transparent parts show the theme's background color, not the background page.
		* **blend**: washes over the current background (alpha compositing: what is transparent shows the page under it). A playlist page can blend over the page of the slot before it; a timer task can blend for a while (Priority Update with Show As `blend`) over whatever the playlist shows. With no background, it washes over the theme's background color.
	* A playlist page's variety is the Slide Show's **Show As** (`auto`, `background`, `blend`, `override`); `auto` follows the Data Source: `layer-foreground` in its features overrides, anything else is a background page.
	* A playlist background page ends the playlist's foreground page (the next track, an error page or "Playback stopped" is never hidden behind it). A timer blend ends on its own time.
* Overlays appear only in **lock screen** mode: a background page and nothing above it. A playlist blend or override page, a timer blend or a priority image takes them off the screen (they are kept, not removed), and they come back when lock screen mode resumes. Foreground pages carry text of their own; overlay text is not drawn on them.
* Priority layer
	* Timer Layer provides images for the priority layer.
	* Like "Breaking News" that Interrupts All Layers, display for a timed period.
		* show Clock on-the-hour for one minute.
		* show Weather at bottom of every hour for five minutes.
	* Does not interrupt activity on lower layers, e.g. an in-progress Slide Show continues to run.
	* Multiple Priority layer images are queued up; the display is updated after previous one expires.

The Display Task (see below) receives Display Instructions and executes them against a Compositor (see below).

## Compositor

Changes to the current final image are arbitrated by the Compositor, a component that collects all the image instructions
for the layers, and determines the final image to output upon request.  This final image is then run through the post-processing
display settings, and sent to the driver for rendering on hardware/software.

The compositor "versions" each update to the layer data, and this is how it determines whether a new image should even be produced.

## Commit Timer

Because the system is message based, there is a Grace Period after each update, where the Display Task waits to see if additional display instructions arrive.   
This is important, because of the Blanking Period (see below).  If this occurs, the timer is reset.  This continues until the timer actually expires.

If the timer is expired, and the Blanking Period (see below) timer is expired, a new image is requested from the Compositor.

The Commit Timer is currently 2 seconds.

## Blanking Period

To avoid over-refreshing the display, which is not good for it, there is a Blanking Period timer of 60 seconds.

While this timer is active, display instructions are accummulated, and their net effect will be the next image rendered by the Compositor.

This means a sequence of display instructions may appear "lost" and not visualized, e.g. two successive background layer updates in quick succession.

# Tasks

The system is made up of tasks.

## Main Task

This is either:

* The top-level Python module `eink-billboard.py`
* The `unittest` module

### Top-level

This is what runs the production application.  It includes:

* Command line arguments
	* dev settings
	* CORS
	* storage root
* Application Task management (see below)
* FastAPI configuration and management, served by `uvicorn`
	* the built web app: files at the bundle root (Vite default layout), `index.html` for client-side routes
	* API routers (`/api`), including the ones plugins and datasources contribute

### `unittest`

This runs the unit tests for Python.  Some of the configuration from the Main Task is replicated:

* deploy storage
* preset settings etc.

The web API is tested in-process with FastAPI's `TestClient` (`test_web_api.py`), against a temporary copy of the test storage.

## Application Task

This task and all the subsequent tasks are organized as `threading.Thread` implementations.  They form the Control Plane of the system.

The thread consists of a queue and message loop of typical construction.  There is a special `QuitMessage` to terminate the loop and the thread.

Application Task is managed by the Main Task.

Application Task manages the following additional components (tasks).

* Timer Task Layer
* Playlist Layer
* Display

### Playlist Layer Task

This layer runs the Playlists that update the Display's Background/Foreground Layer.  The primary algorithm is run in a dedicated `async` coroutine the task controls.

Each "Track" of the Playlist determines:

* Plugin
* Plugin instance settings
	* Data Source
	* Data Source instance settings

The Playlist Layer coroutine simply loops through all the playlists, and then all the tracks in each playlist.  When the last track of the last playlist ends, it terminates, and the Playlist Layer schedules the coroutine again.

The primary plugin is the Slide Show plugin. The layer updated depends on the Data Source's "features".

When a plugin has computed its image, it sends a `DisplayImage` message with the image.  This is received by the Display Task (see below).

Slide Show plugin advances its Data Source based on the Slideshow Time.  When the Data Source is empty, the track ends, and the next track is selected.

When a Playlist ends, another Playlist is selected from the schedule and started.  This may be the same Playlist.

### Timer Layer Task

This layer runs the Timer Tasks that update the Display's Overlay/Priority Layer.  The primary algorithm is run in a dedicated `async` coroutine the task controls.

Each Track determines:

* Trigger (Start Time(s))
	* Startup
	* Day(s) of week
	* Time(s) of day
* Plugin
* Plugin instance settings
	* Data Source
	* Data Source instance settings

The Timer Layer coroutine executes a Playlist consisting of the day's task list with startup and all the triggers materialized (exact time-of-day computed).  When this Playlist ends, the coroutine ends, and the Timer Layer calculates the next day's Playlist and schedules the coroutine again (without startup items).

The primary plugin is the Priority Update plugin (id `interstitial`).  This updates the Display's Priority layer with the (timed) image.

Schedules are very flexible, and may be specific combinations of day(s) and time(s) of day.

When a track's task triggers, it is executed.  Multiple tasks can fire at the same time.  A Timer Task may or may not generate any image, based on business logic.

### Display Task

This task operates primarily on the `DisplayImage` message (and subclasses) and sends the image to the current display.

Display Task uses a dynamically determined "driver" that matches the hardware used:

* Pimoroni
* Waveshare
* Mock 
	* saves to local file system
* Tkinter
	* displays a window via `Tk`

# Storage Architecture

The application uses a specific "storage root" folder it keeps everything in.

* Storage Root
	* A folder outside all the source code, used to keep the volatile state of the application.
		* Global Settings
		* Per-datasource Settings/State
		* Per-plugin Settings/State
		* Schedules
		* Schemas
* Source Root
	* Used to locate "internal" source files that get served via API
* NVE (Non-volatile Environment) Root
	* Used to initialize storage from "factory default" during a force-reset or manual staging
	* There is a default version in the source code
	* You may stage any number of NVE to use for "factory reset"

A Storage Root is required for the following:

* Main Application
* Unit Tests

By default it is named `.storage` and is by default ignored in `.gitignore`. As a consequence, there is no canonical example of these files (in repository), beyond what is in the NVE (which is in the source code by default).

# DEV Mode

## Calendar Data Source
A month grid, the coming weeks, and/or an agenda of the coming days, from the calendars kept in the Calendar data source's settings:
* **iCal links** (`https`, `http` or `webcal`): most calendar apps publish one. Google Calendar has a "Public address in iCal format" (the calendar must be public) or a "Secret address in iCal format" (treat it as a password). A link that needs a sign-in can use Basic (username and password) or a Bearer token.
* **CalDAV servers** (Nextcloud, Fastmail, iCloud with an app password, Radicale): one query for the days the page shows.
* **Holidays** by country (and state or province), from the `holidays` package, which needs no internet.

The settings also choose the first day of the week and whether the grid shows ISO week numbers. A task chooses the views, each a page of its slot, in this order:
* **month:** the month's grid;
* **weeks:** the current week and the next few (Weeks Ahead, default 4) as continuous rows across month ends. Every other month is tinted and each month is named on its first day;
* **agenda:** a list of the coming days (Agenda Days, default 7).

It also chooses which calendars and holiday sets to show (none chosen means all that are enabled).
Each address has a Test button. Besides how many events are coming, it warns when a calendar **runs out**: when nothing in it repeats, it is empty after its last event. A season's fixture list is like this, and the address usually changes for the next season. The page says the same in its footer once that day is in view.
* **Google and Microsoft accounts:** add the account under Accounts, save, then press **Connect**. A calendar row of the kind `google` or `microsoft` names the account and, optionally, a calendar ID; Connect lists the account's calendars and their IDs. Empty means the main calendar.

### Registering your own app (once per account)
The device signs in with an app registration of your own; nothing is shared with anyone else.
* **Google:**
  1. In the Google Cloud console, create a project, enable the **Google Calendar API**, and create an **OAuth client ID** of type **Desktop app**.
  2. Put its client ID and client secret in the account row.
  3. On the OAuth consent screen, **publish** the app. An app left in "Testing" gets sign-ins that expire after 7 days. An unverified app works for your own account: Google warns once.
  4. Connect opens Google's sign-in. Afterwards your browser goes to a `http://localhost/...` address that does not load: copy that whole address back into the settings page.
* **Microsoft:**
  1. In the Microsoft Entra admin center, register an app.
  2. Under Authentication, allow **public client flows**.
  3. Add the delegated permissions **Calendars.Read** and **offline_access**.
  4. Put its application (client) ID in the account row. The tenant is `common` for a personal or any work account, or your tenant's name or ID.
  5. Connect shows a code: open microsoft.com/devicelogin on any device, enter it and sign in, and the page finishes on its own.

The sign-in's tokens are kept in `datasources/calendar/tokens.json` in the storage folder, never in the settings (which the browser reads). Delete an account, or change its client ID, and it must be connected again.

## Weather Data Source
The weather at the device's location from [OpenWeatherMap](https://openweathermap.org), one page per chosen view: the weather **now**, the next day in steps of three **hours**, the next five **days**. Several views make a slot of that many pages.
* **The place** is the `location` of the System settings (the GPS position; empty means the slot fails with a message telling you to set it).
* **The key**: register for a free key (the settings page has a button to the sign-up page). It goes in the Weather data source's settings and is never sent back to the browser. A new key can take a couple of hours to start working: until then the slot says the key was refused.
* **Units**: `auto` reads miles and Fahrenheit in the US timezones and kilometres and Celsius elsewhere, or choose `metric` or `imperial`. The clock follows the System settings' time format.
* It uses the free plan's endpoints (`/data/2.5/weather` and `/data/2.5/forecast`), only the ones the chosen views need, once per slot. The icons are drawn by the page, so rendering needs no network. The key is in the address OpenWeatherMap wants, so the HTTP client's log lines have it hidden (`appid=***`).

## Storage Folder

You must set up a separate `.storage` folder for the application to store its state.  See above for details.

## Run

Use the following recipe to get started with development (to run it on a Raspberry Pi, see the next section):

* New Terminal 1
* `python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ./.storage`
* New Terminal 2
* `cd app && npm run dev`

The web app finds the server through `VITE_API_URL`: `http://localhost:8080/` in development (`app/.env.development`, the recipe above) and `/` in the built app, which the server serves itself (`app/.env.production`). Copy `app/.env.example` to `app/.env.local` to change it for yourself; a trailing slash is expected.

## Running on a Raspberry Pi

The usual setup is a **systemd service** on the Pi, used from another computer on the home network through the Pi's address. The other is a browser on the Pi itself (the console), where the server listens on `localhost` only.

**As a service** (`deploy/eink-billboard.service`, **not yet tested on a real Pi**: adjust the paths and groups to your install):

1. Install the code in `/opt/eink-billboard` (`uv sync --frozen`, which includes the `device` group on a Pi, and `cd app && npm ci && npm run build`), and make a user for it: `sudo useradd --system --home-dir /var/lib/eink-billboard --groups spi,gpio,i2c eink`.
2. Copy the unit, then `sudo systemctl daemon-reload && sudo systemctl enable --now eink-billboard`. It runs as that user, may write only to `/var/lib/eink-billboard` (the storage folder), and listens on port 80 without being root (`CAP_NET_BIND_SERVICE`).
3. **Claim the device.** A new device has no password. Read its one-time setup code from the log, `journalctl -u eink-billboard | grep "setup code"` (it is also drawn on the panel for ten minutes), open `http://<the Pi's address>` or `http://<its name>.local`, enter the code and choose a password. From then on the web app asks for that password. Change it under Settings, System.
4. **Forgot the password?** At the Pi: `sudo systemctl stop eink-billboard`, then `sudo -u eink /opt/eink-billboard/.venv/bin/python -m python.eink-billboard --storage /var/lib/eink-billboard --reset-password`, then start it again: the device is new again and logs a new setup code.

**Settings for the service** go in `/etc/eink-billboard.env` (`sudo chmod 600`, owned by root; the unit reads it if it is there). Prefer it to command line options, which anyone on the Pi can read in the process list:

```
# the credential of scripts (Authorization: Bearer ...); it also signs in the web app
EINK_API_TOKEN=a-long-random-string
# names besides localhost, addresses and the Pi's own name that the server answers to (comma separated)
EINK_ALLOW_HOSTS=billboard.home.arpa
```

**What the server accepts.** It answers only to `localhost`, IP addresses, the Pi's name and `<name>.local`: a request for any other name is refused (421), which stops a web page on another site from reaching the device by DNS rebinding. Reaching the Pi by a name of your own (a router's DNS entry, a reverse proxy) needs `EINK_ALLOW_HOSTS` or `--allow-host`. A client that gets the password or token wrong repeatedly has to wait (429), and each failure is in the log.

**On a network you trust, with no password:** `--no-auth` keeps the old open behavior (it logs a warning at every start).

**The console only:** `--host localhost` listens on the Pi alone and needs no password until you set one (Settings, System). `--require-auth` asks even there.

**HTTPS.** The server speaks plain HTTP, which is normal on a home network (the password is sent in the clear to the Pi). For HTTPS put a reverse proxy in front, for example Caddy, and keep the server on `localhost`:

```
billboard.home.arpa {
	reverse_proxy localhost:8080
}
```

Start the service with `--host localhost --port 8080` and `EINK_ALLOW_HOSTS=billboard.home.arpa`. Behind a proxy the app sees plain `http`, so its session cookie is not marked `Secure` (forwarded headers are deliberately not trusted).

## Web API

* The API is under `/api`; interactive documentation is served at `/api/docs`.
* Every error response has the same body: `{ "success": false, "message": "...", "id": "..." }` (plus `rev` on a `409` revision conflict, and `errors` on a `422` validation failure).
* Settings documents carry `_id` and `_rev`. A `PUT` must send back the `_rev` it loaded; if the settings changed in the meantime the server answers `409` with the current `rev`.
* Settings the schema marks `"writeOnly": true` (e.g. an API key) are returned as `********`. Sending `********` back, or omitting the field, keeps the stored value.
* **A new device is claimed, not given a default password.** Listening on the network (the default), it starts unclaimed: every `/api` route answers 401 with `setup: true` until someone enters the one-time **setup code**, which is in the log (`journalctl -u <service>` under systemd) and on the e-Ink panel, and chooses the device password (at least 8 characters). `--host localhost` stays open until a password is set. `--no-auth` keeps a device open on a network you trust; `--require-auth` asks even on `localhost`; `python -m python.eink-billboard --reset-password` forgets the password (console access is ownership). Below, the API token is the credential for scripts.
* Set `--token <value>` (or the `EINK_API_TOKEN` environment variable) to require `Authorization: Bearer <value>` on every `/api` request. The web app asks for the token the first time it gets a `401` and sends it once to `POST /api/session`; the server remembers the sign-in in memory (a restart signs everyone out; sessions last seven days) and the browser keeps only an `HttpOnly`, `SameSite=Strict` cookie that scripts cannot read. The browser stores nothing else but the theme. `DELETE /api/session` signs out. A client that gets the token wrong more than three times in a row is told to wait (429, `Retry-After`; 2 s, doubling, at most 5 minutes) and each failure is logged with the client's address. The server answers only to `localhost`, IP addresses, the machine's own name and `<name>.local`; a device reached by another name needs `--allow-host <name>` (or `EINK_ALLOW_HOSTS`), otherwise the request is refused with 421 (a defence against DNS rebinding). Scripts can keep sending `Authorization: Bearer <value>`. Do this whenever the server listens on a network you do not fully trust. Behind a TLS-terminating proxy the app sees plain `http`, so the session cookie is not marked `Secure` (forwarded headers are not trusted); `/api/docs` and `/api/openapi.json` require the token like the rest of `/api`.
* `--port` overrides the listening port (default `8080` with `--dev`, otherwise `80`).
* Plugins and datasources may contribute an API router; name it in the `"router"` entry of their `*-info.json`.

## Telemetry
The web app's **Activity** button (top right) opens a gutter beside the page. It shows:
* **Now showing:** a thumbnail of what the panel shows, with the layers it was composed of (background, blend, override, timer blend, priority, overlays). Click it for full size.
* **Recently shown:** the last few pages.
* **Events:** what the device reports, with a source filter and "Problems only".

The gutter follows a WebSocket (`/api/telemetry/ws?since=<seq>`), which reconnects on its own and resumes after the last event it had. Times are the device's, not the browser's. The other routes:
* `GET /api/telemetry?since=<seq>`: the kept events, the last 200, newest last;
* a failure's event also carries `detail`, the exception in full, but only for a page opened on the device itself (`localhost`: the connection's address is loopback); to anyone else it is left out, since the text can hold an address with a key. In a container the published port does not look local, so read the log there;
* `GET /api/status`: how bringing up the display and the two layers went, `{ ok, components: { display | playlist-layer | timer-layer: { state: ok | failed | starting, message } } }`, in our words (a failure says to see the log); the header's status button reads it every 10 s. A failed display is not retried when its settings change (live reconfiguration is not built): fix the settings and restart;
* `GET /api/display/current`: the last `shown` event;
* `GET /api/display/images/<digest>?size=thumb|full`: a shown image as PNG. The device keeps the last 8, in memory only.

An event is `{ seq, ts, source, kind, message?, values }`:

| source | kinds |
|---|---|
| `playlist_layer` | `track-started`, `track-ended`, `track-failed`, `faulted`, `stopped`, `error` |
| `timer_layer` | `task-started`, `task-ended`, `task-failed`, `waiting`, `error` |
| `display` | `showing` ("On deck": the page is ready for the compositor, not yet on the panel), `shown` (title, digest, size, layers; each layer says which playlist track or timer task made it: `origin`), `skipped` (identical to what is shown: not drawn again), `error` |
| `application` | `config-changed` (the area only), `configure-failed` |
| `Application`, `Display`, `PlaylistLayer`, `TimerLayer`, `router` | `error`: a failure the task swallowed to keep running (`report_failure`, below) |
| `telemetry` | `gap` (a slow client missed some), `ping` |

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
