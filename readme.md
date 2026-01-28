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
	* We actually build Real Production Apps this way!
* Unit test coverage of the Python code
* Playlist scheduling model
	* Provides images for the main background display (see below)
	* No concept of time-of-day
* "Day-planner" scheduling model
	* Time/date sensitive tasks
	* Plugins have time slots
		* Different settings per time slot
	* Multiple tasks may run at the same time slot
* Replace Jinja with a modern web front end toolchain
	* Vite
	* Vue JS
* Different architecture for settings, etc.
	* Described in JSON configuration
	* Web settings UI automatically build themselves
* Re-implement existing plugins as data sources
	* The existing plugins just show (a list of) images/single image
	* Encapsulate the notion of "list of images"
* Re-implement existing plugins
	* Plugins are general-purpose "media player" like a slide-show
	* Same plugin handles many data sources
	* Tied to the display policy (see below) instead of the data
* Support same displays
	* Pimoroni
	* Waveshare
	* Mock
	* Tk
* Plugins do not require web authoring (for configuration) unless they need custom UI
	* This is separate from plugins rendering content via `chromium-headless-shell`
* Plugins and Data Sources have more infrastructure support
	* Set timers for slideshows
	* Schedule async operations, e.g. HTTP
	* Plugin (temporary) state (saved as JSON)

> Some of the Goals may seem "Enterprise-y" or over-complicated for a "hobby" project, but that is just how we roll!

# Display Architecture

After struggling with different ideas, we arrive at the following architecture, based on "layers".  These are the layers, back to front:

* Background layer
	* Playlists provide images for the background, like a Digital Picture Frame.
	* Determined by the Data Source.
* Overlay layer
	* This uses the Timed Layer to update (semi-) transparent display "overlays" that are composited onto the background.
	* Similar behavior to device Lock Screen, e.g. Date/weather/reminders/etc.
	* Persistent (date/weather) or time-sensitive (reminders).
	* Determined by the Data Source.
* Foreground layer
	* Override both Background and Overlay layers.
	* Content that is HTML-rendered, usually text, that does not expect to be overlaid with other information.
	* Determined by the Data Source.
* Priority layer
	* Like "Breaking News" that interrupts All Layers, and display for a timed period.
	* For example, show Clock on-the-hour for one minute, show Weather at bottom of every hour for five minutes.
	* Multiple Priority layer requests are queued up and the display is updated after previous one expires.

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

This task and all the subsequent tasks are organized as `threading.Thread` implementations.

The thread consists of a queue and message loop of typical construction.  There is a special `QuitMessage` to terminate the loop and the thread.

Application Task is managed by the Main Task.

Application Task manages the following additional components (tasks).

* Timer Task Layer
* Playlist Layer
* Display

### Playlist Layer

This layer runs the Playlists that update the Display's Background/Foreground Layer.

Each "Track" of the Playlist determines:

* Data Source
* Plugin instance settings

The primary plugin is the Slide Show plugin. The layer updated depends on the Data Source's "features".

When a plugin has computed its image, it sends a `DisplayImage` message with the image.  This is received by the Display Task (see below).

Slide Show plugin advances its Data Source based on the Slideshow Time.  When the Data Source is empty, the track ends, and the next track is selected.

When a Playlist ends, another Playlist is selected from the schedule and started.  This may be the same Playlist.

### Timer Layer

This layer runs the Timer Tasks that update the Display's Overlay/Priority Layer.

Each Track determines:

* Schedule (Start Time(s))
	* Startup
	* Day(s) of week
	* Time(s) of day
* Data Source
* Plugin instance settings

The primary plugin is the Interstitial plugin.  This updates the Display's Priority layer with the (timed) image.

Schedules are very flexible, and may be any combination of day(s) and time(s) of day.

When a track's schedule fires, it is executed.  Multiple tasks can fire at the same time.  A Timer Task may or may not generate any image, based on business logic.

### Display Task

This task operates primarily on the `DisplayImage` message and sends the image to the current display.

Display Task uses a dynamically determined "driver" that matches the hardware used:

* Pimoroni
* Waveshare
* Mock 
	* saves to local file system
* Tkinter
	* displays a window via `Tk`