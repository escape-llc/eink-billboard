# The Pi's command line

The commands of `deploy/eink-container.sh`, the one script a Raspberry Pi needs after the setup ([readme](../readme.md)).

Everything after the setup is one script in the clone, [`deploy/eink-container.sh`](../deploy/eink-container.sh). Run it as yourself, not with `sudo`, from any folder:

```
~/eink-billboard/deploy/eink-container.sh COMMAND [ARGUMENTS]
```

Every command first checks the basics (Linux, not root, Podman and curl installed, run from the clone, a valid port and address) and stops with what to do when one is wrong. Nothing it prints contains the app's settings, which can hold API keys and passwords.

## Commands

| Command | What it does |
|---|---|
| `help` | Lists the commands and settings. |
| `update` | **Brings it up to date on its channel:** fetches the latest code into the clone, goes to the channel's newest version (the readme's [Update](../readme.md#update)), gets its image (`get`) and starts it (your data is kept); the image that ran before is kept for `rollback`, and older ones are removed. When nothing is new and the app already runs it, it says so and does nothing. On a board with less than 1 GB of memory it stops the app while the new version is downloaded and checked, so they do not compete for memory (the panel keeps its picture), and starts it again after: on the new version, or on the one it had when the download or the check fails or you press Ctrl+C. Refuses when the clone has changes of your own. `update --stable` and `update --insider` (or `--master`) change the channel; `update NAME` goes to that release or snapshot and stays; going back to an older version asks you to type `yes`. `update BRANCH` follows a branch of `master`'s repository as it is, for development (it has no images: `build`). |
| `get` | **Gets the image of the clone's code**: downloads the one GitHub made for that exact commit (`ghcr.io/escape-llc/eink-billboard:sha-<commit>`, for a release too: a release is a snapshot's image under another name), checks that its label names the clone's commit, **checks its signature** (GitHub signs every image it publishes; cosign, run from its own image pinned by digest, must find that this repository's image workflow on `master` made it from the clone's exact commit, or the image is not used and the app keeps the one it had; `EINK_VERIFY=0` skips the check, `EINK_SIGNER` names a fork's repository), and names it `localhost/eink-device`. When there is none (GitHub makes it a few minutes after a change reaches `master`, and removes the images of all but the few newest snapshots; there is none for a branch of your own or a machine that is not 64-bit ARM), it says so and what to do (`update --insider` for the newest version GitHub has made, or `build`), and **builds nothing**: the app keeps the image it had. `EINK_PULL=0` builds instead of downloading. While it downloads it prints a plain line every 30 seconds (how long it has run and how much it has written so far) instead of Podman's progress bars, which redraw the screen and stand still while a layer is unpacked; Podman's own words go to `~/.cache/eink-billboard/pull.log`. When nothing has been written for 5 minutes, the download is stopped (`update` again tries it again); Ctrl+C stops the download too. |
| `build` | Builds the app's image (`localhost/eink-device`) from the clone as it is, without pulling anything (`update` pulls). It looks at the internet only to say so when the clone is behind (`WARNING: the clone is 3 commit(s) behind`, with the command to use): much longer than a download the first time, less after an update, since it reuses what did not change. Removes unused images and the leftovers of failed builds first (`podman system prune --external`, then every unused image older than three days, because the layers of each build otherwise pile up; the running app and its data are kept), then checks for about 6 GB of free space, so a full disk is found in seconds; records the commit it was built from, and writes everything to `~/.cache/eink-billboard/build.log`; on failure it shows the end of that log and says what it was: Podman failing to start a step (`slirp4netns failed` is usually Podman out of room, not the network: try `podman system prune -f --external`, then `podman system migrate`, or `EINK_BUILD_NETWORK=host build`), a full disk, or a download that did not answer. |
| `start` | Starts the app (or replaces the running one; the data is kept) on port 8080 of every address of the Pi, IPv4 and IPv6 (the container uses the Pi's own network). Passes in the panel's devices that exist (`/dev/spidev0.0`, `/dev/spidev0.1`, `/dev/i2c-1`, `/dev/gpiochip0`) with your `spi`, `i2c` and `gpio` groups, and `/dev/snd` as a folder for a USB sound card (an audio output; a card plugged in later is seen after a `restart`), warns when a group is missing, refuses a port that is already in use, waits up to 90 seconds for the app to answer (showing its last log lines if it stops), then prints the setup code. Also `restart`. |
| `stop` | Stops and removes the container. The settings, playlists and password are kept, in the volume `eink-data`. |
| `logs` | The app's log; `logs -f` follows it (Ctrl+C to stop). |
| `code` | The address and the setup code while the device is not set up, otherwise that it is set up (or needs no code because of a token). |
| `rollback` | Goes back to the image that ran before the last `update`, `get` or `build`, and starts it; `rollback` again goes forward. Asks first. Your data is kept; settings the newer version saved in a newer shape are named by the older one (log, System page) and left as they are. |
| `check` | The troubleshooting report: the Pi (whether its network keeps IPv6 after a drop, 64-bit, Podman version, groups, SPI, I2C, memory and swap: in memory (zram) or on the card, the kernel's memory accounting, the free space an update needs), the devices, the image, who made it (GitHub or this Pi) and the commit it came from (compared with the clone), the image `rollback` would go back to, whether the app answers, which devices it can open and which driver libraries load inside the container, the chosen display, the setup state, start-at-boot, whether an Inky answers, and what the display said when the app last started. Ends with how many things are fine and how many to fix. |
| `display mock` | No panel: the pages are drawn but not shown. Saves the choice through the app's own settings and restarts the app, then shows whether the display started. |
| `display inky` | A Pimoroni Inky (it says which one it is). An Inky's driver works the panel's chip select (GPIO 8) itself, so it needs `dtoverlay=spi0-0cs` in `/boot/firmware/config.txt`; the setup adds it (and removes it for a Waveshare panel, which needs the kernel's), and `display` and `check` say when it does not match. |
| `display waveshare MODEL` | A Waveshare panel; the model is checked against the drivers (`models`). |
| `models` | The Waveshare models there are drivers for, e.g. `epd7in3e` for the 7.3 inch e-Paper HAT (E). |
| `detect` | Asks the I2C bus whether an Inky is attached (a read only). Exit status 0: an Inky answered; 3: none did; 4: it could not ask (the app is not running, or I2C is off). |
| `autostart on` | Starts the app when the Pi starts: a systemd unit of your own (`~/.config/systemd/user/eink-billboard.service`) that waits until the Pi has a name server (at most 2 minutes: on the Pi's own network the container copies its DNS settings when it starts), then starts the container, or makes it again with `start` when Podman refuses it (a device it was made with is gone, e.g. `/dev/spidev0.1` after `dtoverlay=spi0-0cs`), and *linger*, which runs your units at boot without a login (asks for your password once). Needs the container to exist (`start` first). |
| `autostart off` | No longer starts at boot (the app keeps running now). |
| `autostart` | Whether it starts at boot (`status`). |
| `ssl on` | **HTTPS**, served by the app itself on the same port, with the device's own self-signed certificate (or the one you gave before). Kept in the settings (`EINK_SSL=1`) and restarts the app; `start` and `update` keep it. A browser warns the first time: the log's line "Serving HTTPS with ..." gives the certificate's SHA-256 fingerprint to compare. |
| `ssl on CERT KEY` | HTTPS with a certificate of your own: two PEM files (the certificate with its chain, and its key without a passphrase), kept as the Podman secrets `eink-tls-cert` and `eink-tls-key` and mounted for the app's user only (mode 0400); the files themselves can be deleted afterwards. Giving another replaces them. |
| `ssl off` | Plain HTTP again, and restarts the app; a certificate you gave is kept for the next `ssl on`. |
| `ssl forget` | Removes the certificate you gave (the secrets); while HTTPS is on the device's own is used. `ssl` alone says which is in use. |
| `settings` | The settings this Pi keeps (below): the port, the address, the other names, HTTPS, and whether there is a token for scripts (never its value). |
| `settings ask` | Asks them again, as the setup did, keeps the answers and restarts the app with them. Needs someone at the keyboard. |
| `settings edit` | Opens the settings file in your editor (`$EDITOR`, else nano), then restarts the app with it. Any setting the app reads can go in it. |
| `token new` | Makes a token for scripts (48 random hex characters), keeps it in the settings, shows it once and restarts the app with it. A script sends it as `Authorization: Bearer <the token>` (the web app's Help, Pushing a message from a script). A token also counts as setting the device up: the web app's first sign-in is the token. |
| `token show` | Shows the token again. |
| `token off` | Removes it and restarts: scripts are refused (with no device password set yet, the device asks for a setup code again). `token` alone says whether there is one. |
| `storage` | When `check` says Podman keeps images the slow way (`vfs`: every layer a full copy, so every update writes and takes far more than it needs to), changes it to overlay. That needs `podman system reset`, which deletes all of your Podman images, containers and volumes, so it first tries overlay in a scratch store and stops with nothing changed if it does not work, then saves the app's data to a file in your home folder, checks it, puts it back after and downloads the app again. Asks you to type `reset` first. (`get` does this by itself when Podman holds nothing yet.) |
| `reset-password` | Forgets the device password, restarts and shows the new setup code. Asks you to type `yes` first. |
| `wipe` | Deletes everything the app keeps (settings with their API keys, playlists, schedules, password) and the container, so the next `start` is a new device. Asks you to type the volume's name (`eink-data`) first. |

`reset-password` and `wipe` refuse to run without someone at the keyboard to answer.

## Settings

Kept in `~/.config/eink-billboard/eink.env`, one `NAME=value` a line, readable only by you (it holds the token). The setup asks for them the first time; `settings ask`, `settings edit`, `token` and `ssl` change them; every `start`, `update` and start at boot uses them (Podman hands the whole file to the app, so any setting the app reads can go in it, such as `EINK_LOG_LEVEL=DEBUG`). One given in the environment wins for that one command (`EINK_PORT=8090 ~/eink-billboard/deploy/eink-container.sh start`):

| Setting | Default | What it is |
|---|---|---|
| `EINK_PORT` | `8080` | The port on the Pi. Below 1024 needs a system setting, which `start` explains |
| `EINK_PUBLIC_URL` | `http://<the Pi's address>:<port>` (`https://` with `ssl on`) | The address people open the web app at (see [On your network](../readme.md#on-your-network)) |
| `EINK_ALLOW_HOSTS` | `<name>,<name>.local` | Names the app answers to besides addresses |
| `EINK_SSL` | none | `1`: HTTPS (`ssl on`) |
| `EINK_API_TOKEN` | none | A token for scripts (`token new`) |

The kit's own, from the environment only:

| Setting | Default | What it is |
|---|---|---|
| `EINK_NAME` | `eink` | The container's name |
| `EINK_IMAGE` | `localhost/eink-device` | The image's name |
| `EINK_VOLUME` | `eink-data` | The volume that holds the app's data |

## The setup command's options

The setup (`deploy/bootstrap.sh`) can be run again at any time; these change how it runs (after `| bash -s --`, e.g. `curl ... | bash -s -- --dry-run`):

| Option or setting | What it does |
|---|---|
| `--dry-run` | Shows what it would do, changes nothing |
| `--yes` | Asks nothing: goes ahead, and the display is `EINK_DISPLAY` (or the last choice, or none) |
| `--help` | Its description |
| `EINK_DISPLAY` | The display without asking: `mock`, `inky`, or `waveshare:MODEL` (e.g. `waveshare:epd7in3e`) |
| `--stable`, `--insider` | The channel to follow (the default: stable, or the one the Pi has; `--master` is insider) |
| `EINK_CHANNEL` | The same, `stable` or `insider` |
| `EINK_REF` | A branch or tag to install instead of a channel's newest version |
| `EINK_DIR` | Where the app is cloned (`~/eink-billboard`) |
| `EINK_REPO` | The repository to clone |

It remembers the display you chose in `~/.config/eink-billboard/display` and offers it next time.
