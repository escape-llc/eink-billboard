# Vendored: Waveshare e-Paper drivers

These files are Waveshare's own Python drivers, copied unchanged (but for the lines named below) from
<https://github.com/waveshareteam/e-Paper>, commit `a794fbc39656b0f93938d1ffb3fdc77eaed9e9fc`, folder `RaspberryPi_JetsonNano/python/lib/waveshare_epd`
(65 models and `epdconfig.py`, which picks the Raspberry Pi, Jetson or Sunrise board's GPIO and SPI when it is imported). Each file carries Waveshare's MIT permission
notice in its header; keep it. They are not ours to reformat or lint: `ruff`, `mypy` and `coverage` leave this folder out (`pyproject.toml`).

Some stray imports were removed because they stop a module from importing at all on Python 3.13 or on a machine without the library, and nothing uses them:
`epd2in9d.py` (`from distutils.command.build_scripts import build_scripts`, `distutils` is gone), `epd3in52.py` (`from multiprocessing.reduction import recv_handle`) and `import RPi.GPIO as GPIO` in `epd2in13d.py`, `epd2in9d.py`, `epd4in2.py` and `epd4in2_V2.py` (the driver talks to the pins through `epdconfig`; `RPi.GPIO` has no wheel for Python 3.13).

To update: replace the files from a newer commit, remove those lines again if they are still there, change the commit above, and run `test_waveshare_display` (it checks the models the Display settings offer
against the files here).

`python/display/waveshare_display.py` loads one of them by name when the display is made, never at the top of a module: they import `RPi.GPIO`, `gpiozero` and `spidev`, which only a Raspberry Pi has.
