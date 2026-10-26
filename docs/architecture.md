# Architecture

How the server is built: the display layers and compositor, the tasks and the storage.

## Design

* Developed on Windows and Linux alike
	* Python's multi-platform support
* Developed in Docker or Podman containers too (see Containers)
* Task-based architecture with message passing
	* Threads, each with its own `asyncio` loop
	* Easy cancellation during shutdown or reconfiguration
* Unit tests for the Python code
* A playlist scheduling model
	* Provides the pages of the background and foreground (see below)
	* No time of day
* A "day-planner" scheduling model
	* Time and date sensitive tasks, each with a day and time "trigger"
	* Tasks run plugins, with settings of their own
	* Several tasks may trigger at the same time
* A web app built with Vite, Vue and PrimeVue
	* Settings forms built from descriptors
* Settings described in JSON
	* The web settings forms build themselves from schema descriptors; a component needs web code of its own only for a custom control
* A device-wide algorithmic color theme, the same colors in every component
* `async` data sources make the content
	* A page or a list of pages
	* Data sources may use other data sources
* `async` plugins show data sources on display layers (see below)
	* A plugin is a general-purpose "media player", such as a slide show
	* It handles any data source with matching "features", so there are few, simple plugins
	* It follows the display policy (see below), not the data
* Displays: Pimoroni Inky, Waveshare, Mock, Tk
* Infrastructure for plugins and data sources
	* Timers (for slide shows, etc.)
	* `async` operations such as HTTP
	* State of their own, saved as JSON

> Some of this may seem "Enterprise-y" or over-complicated for a "hobby" project, but that is just how we roll!

## Display Architecture

The display is built from "layers", back to front:

* Background layer
	* Playlist Layer provides images for the background layer.
	* Like a Digital Picture Frame.
	* Determined by the Data Source.
* Overlay layer
	* Timer Layer provides images for the overlay layer.
	* Semi-transparent image "overlays" are composited onto the background (`ImageOverlay`: an image at a position; what it does not draw shows the background). Overlay text is drawn by Chromium on a transparent page with an outline in the theme's outline color (white, or black on a black page) so it reads over a busy picture (`python/datasources/overlay_text.py`); the Overlay task's `outline` (0 to 1, a factor of the text size) sets how wide.
	* The Compositor draws them; the Foreground and Priority layers hide them.
	* The screen has six overlay **zones**, three across the top and three across the bottom (`top-left` ... `bottom-right`), laid out as the viewer sees the screen; the Display announces them at startup (`DisplaySettings.overlays`).
	* The **Overlay** plugin runs as a timer task: it asks its data source (one with the `layer-overlay` feature; it makes a single image, `media-image`) for an image the size of its zone, and the overlay stays until the task's next run replaces it.
	  When the data source has nothing to show, the overlay is taken down (revoked); so is the overlay of a task that is disabled or removed. A failing overlay task shows its error in its zone.
	* Overlay data sources draw the date, the weather or the coming events in a zone; each plugin and data source is described in the web app's Help drawer.
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

### Compositor

Changes to the current final image are arbitrated by the Compositor, a component that collects all the image instructions
for the layers, and determines the final image to output upon request.  This final image is then run through the post-processing
display settings, and sent to the driver for rendering on hardware/software.

The compositor "versions" each update to the layer data, and this is how it determines whether a new image should even be produced.

### Commit Timer

Because the system is message based, there is a Grace Period after each update, where the Display Task waits to see if additional display instructions arrive.   
This is important, because of the Blanking Period (see below).  If this occurs, the timer is reset.  This continues until the timer actually expires.

If the timer is expired, and the Blanking Period (see below) timer is expired, a new image is requested from the Compositor.

The Commit Timer is currently 2 seconds.

### Blanking Period

To avoid over-refreshing the display, which is not good for it (and to give a picture time to settle before it is drawn over), the panel **rests** after each refresh. **No image is sent to the driver during the rest.**

