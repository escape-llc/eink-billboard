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
	* Semi-transparent image "overlays" are composited onto the background.
	* Similar behavior to device Lock Screen, e.g. Date/weather/reminders/etc.
	* Persistent (date/weather) or time-sensitive (reminders).
	* Determined by the Data Source.
* Foreground layer
	* Playlist Layer provides images for the foreground layer.
	* Overrides both Background and Overlay layers.
	* Content that is HTML-rendered, usually text, not expected to be overlaid with other information, e.g. RSS Feed.
	* Determined by the Data Source.
	* Foreground layer with transparency will "blend over" the current Background image.
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
* Flask configuration and management
	* static (for web app)
	* blueprints

### `unittest`

This runs the unit tests for Python.  Some of the configuration from the Main Task is replicated:

* deploy storage
* preset settings etc.

It currently does not test the Flask portion of the system.

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

The primary plugin is the Interstitial plugin.  This updates the Display's Priority layer with the (timed) image.

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

## Storage Folder

You must set up a separate `.storage` folder for the application to store its state.  See above for details.

## Run

Use the following recipe to get started with development:

* New Terminal 1
* `python -m python.eink-billboard --dev --cors "http://localhost:5173" --host localhost --storage ./.storage`
* New Terminal 2
* `cd app && npm run dev`

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

If you are running a clone and want to have the `unittest.yaml` in Github workflow work properly, you must get a storage root copied into the test runner.

We use the simple "trick" of base 64-encoding a ZIP archive, storing that string as a Repository Secret, and reversing the process in the workflow.

1. Stage your test data.  By default this location should be `./python/tests/.storage`.
2. Run the `prepare-test-data.ps1` script.  It uses the above path by default.
3. Take the `secure-string.txt` file and copy/paste it into a Secret in GH.  Use the same name as in our YAML file `TEST_STORAGE_B64`.
4. Run the `unittest.yaml` workflow; troubleshoot issues.