* The rest is the **Rest After a Refresh** display setting (`refreshInterval`, seconds, default 60; 0 for none, which suits the mock display). It starts when a refresh **ends**, so a slow refresh does not eat into it, and it starts after a refresh that fails or times out too, since the panel may have been driven all the same. A panel model may need more than the setting says (`MIN_REST_SECONDS` of its display class); the longer one wins.
* The rule is held **in the driver stage** (`python/display/refresh_gate.py`, beside the panel guard): every display class asks its gate before it sends an image and refuses (`TooSoon`) while the panel rests, so whatever else may one day call `render` is held to it too.
* The Display Task waits out the rest **before** it takes the next image from the Compositor, so display instructions that arrive meanwhile are accumulated and their net effect is the next image. This means a sequence of display instructions may appear "lost" and not visualized, e.g. two successive background layer updates in quick succession. A `deferred` telemetry event says how long the wait is.
* The end of the last refresh and a digest of what the panel shows are kept across restarts (the storage's `state/refresh.json`, written through the configuration manager), so a restart inside the rest waits out what is left of it and an unchanged page is not drawn again. A stored time can never hold the panel for more than one rest (a Pi without a clock set reads any date at boot), and a file that cannot be read is no state.

## Tasks

The system is made up of tasks.

### Main Task

This is either:

* The top-level Python module `eink-billboard.py`
* The `unittest` module

#### Top-level

This is what runs the production application.  It includes:

* Command line arguments
	* dev settings
	* CORS
	* storage root
* Application Task management (see below)
* FastAPI configuration and management, served by `uvicorn`
	* the built web app: files at the bundle root (Vite default layout), `index.html` for client-side routes
	* API routers (`/api`), including the ones plugins and datasources contribute

#### `unittest`

This runs the unit tests for Python.  Some of the configuration from the Main Task is replicated:

* deploy storage
* preset settings etc.

The web API is tested in-process with FastAPI's `TestClient` (`test_web_api.py`), against a temporary copy of the test storage.

### Application Task

This task and all the subsequent tasks are organized as `threading.Thread` implementations.  They form the Control Plane of the system.

The thread consists of a queue and message loop of typical construction.  There is a special `QuitMessage` to terminate the loop and the thread.

Application Task is managed by the Main Task.

Application Task manages the following additional components (tasks).

* Timer Task Layer
* Playlist Layer
* Display
* Device I/O

#### Restoring a backup: one notice, not one per file

A restore (see "Backup and Restore" under Web API) writes many files at once. Left alone, every changed file would be its own change event, and each would reach every task: the layers would reload against a half-written storage, and the web app would be told thirty times. So the restore is bracketed by two messages and **the Application enforces the semantics** (it is the one place that turns the watcher's events into `ConfigurationChanged`):

* `RestoreBegin` (from the route, which waits for the answer) is **refused** when the device has not been claimed or a restore is already running. Otherwise the Application goes from `idle` to `restoring`: the watcher's per-file events are **absorbed** (counted, not sent), the layers and the display hear nothing.
* `RestoreEnd` (sent in a `finally`, so it always comes) makes it `draining`: every cached configuration object is forgotten, and the Application waits until no change event has come for 3 seconds (the watcher reports a file a debounce after it was written), at most 15 seconds.
* Then it sends **one** `ConfigurationChanged(area="restore")` and one telemetry line (`restore`), and is `idle` again. Every task treats `restore` as "everything changed": the layers reload their schedules once, the Device I/O task reads its settings again, the Display says that the display settings apply at the next start. An edit made during the restore is covered by that one notice, never lost.
* A lease guards against a route that dies before its end: a `restoring` state older than two minutes is ended by the Application itself, and a quit clears it, so change notices cannot stay held back.

#### Playlist Layer Task

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

##### Transport: play, stop, next

A viewer controls the Playlist Layer (the Timer Layer keeps running) with three commands. They go to the Application Task first (`Application.transport(command)`, thread-safe, called by `POST /api/transport` and by the device's buttons), which drops them while the device is not claimed and forwards the rest on the `playlist-layer` route.

* **Stop** (`StopPlayback`) cancels the running track. The panel keeps what it shows and nothing starts the layer again (not a schedule reload, not the restart after a failure, not the end of a pass) until Play or Next.
* **Play** (`ResumePlayback`) enters the interrupted track again with `PluginExecutionContext.resumed` set. **Every plugin handles that flag** (`resume_contract` on the class, `"honours"` or `"ignores"`; `test_transport` fails for a plugin that says neither). The Slide Show carries on with the next item of a kept list; it passes on (returns at once, and the layer goes on to the next track) for a single picture, a list that is not kept, and a kept list that was used up, so a picture is not shown or generated twice.
* **Next** (`NextTrack`) cancels and starts at the next track, wrapping at the end and crossing playlists. A stopped layer plays from there.
* A schedule reload goes on where the layer was instead of starting over. The track is found by the playlist's and track's ids in the new playlists and entered as a resume; a track whose own settings changed runs afresh; a track that is gone leaves its place in the playlist; a playlist that is gone, a layer that has not begun, or a faulted layer starts from the top. "The schedules changed" compares the files as they were loaded, not the tracks the layer ran (those have their defaults filled in), so saving a timer task does not touch the playlist.
* A track that keeps failing is **struck out**: after the System setting *Failures Before a Track Stops Running* (3) failures in a row (a missing plugin or a setting that fails its rules strikes it out at once), the layer no longer runs it and its slot shows the error page. It is **tried again** after *First Retry of a Struck-Out Track* (60 s; one attempt, and if it fails the wait doubles, up to *Longest Wait Between Retries*, 900 s); a success puts it back in play, and changing the playlist tries it at once. When every track has struck out, the panel says playback is stopped and the same retries run.

The layer task takes the starting coordinates (`Start`: playlist, track, resume) and begins its pass there; later passes start from the top.

#### Timer Layer Task

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

The primary plugin is the Priority Update plugin (id `priority-update`).  This updates the Display's Priority layer with the (timed) image.

Schedules are very flexible, and may be specific combinations of day(s) and time(s) of day.

When a track's task triggers, it is executed.  Multiple tasks can fire at the same time.  A Timer Task may or may not generate any image, based on business logic.

#### Display Task

This task operates primarily on the `DisplayImage` message (and subclasses) and sends the image to the current display.

Display Task uses a dynamically determined "driver" that matches the hardware used. **Each display device is a descriptor**, like a plugin or a data source: `python/displays/<id>/display-info.json` (`mock`, `tk`, `inky`, `waveshare`: `id`, `name`, `class`, `module`, `file`, `features` including `display-device`, `describe`, and `instanceSettings` with the device's own properties). The Display settings' **Display Type** is a `schema` field whose lookup is `{ "schema": "displays", "features": ["display-device"] }`, so it offers the installed displays and, once one is chosen, its fields appear under it (`GET /api/displays/list` feeds the form). The chosen device's fields are stored **in the `display` settings document** beside the common ones (orientation, rotate 180, rest after a refresh, image settings), are checked on save like a task's content (only the chosen device's), and their defaults are filled in at seeding and at every start. The Display task looks the type up among the descriptors by declared id and makes its class (`ConfigurationManager.enum_displays` / `create_display`); a type that is not installed fails in our words. A new display is a folder with a descriptor and a class: nothing else lists it. (The GPIO buttons are not displays: they are the Devices tab.)

* Pimoroni **Inky** (`inky`): "auto mode": the driver reads the board's EEPROM (pHAT, wHAT, Impression, Spectra...) and its size is the display's resolution.
	* The driver is part of the `device` dependency group (Linux, `uv sync --frozen`, `--no-group device` elsewhere) and is imported when the display is made, never at start-up, so Windows, the container and a Pi without it all run.
	* The Display task owns it like the others. When the driver is not installed, or no board answers (nothing attached, SPI or I2C off), the display does **not** start: there is no fallback to the mock one (it would draw somewhere nobody looks). The System page's Device card says why in our words ("The Inky driver is not installed...", "No Inky display was found. Check that it is attached and that SPI and I2C are enabled..."); the playlist and the timer wait for the display. Fix it (or choose `mock` or `tk` in the Display settings) and restart: live reconfiguration is not built.
	* **Border Color** (`borderColor`) is given to the driver's `set_border` before each refresh. **Each model numbers its colors differently** (a pHAT has white 0 and black 1, an Impression black 0 and white 1, and the Spectra boards' class attributes disagree with the module constants that `set_border` checks), so the name is looked up in the constants of the board's own driver module, never in `inky.BLACK` or a class attribute. White and black exist on every model, red or yellow on the ones with that ink, green, blue and orange on the 7-color ones; a color the board does not have keeps the driver's own border and the log says so once (never a failed refresh).
	* **Not tried on a real panel** (there is none on the development machine): the driver is tested with a fake board, and its failure flow can be run for real in a container (below).
	* **Troubleshooting without a panel:** `podman compose --profile inky up --build -d app-inky` serves the app on http://localhost:8081 with the real `inky` driver installed (the `device` group, built with a compiler) and a storage of its own. Set the Display Type to `inky` (Display settings), save, and restart it (`podman compose --profile inky restart app-inky`): the driver loads, reads for the board's EEPROM, finds none, and the System page says so. `EINK_FAKE_INKY=<mode> podman compose --profile inky up -d app-inky` pretends there is a board (`scripts/fake_inky.py` replaces only I2C, the GPIO lines and SPI): `ok` (draws; the last image is `/tmp/fake-inky/fake-inky-last.png`, `podman cp` it out), `busy-stuck` (a busy line held high: every refresh waits out the driver's timeout), `spi-off` (the display starts, the first draw fails: SPI not enabled), `unknown-board` (the board answered, this driver version has no class for it).
* **Waveshare** (`waveshare`): any of the 65 models whose official drivers are vendored in `python/display/waveshare_epd/` (see its `VENDORED.md`: source commit, the few lines removed, how to update). A Waveshare cannot say which model it is, so the Display settings have a **Waveshare Model** (`model`, Waveshare's module names: `epd7in3e` is the 7.3 inch 7-color one). The model's driver is imported when the display is made (it needs `gpiozero` and `spidev`, the `device` group, Raspberry Pi only; a Pi 5 also needs the `lgpio` backend, which has no wheel for Python 3.13: it is in the `device` group and built from source, which the container image does (the C library `lg`, pinned and checked by hash, plus `swig`; Debian has no package for it); outside a container install `swig` and `lg` first). Black-white-red panels are given the black and the red layer.
	* The driver stage guards every panel the same way (`python/display/panel_guard.py`, used by the Inky and Waveshare displays). The drivers wait for the panel's busy line with a loop that never ends by itself, so a panel that is not there (or wired wrong) would hold the device for good: starting and each refresh are given a time (60 and 180 seconds); a panel that does not answer is reported in the status in our words, and a stuck refresh refuses the next ones. Like the Inky, a display that cannot start is not replaced by the mock one.
	* **Troubleshooting without a panel:** `podman compose --profile waveshare up --build -d app-waveshare` (http://localhost:8082, own storage, the same image as `app-inky`). Choose `waveshare` and a model, save, restart. `EINK_FAKE_WAVESHARE=<mode>` pretends there is a Raspberry Pi with a panel (`scripts/fake_waveshare.py` answers for `/proc/cpuinfo`, `spidev` and the `gpiozero` pins): `ok` (draws; the last image is `/tmp/fake-waveshare/fake-waveshare-last.png`), `busy-stuck` (the busy line stays low: the start times out), `spi-off` (no SPI bus: the start fails); with none set the driver finds no Raspberry Pi.
	* **Not tried on a real panel.**
* Mock (`mock`)
	* saves to local file system; its own settings are the size of the pictures (`width`, `height`, 800 x 480), the `outputFolder` and `cleanOutputFolder`
* Tkinter
	* displays a window via `Tk`

#### Device I/O Task

Everything connected to the Pi's own lines that is **not the panel** (push buttons; sensors on the I2C and SPI buses would join them) belongs to one task, `DeviceIO` (`python/task/device_io.py`). The display's driver stage keeps the panel's lines; this task opens, listens to and closes the rest. It knows hardware and nothing about what an input *means*:

* A device (`python/device/`) reports that something happened: `InputEvent(source, name, gesture)` (`gesture`: `press`, `long-press`). The library's callback only puts the event on this task's queue; the task forwards it on the `device-input` route and the **Application** gives it its meaning (`python/device/bindings.py`: what a press does is the action of the button's row in the `devices` settings, read at each press: `play`, `stop`, `toggle` or `next`, the same commands as the web app's buttons, ignored while the device is not claimed; only a `press` is bound, a `long-press` is reported and bound to nothing yet). A row whose action is `task` carries the settings of a Priority Update; a press sends `RunTrigger` on the `timer-layer` route, and the timer layer runs it as a job of its own, like a timer task that is in no schedule file.
* **Buttons** (the `devices` settings' `triggers`: a row for each button, its GPIO `pin` and its `action`; a button is named for its pin, `gpio-5`; the pin's pull-up holds it high, 50 ms debounce). The list's own rules keep a pin to one row (`items.key`) and each of `play`, `stop`, `toggle` and `next` to one button (`items.once`). Nothing is imported or opened with no rows. `gpiozero` (the `device` dependency group) is imported when a button is opened; on a machine without it the status says what to do.
* **The panel's lines are off limits** (`python/device/pins.py`): a pin is refused, in words that name it, when the panel uses it (Waveshare: 17 reset, 25 data/command, 8 chip select, 24 busy, 18 power, 10 and 11 SPI; Inky: 27 reset, 17 busy, 22 data/command, 8 chip select, 10 and 11 SPI, plus 26 and 16 on the 13.3 inch one), when it is not on the 40-pin header (2 to 27), or when two buttons share it. I2C bus 1 and SPI chip select 1 (`/dev/spidev0.1`) are left for sensors.
* A change to the Devices settings is applied within a few seconds, without a restart; a configuration that is refused or cannot be opened leaves the one that worked in place, and the failure is told (status, telemetry `error`).
* A new device is added in `python/device/registry.py` (an `InputDevice`: its pins, `open`, `close`).
* **Trying the buttons on a Pi:** `python -m scripts.gpio_check --pin 5 6` (the app stopped) opens the same `Buttons` device and prints each press; `python -m scripts.gpio_press --pin 12` presses a button for the running app, by pulling a free driver pin low (the driver pin is wired to the button's pin; it is only driven low, then let go). Both refuse the panel's pins with `--panel`.

## Storage Architecture

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

### Versions of stored documents

A stored document says which version of its **source** it is, so a setting can be renamed, removed or reinterpreted and an older document still comes along.

* A settings document carries the `_schema` of its source: the schema file (`schemas/system.json`) for the device's own, the `settings` block of a plugin's or data source's descriptor, the constants in `python/model/schedule.py` for a schedule. The number at the end is the version (`urn:inky:storage:schema:system:1`); a document with no `_schema` is version 1. A document that has no source (a kept list, the panel's refresh state, the Calendar's sign-ins) carries an integer `_version`, which the code that writes it owns.
* **A migration** is a pure function from version `n` to `n + 1`, registered in `python/model/migrations.py`: it is hard-coded on purpose, because what a rename means is for a person to say. At every start `upgrade_settings()` migrates each stored document in order up to its source's number, then fills in the keys the source added since (a default), and stamps it. A value the person set is never changed unless a migration says so.
* A document from a **newer** version (a downgrade) is not changed and not trusted: it is left as it is and named once on the System page and in the log. A source whose number was raised with no migration leaves its documents as they are, and says so.
* A saved document carries its source's `_schema` whatever the request said: a version is the source's to give.
* **Changing a setting's shape** (renaming, removing, retyping, reinterpreting; adding a property with a default needs none of this): raise the source's number, register the migration, run `uv run python -m python.tests.test_schema_versions --record`, and add a fixture of the old shape. `test_schema_versions` fails until they agree (`fixtures/schema_shapes.json` records each source's properties at its current number).

A Storage Root is required for the following:

* Main Application
* Unit Tests

By default it is named `.storage` and is by default ignored in `.gitignore`. As a consequence, there is no canonical example of these files (in repository), beyond what is in the NVE (which is in the source code by default).
