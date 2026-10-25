#!/usr/bin/env bash
# eInk Billboard in a Podman container on a Raspberry Pi 4 or 5, built from this checkout.
# Everything needed to build it, run it and find out why it does not work. Run it as yourself (not with sudo), from anywhere:
#
#   deploy/eink-container.sh update              bring it up to date on its channel: the newest version of it, its image downloaded, started (data kept)
#   deploy/eink-container.sh update --stable     follow the releases from now on (the default for a new Pi; the newest snapshot while there is no release)
#   deploy/eink-container.sh update --insider    follow the snapshots from now on: every change, a few minutes after it is made (--master is the same)
#   deploy/eink-container.sh update TAG          go to that release or snapshot and stay there (until --stable or --insider)
#   deploy/eink-container.sh get                 download the image GitHub made for this checkout; it says what to do when there is none
#   deploy/eink-container.sh build               build the image here instead, from this checkout as it is (much longer than a download)
#   deploy/eink-container.sh rollback            go back to the image that ran before the last update or build, and start it (again: forward); asks first
#   deploy/eink-container.sh start               start the app (or start it again), with the panel's devices, on port 8080 of every address of the Pi
#   deploy/eink-container.sh stop                stop it (the settings, schedules and password are kept)
#   deploy/eink-container.sh logs [-f]           the app's log (-f follows it; Ctrl+C to stop)
#   deploy/eink-container.sh code                the setup code and where to enter it, while the device is not set up
#   deploy/eink-container.sh check               when something does not work: the Pi, its devices, the container, the app, the display
#   deploy/eink-container.sh storage             when check says Podman keeps images the slow way (vfs): change it to overlay (the app's data is kept); asks first
#   deploy/eink-container.sh display TYPE [MODEL]
#                                                choose the display and restart: mock, inky, or waveshare with its model (e.g. "display waveshare epd7in3e")
#   deploy/eink-container.sh models              the Waveshare models there are drivers for
#   deploy/eink-container.sh detect              ask whether an Inky panel is attached (an Inky says what it is; a Waveshare cannot)
#   deploy/eink-container.sh autostart on|off    start the app when the Pi starts, or not (status: which it is)
#   deploy/eink-container.sh ssl on [CERT KEY]   HTTPS (the app serves it itself) and restart: with your certificate and key (PEM files, kept as Podman
#                                                secrets, not copied), else the device's own self-signed certificate (a browser warns until it is trusted)
#   deploy/eink-container.sh ssl off             plain HTTP again, and restart (a certificate you gave is kept for the next 'ssl on')
#   deploy/eink-container.sh ssl forget          remove the certificate you gave (the device's own is used while HTTPS is on); 'ssl' alone: which it is
#   deploy/eink-container.sh reset-password      forget the device password (it asks for a new setup code); asks first
#   deploy/eink-container.sh wipe                delete everything the app keeps (settings, schedules, password) and start as new; asks first
#   deploy/eink-container.sh help                this text
#
# Settings, from the environment (all optional), e.g. "EINK_PORT=8090 deploy/eink-container.sh start":
#   EINK_PORT          the port on the Pi (8080; below 1024 needs a system setting, see "start")
#   EINK_PUBLIC_URL    the address people open the web app at (http://<the Pi's address>:<port>); shown on the panel and with the setup code
#   EINK_ALLOW_HOSTS   names the app answers to besides addresses, comma separated (<hostname>,<hostname>.local)
#   EINK_API_TOKEN     a token for scripts; it also counts as setting the device up (no setup code then)
#   EINK_NAME, EINK_IMAGE, EINK_VOLUME   the container (eink), the image (localhost/eink-device), the data volume (eink-data)
#   EINK_REGISTRY      where the images GitHub made are downloaded from (ghcr.io/escape-llc/eink-billboard)
#   EINK_PULL          0: never download: get builds here instead
#   EINK_VERIFY        0: do not check a downloaded image's signature (for testing with images GitHub did not make)
#   EINK_SIGNER        the repository whose image workflow must have signed a downloaded image (escape-llc/eink-billboard)
#
# What the Pi needs: Raspberry Pi OS 64-bit, Podman (sudo apt install podman), SPI on (and I2C for an Inky panel: sudo raspi-config, Interface Options),
# and your user in the spi, i2c and gpio groups. "check" says which of these is missing and how to fix it.
# After a reboot the app starts again only with "autostart on" (the bootstrap turns it on).
# This script never prints the settings: they can hold API keys and passwords.
set -u
set -o pipefail

NAME=${EINK_NAME:-eink}
IMAGE=${EINK_IMAGE:-localhost/eink-device}
# the image that ran before the last update or build, kept for "rollback"; the one before it is left with no name, and removed
PREVIOUS="$IMAGE-previous"
REGISTRY=${EINK_REGISTRY:-ghcr.io/escape-llc/eink-billboard}
VOLUME=${EINK_VOLUME:-eink-data}
PORT=${EINK_PORT:-8080}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="deploy/eink-container.sh"
# HTTPS (#ssl): "on" or "off", remembered; the certificate a person gives is two Podman secrets, mounted for the app's user only
SSL_FILE=${XDG_CONFIG_HOME:-$HOME/.config}/eink-billboard/ssl
SECRET_CERT=${EINK_SECRET_PREFIX:-eink}-tls-cert
SECRET_KEY=${EINK_SECRET_PREFIX:-eink}-tls-key
LOG_DIR=${XDG_CACHE_HOME:-$HOME/.cache}/eink-billboard
# the channel "update" follows (#504): stable (the newest release), insider (the newest snapshot), pinned (a tag that stays) or branch (development)
CHANNEL_FILE=${XDG_CONFIG_HOME:-$HOME/.config}/eink-billboard/channel
# the panel's devices: SPI (both chip selects), I2C bus 1 (where an Inky says what it is) and the 40-pin header's GPIO chip. That is gpiochip0 on a Pi 4,
# and on a Pi 5 with a current kernel, where gpiochip4 is only a link to it: Podman does not pass a link in, and it is not needed.
DEVICES=(/dev/spidev0.0 /dev/spidev0.1 /dev/i2c-1 /dev/gpiochip0)
GROUPS_NEEDED=(spi i2c gpio)
# the app inside the image
PY=/opt/venv/bin/python
READY_SECONDS=90

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
section() { printf '\n== %s\n' "$*"; }

# ---- checks every command makes first -------------------------------------------------------------------------------------------------------------

preflight() {
	[ "$(uname -s)" = "Linux" ] || fail "this script is for the Raspberry Pi (Linux); on another computer use compose.yaml (see AGENTS.md)."
	if [ "$(id -u)" -eq 0 ]; then
		fail "do not run this with sudo or as root. Run it as your own user: $SCRIPT ${1:-help}
       (The app runs in your user's Podman; containers made as root are separate and would not see each other.)"
	fi
	command -v podman >/dev/null || fail "Podman is not installed. Install it with:  sudo apt update && sudo apt install -y podman"
	command -v curl >/dev/null || fail "curl is not installed. Install it with:  sudo apt install -y curl"
	[ -f "$HERE/Dockerfile" ] && [ -f "$HERE/python/eink-billboard.py" ] || fail "this script must stay in the deploy folder of the eInk Billboard checkout (it builds from $HERE)."
	case "$PORT" in
		''|*[!0-9]*) fail "EINK_PORT must be a number, not '$PORT'." ;;
	esac
	{ [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; } || fail "EINK_PORT must be between 1 and 65535, not $PORT."
	if [ -n "${EINK_PUBLIC_URL:-}" ]; then
		case "$EINK_PUBLIC_URL" in
			http://?*|https://?*) ;;
			*) fail "EINK_PUBLIC_URL must start with http:// or https:// and name a host, e.g. http://192.168.1.20:8080 (it is '$EINK_PUBLIC_URL')." ;;
		esac
	fi
}

podman_version_ok() {
	# 4.3 (Raspberry Pi OS Bookworm) is the oldest this was tried with
	local version major minor
	version=$(podman version --format '{{.Client.Version}}' 2>/dev/null) || return 0
	major=${version%%.*}; minor=${version#*.}; minor=${minor%%.*}
	case "$major$minor" in *[!0-9]*|'') return 0 ;; esac
	[ "$major" -gt 4 ] || { [ "$major" -eq 4 ] && [ "$minor" -ge 3 ]; }
}

running() { [ "$(podman inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; }
# the board's memory (kB, MemTotal; EINK_MEM_KB: a test's), and whether it is a small board: less than about 1 GB (a 1 GB Pi shows about 900 MB), where the app
# draws one page at a time (render_slot_count) and "update" stops the app while it downloads
board_mem_kb() { if [ -n "${EINK_MEM_KB:-}" ]; then echo "$EINK_MEM_KB"; else awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null; fi; }
small_board() { local kb; kb=$(board_mem_kb); [ -n "$kb" ] && [ "$kb" -lt 800000 ]; }
exists() { podman container exists "$NAME" 2>/dev/null; }
need_running() {
	running && return 0
	if exists; then
		say "The container '$NAME' is there but not running. Its last lines:"
		podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /'
		fail "it stopped: see the lines above, then: $SCRIPT start"
	fi
	fail "the app is not running. Start it with:  $SCRIPT start"
}

first_address() { hostname -I 2>/dev/null | awk '{print $1}'; }
public_url() {
	if [ -n "${EINK_PUBLIC_URL:-}" ]; then say "$EINK_PUBLIC_URL"; return; fi
	local address; address=$(first_address)
	say "$(scheme)://${address:-$(hostname).local}:$PORT"
}
in_group() { id -nG | tr ' ' '\n' | grep -qx "$1"; }
ssl_on() { [ "$(cat "$SSL_FILE" 2>/dev/null)" = "on" ]; }
scheme() { if ssl_on; then echo https; else echo http; fi; }
own_certificate() { podman secret inspect "$SECRET_CERT" >/dev/null 2>&1 && podman secret inspect "$SECRET_KEY" >/dev/null 2>&1; }
# -k: this asks the app on the Pi's own loopback whether it answers, which the device's own (self-signed) certificate cannot prove to curl
access_json() { if ssl_on; then curl -fsSk --max-time 5 "https://127.0.0.1:$PORT/api/access" 2>/dev/null; else curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/access" 2>/dev/null; fi; }

# waits until the app answers, or it stops, or READY_SECONDS have passed; says which
wait_ready() {
	local waited=0
	printf 'Waiting for the app to answer'
	while [ "$waited" -lt "$READY_SECONDS" ]; do
		if access_json >/dev/null; then printf ' ready.\n'; return 0; fi
		if ! running; then printf '\n'; need_running; fi
		printf '.'
		sleep 2
		waited=$((waited + 2))
	done
	printf '\n'
	say "The app did not answer in $READY_SECONDS seconds. Its last lines:"
	podman logs --tail 25 "$NAME" 2>&1 | sed 's/^/    /'
	fail "see the lines above; '$SCRIPT check' looks at everything"
}

# ---- the commands ---------------------------------------------------------------------------------------------------------------------------------

# free space where Podman keeps its images, in KB (empty when it cannot be read)
store_free_kb() { df -Pk "$(podman info --format '{{.Store.GraphRoot}}' 2>/dev/null || echo "$HOME")" 2>/dev/null | awk 'NR==2 {print $4}'; }
BUILD_NEEDS_KB=6000000
PRUNE_UNUSED_AFTER=72h

# ---- how Podman keeps its images (#552) -------------------------------------------------------------------------------------------------------------
# Podman chooses its storage driver the first time it runs and keeps it. Rootless, when the kernel's overlay cannot be used for a user and fuse-overlayfs is not
# installed, it falls back to vfs, where every layer is a full copy of all the layers under it: on a Pi, 5.7 GB written and nine minutes to unpack one image.
STORAGE_CONF=${XDG_CONFIG_HOME:-$HOME/.config}/containers/storage.conf
store_driver() { podman info --format '{{.Store.GraphDriverName}}' 2>/dev/null; }
store_empty() { [ -z "$(podman images -aq 2>/dev/null)$(podman ps -aq 2>/dev/null)$(podman volume ls -q 2>/dev/null)$(podman pod ps -q 2>/dev/null)" ]; }

# the storage.conf that gives overlay here, found by trying it in a scratch store on the same disk as Podman's own (the kernel's overlay first, then
# fuse-overlayfs); prints it, or fails when neither works. Nothing of Podman's own storage is touched.
overlay_conf() {
	local base fuse way probe run driver ways=(kernel) options
	base=${XDG_DATA_HOME:-$HOME/.local/share}
	mkdir -p "$base" || return 1
	fuse=$(command -v fuse-overlayfs 2>/dev/null)
	[ -n "$fuse" ] && ways+=("$fuse")
	for way in "${ways[@]}"; do
		# the store on the same disk as Podman's own (that is what is tried); its run-time state anywhere short (Podman refuses a runroot of more than 50 characters)
		probe=$(mktemp -d "$base/eink-overlay-probe.XXXXXX") || return 1
		run=$(mktemp -d /tmp/eink-run.XXXXXX) || { rm -rf "$probe"; return 1; }
		# a store and a database of their own: a storage.conf alone is not enough, since Podman's database remembers the driver it began with and overrides it
		options=(--root "$probe/graph" --runroot "$run" --storage-driver overlay)
		[ "$way" = kernel ] || options+=(--storage-opt "overlay.mount_program=$way")
		# the last line: fuse-overlayfs may say its version first
		driver=$(podman "${options[@]}" info --format '{{.Store.GraphDriverName}}' 2>/dev/null | tail -n 1)
		# what Podman made there belongs to the user namespace's IDs, which only it can remove
		podman unshare rm -rf "$probe" "$run" 2>/dev/null || rm -rf "$probe" "$run" 2>/dev/null
		if [ "$driver" = overlay ]; then
			printf '[storage]\ndriver = "overlay"\n'
			[ "$way" = kernel ] || printf '[storage.options.overlay]\nmount_program = "%s"\n' "$way"
			return 0
		fi
	done
	return 1
}

# writes the storage.conf that overlay_conf found; a storage.conf of the user's own is kept beside it
write_storage_conf() {
	mkdir -p "$(dirname "$STORAGE_CONF")" || return 1
	if [ -f "$STORAGE_CONF" ] && ! grep -q "written by $SCRIPT" "$STORAGE_CONF"; then
		mv "$STORAGE_CONF" "$STORAGE_CONF.before-eink" || return 1
		say "Your own $STORAGE_CONF is kept as $STORAGE_CONF.before-eink."
	fi
	{ printf '# written by %s: overlay, which was tried on this Pi and works\n' "$SCRIPT"; printf '%s\n' "$1"; } > "$STORAGE_CONF"
}

# before a download or a build: a Podman that keeps images as vfs and holds nothing yet is changed to overlay (there is nothing to lose); one that holds
# something is only warned about, since changing it deletes everything Podman holds ("storage" does that, keeping the app's data)
prefer_overlay() {
	local conf
	[ "$(store_driver)" = vfs ] || return 0
	if store_empty && conf=$(overlay_conf); then
		if podman system reset --force >/dev/null 2>&1 && write_storage_conf "$conf" && [ "$(store_driver)" = overlay ]; then
			say "Podman was set to keep images the slow way (vfs) and held nothing yet: it uses overlay now."
			return 0
		fi
	fi
	warn "Podman keeps images the slow way (vfs): every layer is a full copy, so this writes and takes far more than overlay does.
         '$SCRIPT storage' changes it to overlay and keeps the app's data."
}

# what the end of a failed build says it was, and what to do (it used to say "network or space" for everything)
build_failure_hint() {
	local log=$1
	if grep -qiE "slirp4netns|pasta|netavark|rootlessport|did not get container start message" "$log"; then
		# found on a Pi: "slirp4netns failed" at a RUN step was Podman out of room (old images and the leftovers of failed builds), not the network: pruning fixed it
		say "Podman could not start a build step. Most often it is out of room: old images and the leftovers of earlier failed builds. Try, in order:"
		say "    1. podman system prune -f --external; podman image prune -a -f     (removes unused images, all of them, and the leftovers of failed builds; the app's data is kept; the next build is slower)"
		say "    2. df -h / /var/tmp ~ /run/user/$(id -u)    (none should be nearly full)"
		say "    3. podman system migrate, then $SCRIPT build again"
		say "    4. EINK_BUILD_NETWORK=host $SCRIPT build    (builds on the Pi's own network, with nothing in between)"
	elif grep -qiE "no space left on device|ENOSPC" "$log"; then
		say "The disk is full. 'podman system df' shows what Podman holds; 'podman image prune -a' removes unused images; 'df -h / /var/tmp ~' shows where."
	elif grep -qiE "could not resolve|temporary failure in name resolution|connection (timed out|refused|reset)|network is unreachable|tls|i/o timeout" "$log"; then
		say "A download failed: the Pi's internet or a site was not answering. Try again."
	fi
}

cmd_build() {
	prefer_overlay
	podman_version_ok || warn "Podman $(podman version --format '{{.Client.Version}}' 2>/dev/null) is older than 4.3, the oldest this was tried with."
	case "$(uname -m)" in
		aarch64) ;;
		armv7l|armv6l) warn "this is a 32-bit system ($(uname -m)). The app is built for 64-bit Raspberry Pi OS; install that if the build fails." ;;
		*) warn "this is not a Raspberry Pi ($(uname -m)): the image builds, but there will be no panel to drive." ;;
	esac
	# the old image and the layers a failed build left are unused, a few GB each: remove them first (the running container's image stays), then check, so a
	# full disk is found in seconds and not after fifteen minutes of building
	local free_kb before_kb
	before_kb=$(store_free_kb)
	# the leftovers of failed builds (working containers) hold space an image prune does not free; not every Podman has --external
	podman system prune -f --external >/dev/null 2>&1 || podman image prune -f >/dev/null 2>&1
	# every build leaves its layers (the web stage, the Python stage, the base images) as images their children still use, so no plain prune frees them: 28 of them were 24 GB on a Pi.
	# Unused images older than three days go; the last few builds' layers stay, so a build after an update is still a few minutes, not twenty
	podman image prune -a -f --filter "until=$PRUNE_UNUSED_AFTER" >/dev/null 2>&1
	free_kb=$(store_free_kb)
	[ -n "$before_kb" ] && [ -n "$free_kb" ] && [ "$free_kb" -gt "$before_kb" ] && say "Removed unused images and leftovers of failed builds: $(( (free_kb - before_kb) / 1024 )) MB freed."
	if [ -n "$free_kb" ] && [ "$free_kb" -lt "$BUILD_NEEDS_KB" ]; then
		fail "the build needs about $((BUILD_NEEDS_KB / 1048576)) GB of free disk space, and there is $((free_kb / 1024)) MB (unused images and failed builds' leftovers were already removed). Free some space and try again: 'podman system df' shows what Podman holds, 'podman image prune -a' removes every image no container uses (the app's image too when it is stopped; the build makes it again)."
	fi
	mkdir -p "$LOG_DIR"
	local log="$LOG_DIR/build.log" commit
	commit=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)
	if [ "${IN_UPDATE:-0}" != 1 ]; then
		# "build" builds what is in the clone and fetches nothing: say so, and say when the clone is behind (it was run again and again, expecting the newest code)
		local branch behind
		timeout 15 git -C "$HERE" fetch -q origin >/dev/null 2>&1
		if branch=$(git -C "$HERE" symbolic-ref -q --short HEAD) && behind=$(git -C "$HERE" rev-list --count "HEAD..origin/$branch" 2>/dev/null) && [ "${behind:-0}" -gt 0 ]; then
			warn "the clone is $behind commit(s) behind '$branch' on the internet, and build uses what is here, not the newest. To get the newest code and build it:  $SCRIPT update"
		else
			say "build uses the code in the clone as it is; '$SCRIPT update' fetches the newest first."
		fi
	fi
	say "Building $IMAGE from $HERE (commit $commit)."
	say "The first build takes a long time; later ones reuse what did not change. Everything is also written to $log."
	# EINK_BUILD_NETWORK=host builds on the Pi's own network, with no slirp4netns or pasta in between: for a Pi whose container networking fails (see below)
	local network=()
	[ -z "${EINK_BUILD_NETWORK:-}" ] || network=(--network "$EINK_BUILD_NETWORK")
	keep_previous
	if ! podman build "${network[@]}" --target app-device --build-arg "EINK_COMMIT=$commit" --label "eink.commit=$commit" --label "eink.built-by=local" -t "$IMAGE" "$HERE" 2>&1 | tee "$log"; then
		say ""
		say "The last lines of the build:"
		tail -15 "$log" | sed 's/^/    /'
		build_failure_hint "$log"
		fail "the build failed (the whole of it is in $log)."
	fi
	say ""
	# "update" starts it next by itself
	if [ "${IN_UPDATE:-0}" = 1 ]; then say "Built $IMAGE (commit $commit)."; else say "Built $IMAGE (commit $commit). Start it with:  $SCRIPT start"; fi
}

# the commit an image ($1, the app's by default) was built from (its label), or "unknown"
image_commit() {
	local built
	built=$(podman image inspect -f '{{index .Labels "eink.commit"}}' "${1:-$IMAGE}" 2>/dev/null)
	case "$built" in ''|'<no value>') echo unknown ;; *) echo "$built" ;; esac
}

# who made an image ($1, the app's by default): "GitHub" (downloaded) or "this Pi" (built here; an image from before the label was built here too)
image_maker() {
	case "$(podman image inspect -f '{{index .Labels "eink.built-by"}}' "${1:-$IMAGE}" 2>/dev/null)" in
		github) echo "GitHub" ;;
		*) echo "this Pi" ;;
	esac
}

# whether a commit label ($1, short) is the clone's commit: the label is the start of the full commit (GitHub labels 7 characters; a Pi's git may use more)
same_commit() {
	local full
	full=$(git -C "$HERE" rev-parse HEAD 2>/dev/null) || return 1
	[ -n "$1" ] && [ "$1" != unknown ] && [ "${full#"$1"}" != "$full" ]
}

# the tag GitHub published this checkout's image under: its commit's (sha-<the full commit>), for a snapshot and a release alike (a release is a snapshot's
# image under another name, and the commit's name is there before the release's)
published_tag() {
	local full
	full=$(git -C "$HERE" rev-parse HEAD 2>/dev/null) || return 1
	echo "sha-$full"
}

# the image with the app's name becomes the previous one, for "rollback"; the one that was previous is left with no name, and goes with the next tidy-up
keep_previous() {
	podman image exists "$IMAGE" || return 0
	podman tag "$IMAGE" "$PREVIOUS" >/dev/null 2>&1 || warn "the image that runs now could not be kept for a rollback."
}

# images left with no name (an older app image, a build's leftovers) that no container uses are removed; the app's and the previous one keep their names, and stay
tidy_images() {
	local before_kb after_kb
	before_kb=$(store_free_kb)
	if podman image prune -f >/dev/null 2>&1; then
		after_kb=$(store_free_kb)
		[ -n "$before_kb" ] && [ -n "$after_kb" ] && [ "$after_kb" -gt "$before_kb" ] && say "Removed old images: $(( (after_kb - before_kb) / 1024 )) MB freed."
	fi
	return 0
}

# how often a download says it is still going, and how long it may write nothing before it is given up (EINK_PULL_TICK, EINK_PULL_STALL: a test's)
PULL_TICK=${EINK_PULL_TICK:-30}
PULL_STALL_SECONDS=${EINK_PULL_STALL:-300}

# the free space (KB) of the file system a path is on
free_kb_at() { df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}'; }

# `podman pull` of $1 with a plain line every PULL_TICK seconds instead of Podman's progress bars (which redraw the screen, and stand still while a layer is
# unpacked): how long, and how much has been written so far. Nothing written for PULL_STALL_SECONDS stops it (exit 124). Podman's own words go to pull.log.
pull_plainly() {
	local ref=$1 log="$LOG_DIR/pull.log" store tmp pid start_store start_tmp last now quiet=0 waited=0 written status
	mkdir -p "$LOG_DIR"
	# where the image is unpacked, and where Podman keeps the layers while they download: asked once, before the pull holds the storage
	store=$(podman info --format '{{.Store.GraphRoot}}' 2>/dev/null || echo "$HOME")
	tmp=${TMPDIR:-/var/tmp}
	start_store=$(free_kb_at "$store")
	start_tmp=$(free_kb_at "$tmp")
	last="$start_store $start_tmp"
	podman pull -q --tls-verify="${EINK_REGISTRY_TLS_VERIFY:-true}" "$ref" >"$log" 2>&1 &
	pid=$!
	# a pull in the background is not stopped by Ctrl+C on its own: stop it with the script (the number is put in now: $pid is gone when the script ends)
	# shellcheck disable=SC2064
	trap "kill $pid 2>/dev/null" EXIT
	while kill -0 "$pid" 2>/dev/null; do
		sleep "$PULL_TICK" & wait $!
		kill -0 "$pid" 2>/dev/null || break
		waited=$((waited + PULL_TICK))
		now="$(free_kb_at "$store") $(free_kb_at "$tmp")"
		if [ "$now" != "$last" ]; then quiet=0; last=$now; else quiet=$((quiet + PULL_TICK)); fi
		if [ "$quiet" -ge "$PULL_STALL_SECONDS" ]; then
			kill "$pid" 2>/dev/null
			wait "$pid" 2>/dev/null
			trap - EXIT
			return 124
		fi
		# what was written: the space taken on the storage's file system, and on the download folder's when it is another one
		written=$(( ${start_store:-0} - $(free_kb_at "$store") ))
		[ "$(df -P "$store" 2>/dev/null | awk 'NR==2 {print $1}')" = "$(df -P "$tmp" 2>/dev/null | awk 'NR==2 {print $1}')" ] \
			|| written=$(( written + ${start_tmp:-0} - $(free_kb_at "$tmp") ))
		[ "$written" -ge 0 ] || written=0
		say "  ... $((waited / 60)) min $((waited % 60)) s, $((written / 1024)) MB written so far"
	done
	wait "$pid"
	status=$?
	trap - EXIT
	return "$status"
}

# ---- the image is GitHub's, for this commit (#555) -------------------------------------------------------------------------------------------------
# image.yaml attests every image it publishes (actions/attest-build-provenance: a Sigstore signature, kept in the registry beside the image). A label says
# nothing (anyone able to push could set it), so before an image takes the app's name, cosign checks that this repository's image workflow, on master, made
# it from the clone's own commit. cosign runs from an image of its own, pinned by digest, so what checks the app is never the app.
COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign:v3.1.3@sha256:9e5c2f2edc34351160407ca3416c61855bdf9403c3c5936e0f0be7fc261611b8"
# the repository whose workflow may have made the app's image (a fork that publishes its own sets EINK_SIGNER)
SIGNER=${EINK_SIGNER:-escape-llc/eink-billboard}

# $1: a downloaded image, $2: the full commit it must have been made from. The digests are the ones Podman recorded for what it downloaded (the image index,
# which is what is attested, and the image in it), so a tag moved in the meantime cannot pass. Succeeds only when one of them is verified.
verify_image() {
	local image=$1 commit=$2 log="$LOG_DIR/verify.log" digest insecure=()
	if [ "${EINK_VERIFY:-1}" = 0 ]; then
		warn "EINK_VERIFY=0: the image's signature is not checked."
		return 0
	fi
	mkdir -p "$LOG_DIR"
	[ "${EINK_REGISTRY_TLS_VERIFY:-true}" = false ] && insecure=(--allow-insecure-registry --allow-http-registry)
	: > "$log"
	for digest in $(podman image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image" 2>/dev/null | grep -F "$REGISTRY@sha256:"); do
		# --network host: cosign only asks the registry and Sigstore, and reaches a registry on this machine as the pull did
		if podman run --rm --network host --pull=missing "$COSIGN_IMAGE" verify-attestation "${insecure[@]}" \
			--type slsaprovenance1 \
			--certificate-oidc-issuer https://token.actions.githubusercontent.com \
			--certificate-identity "https://github.com/$SIGNER/.github/workflows/image.yaml@refs/heads/master" \
			--certificate-github-workflow-repository "$SIGNER" \
			--certificate-github-workflow-sha "$commit" \
			"$digest" >>"$log" 2>&1; then
			say "Checked: $SIGNER's image workflow made it from commit ${commit::7} (its Sigstore signature)."
			return 0
		fi
	done
	return 1
}

# download the image GitHub made for this checkout and give it the app's name; fails, changing nothing, when there is none or it is not this checkout's
pull_image() {
	local tag ref made
	tag=$(published_tag) || return 1
	ref="$REGISTRY:$tag"
	say "Downloading the image GitHub made for this version ($tag), then unpacking it."
	local pulled
	pull_plainly "$ref"
	pulled=$?
	if [ "$pulled" -eq 124 ]; then
		warn "the download stopped moving (nothing was written for $((PULL_STALL_SECONDS / 60)) minutes; is the Pi's internet slow or gone?). Run it again: it starts the download again."
		return 1
	elif [ "$pulled" -ne 0 ]; then
		warn "there is no image to download for this version: GitHub makes one a few minutes after a change reaches master, and none for a branch of your own. What Podman said is in $LOG_DIR/pull.log."
		return 1
	fi
	# the image says which commit it is: it must be this checkout's, or the app and the clone would disagree
	made=$(image_commit "$ref")
	if ! same_commit "$made"; then
		warn "the downloaded image says it is commit $made, not this checkout's ($(git -C "$HERE" rev-parse --short HEAD)), so it is not used."
		# "untag IMAGE NAME" removes that one name; "untag IMAGE" alone removes every name the image has (the app's too)
		podman untag "$ref" "$ref" >/dev/null 2>&1
		return 1
	fi
	if ! verify_image "$ref" "$(git -C "$HERE" rev-parse HEAD)"; then
		warn "the downloaded image could not be shown to be GitHub's for this version (made by $SIGNER's image workflow from commit $(git -C "$HERE" rev-parse --short HEAD)), so it is not used.
         The app keeps the image it had. What cosign said is in $LOG_DIR/verify.log (it also fails when the Pi cannot reach Sigstore or download cosign: try again)."
		podman untag "$ref" "$ref" >/dev/null 2>&1
		return 1
	fi
	keep_previous
	podman tag "$ref" "$IMAGE" || { warn "the downloaded image could not be named $IMAGE."; return 1; }
	# one name only: when the next image takes the app's name, this one is left with none, and goes
	podman untag "$ref" "$ref" >/dev/null 2>&1
	say "Downloaded $IMAGE (commit $made, made by GitHub)."
	return 0
}

# the image of this checkout, downloaded: nobody should wait for a build, so one is made here only when asked for (build, or EINK_PULL=0)
cmd_get() {
	if same_commit "$(image_commit)" && podman image exists "$IMAGE"; then
		say "The image is already this checkout's (commit $(image_commit), made by $(image_maker))."
		return 0
	fi
	prefer_overlay
	if [ "${EINK_PULL:-1}" = 0 ]; then
		say "EINK_PULL=0: not downloading, building here."
		cmd_build
		return
	fi
	if pull_image; then
		tidy_images
		[ "${IN_UPDATE:-0}" = 1 ] || say "Start it with:  $SCRIPT start"
		return 0
	fi
	fail "the app was not changed: it still has the image it had (commit $(image_commit)).
       '$SCRIPT update --insider' goes to the newest version GitHub has made an image of; '$SCRIPT build' builds this one here instead (much longer than a download)."
}

# go back to the image that ran before (and "rollback" again goes forward): the two swap names, then the app starts on it
cmd_rollback() {
	podman image exists "$PREVIOUS" || fail "there is no earlier image to go back to: one is kept from the second update or build on."
	local now before swap="$IMAGE-swap"
	now=$(image_commit)
	before=$(image_commit "$PREVIOUS")
	say "The app's image is commit $now; the one before it is commit $before (made by $(image_maker "$PREVIOUS"))."
	say "Settings saved by the newer version are kept; the older one does not change what it does not know, and names it in its log and on the System page."
	confirm "This starts commit $before in place of $now. 'rollback' again goes forward." "yes"
	podman tag "$IMAGE" "$swap" && podman tag "$PREVIOUS" "$IMAGE" && podman tag "$swap" "$PREVIOUS" \
		|| fail "the images could not be swapped: 'podman images' lists them."
	podman untag "$swap" "$swap" >/dev/null 2>&1
	say "Commit $before has the app's name now; the clone stays at $(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown) ('$SCRIPT update' brings the newer one back)."
	cmd_start
}

# the newest release (v..., by version) and the newest snapshot (14 digits: its commit's time in UTC) among the clone's tags; nothing when there is none
# (the same two rules are in deploy/bootstrap.sh, for a Pi's first clone)
newest_release() { git -C "$HERE" tag -l 'v*' --sort=-v:refname | grep -E '^v[0-9A-Za-z._-]{1,100}$' | head -n 1; }
newest_snapshot() { git -C "$HERE" tag -l '[0-9]*' | grep -E '^[0-9]{14}$' | sort | tail -n 1; }

# the channel "update" follows: the one it saved; on a Pi set up before channels, what the clone follows now (master: insider; another branch: that
# branch; a tag: that tag), so nothing moves to another kind of version on its own
channel() {
	local saved
	saved=$(cat "$CHANNEL_FILE" 2>/dev/null)
	case "$saved" in stable|insider|pinned|branch) echo "$saved"; return 0 ;; esac
	if git -C "$HERE" symbolic-ref -q HEAD >/dev/null; then
		if [ "$(git -C "$HERE" symbolic-ref -q --short HEAD)" = master ]; then echo insider; else echo branch; fi
	else
		echo pinned
	fi
}

# what the clone is on, for people: its tag (a release or a snapshot) and commit, or its branch and commit
version_name() {
	local tag branch short
	short=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)
	if tag=$(git -C "$HERE" describe --tags --exact-match 2>/dev/null); then echo "$tag (commit $short)"
	elif branch=$(git -C "$HERE" symbolic-ref -q --short HEAD); then echo "branch $branch (commit $short)"
	else echo "commit $short"; fi
}

# fetch the latest code and go to the version the channel names, get its image, start it: the one command for "bring it up to date"
# ($1, optional: --stable or --insider to change the channel, a tag to go to and stay on, or a branch to follow, for development)
cmd_update() {
	local want="" follow=""
	[ $# -le 1 ] || fail "update takes one of: --stable, --insider, or the name of a release or snapshot."
	case "${1:-}" in
		"") ;;
		--stable) follow=stable ;;
		--insider|--master) follow=insider ;;
		-*) fail "there is no option '$1' for update: --stable (the releases), --insider (every change; --master is the same), or the name of a release or snapshot." ;;
		*) want=$1 ;;
	esac
	command -v git >/dev/null || fail "git is not installed. Install it with:  sudo apt install -y git"
	git -C "$HERE" rev-parse --git-dir >/dev/null 2>&1 || fail "$HERE is not a git clone, so it cannot be updated. Run the setup command again, it makes one."
	# handed over by the old copy of this script, which moved the clone to this commit: only the second half is left (an older copy, which does not know
	# this, runs a whole update again, finds the clone already there, and goes on: nothing loops)
	if [ -n "${EINK_UPDATE_HANDOVER:-}" ]; then
		local handed=$EINK_UPDATE_HANDOVER
		unset EINK_UPDATE_HANDOVER
		if [ "$handed" = "$(git -C "$HERE" rev-parse HEAD)" ]; then
			update_app
			return
		fi
	fi
	git -C "$HERE" diff --quiet && git -C "$HERE" diff --cached --quiet \
		|| fail "the clone in $HERE has changes of its own, and updating would mix them in. Undo them (git -C $HERE stash), then run it again."

	section "Getting the latest code"
	local before target="" branch before_full now
	before=$(git -C "$HERE" rev-parse --short HEAD)
	before_full=$(git -C "$HERE" rev-parse HEAD)
	# the snapshots GitHub removed go from here too, so the newest one here is one GitHub still has an image of
	git -C "$HERE" fetch -q --tags --prune --prune-tags origin || fail "the latest code could not be fetched: is the Pi on the internet?"
	if [ -n "$want" ]; then
		if git -C "$HERE" rev-parse -q --verify "refs/tags/$want^{commit}" >/dev/null 2>&1; then
			follow=pinned
			target=$want
		elif git -C "$HERE" rev-parse -q --verify "refs/remotes/origin/$want^{commit}" >/dev/null 2>&1; then
			follow=branch
			git -C "$HERE" checkout -q "$want" || fail "could not switch to '$want'."
		else
			fail "there is no release, snapshot or branch '$want'. The releases and snapshots:  git -C $HERE tag   (or '$SCRIPT update --stable' for the newest release)"
		fi
	fi
	[ -n "$follow" ] || follow=$(channel)
	case "$follow" in
		stable)
			target=$(newest_release)
			if [ -z "$target" ]; then
				target=$(newest_snapshot)
				[ -z "$target" ] || say "There is no release yet: the newest snapshot ($target) is used until there is one."
			fi ;;
		insider) target=$(newest_snapshot) ;;
		pinned) [ -n "$target" ] || target=$(git -C "$HERE" describe --tags --exact-match 2>/dev/null || true) ;;
	esac
	case "$follow" in
		stable|insider) [ -n "$target" ] || fail "GitHub has made no version to download yet (it makes one a few minutes after each change). Try again in a few minutes. Nothing was changed." ;;
	esac

	if [ "$follow" = branch ]; then
		branch=$(git -C "$HERE" symbolic-ref -q --short HEAD) || fail "the clone is on no branch: '$SCRIPT update --stable' or '--insider' gives it a channel."
		git -C "$HERE" rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null \
			|| fail "the branch '$branch' is not in the repository the clone came from, so there is nothing to update it from. Choose a channel:  $SCRIPT update --insider"
		# a branch moves on: take what is new (only forward; a clone with commits of its own is not touched)
		git -C "$HERE" merge -q --ff-only "origin/$branch" 2>/dev/null \
			|| fail "the clone cannot simply move forward to the latest '$branch' (it has commits of its own). Nothing was changed."
		warn "the branch $branch is followed as it is, for development: GitHub makes images of master's snapshots only, so a version with none is built here with '$SCRIPT build'."
	elif [ -n "$target" ] && [ "$(git -C "$HERE" rev-parse "refs/tags/$target^{commit}")" != "$(git -C "$HERE" rev-parse HEAD)" ]; then
		# going back to an older version: settings the newer one saved in a newer shape are only named by the older one, and left as they are
		if git -C "$HERE" merge-base --is-ancestor "refs/tags/$target" HEAD 2>/dev/null; then
			confirm "This goes back from $(version_name) to the older $target. Your data is kept; settings the newer version saved in a newer shape are named by the older one (log, System page) and left as they are." "yes"
		fi
		git -C "$HERE" checkout -q "refs/tags/$target" || fail "could not switch to $target."
	fi
	mkdir -p "$(dirname "$CHANNEL_FILE")"
	printf '%s\n' "$follow" > "$CHANNEL_FILE"
	case "$follow" in
		stable) say "Channel: stable (the releases). On $(version_name), was commit $before." ;;
		insider) say "Channel: insider (every change). On $(version_name), was commit $before." ;;
		pinned) say "On $(version_name), which stays: '$SCRIPT update --stable' or '--insider' follows a channel again." ;;
		branch) say "Following $(version_name), was commit $before." ;;
	esac

	# the clone now holds the new copy of this script, and the one running is the old one: the rest (the download, its check, the start) is the new copy's,
	# so a change to this script works in the update that brings it, not the one after (#561: the image check of #555 did not run in its own update)
	now=$(git -C "$HERE" rev-parse HEAD)
	if [ "$now" != "$before_full" ]; then
		EINK_UPDATE_HANDOVER=$now exec "$HERE/deploy/eink-container.sh" update
	fi
	update_app
}

# the second half of "update": the clone is where it should be; get its image (unless the app has it) and start it
update_app() {
	if same_commit "$(image_commit)" && podman image exists "$IMAGE"; then
		if running; then
			say "The app already runs this code: nothing to do."
			return 0
		fi
		say "The image is already this code's."
	elif small_board && running; then
		# the download, its unpacking and cosign's check would compete with the app and a render for the memory a small board does not have (#568); an
		# e-ink panel keeps its picture with the app stopped, so nobody sees it. Stopped, not removed: on a failure the same container starts again.
		section "Getting the app"
		say "This Pi has less than 1 GB of memory, so the app is stopped while the new version is downloaded and checked, and started again after (the panel keeps its picture)."
		podman stop -t 15 "$NAME" >/dev/null 2>&1 || fail "the app could not be stopped for the download, so nothing was changed:  podman stop $NAME"
		# Ctrl+C during the download leaves the app as it was, running
		trap 'podman start "$NAME" >/dev/null 2>&1; printf "\nStopped; the app is running again on the image it had.\n"; exit 130' INT TERM
		local got=0
		(IN_UPDATE=1 cmd_get) || got=$?
		trap - INT TERM
		if [ "$got" -ne 0 ]; then
			podman start "$NAME" >/dev/null 2>&1 || fail "the app could not be started again on the image it had:  $SCRIPT start"
			say "The app is running again on the image it had (commit $(image_commit))."
			exit 1
		fi
	else
		section "Getting the app"
		IN_UPDATE=1 cmd_get
	fi

	section "Starting"
	cmd_start

	# the new image took the app's name, the one that ran is now the previous one (for "rollback"), and the one before that has no name left: the
	# container runs the new image, so it is unused, and goes. Only unused images go; a failure here is not one for the update.
	tidy_images
}

cmd_start() {
	podman image exists "$IMAGE" || fail "there is no image yet. Get it first:  $SCRIPT get"
	if [ "$PORT" -lt 1024 ]; then
		local lowest
		lowest=$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start 2>/dev/null || echo 1024)
		[ "$PORT" -ge "$lowest" ] || fail "port $PORT needs a system setting for a container of your own:
       echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/90-eink.conf && sudo sysctl --system
       (or keep the default, 8080)."
	fi
	if exists; then
		say "Replacing the running app (its data is kept)."
		podman rm -f "$NAME" >/dev/null 2>&1 || fail "the old container '$NAME' could not be removed: podman rm -f $NAME"
	fi
	if command -v ss >/dev/null && ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$"; then
		fail "something else already uses port $PORT on this Pi. Stop it, or choose another port:  EINK_PORT=8090 $SCRIPT start"
	fi

	local url hosts devices=() missing_groups=() g
	url=$(public_url)
	hosts=${EINK_ALLOW_HOSTS:-$(hostname),$(hostname).local}
	for d in "${DEVICES[@]}"; do
		# a device of its own (not a link): what Podman can pass in
		if [ -c "$d" ] && [ ! -L "$d" ]; then devices+=(--device "$d"); fi
	done
	if [ ${#devices[@]} -eq 0 ]; then
		warn "no SPI, I2C or GPIO device was found, so only the mock display (no panel) can work. Is SPI on? '$SCRIPT check' says."
	else
		for g in "${GROUPS_NEEDED[@]}"; do in_group "$g" || missing_groups+=("$g"); done
		[ ${#missing_groups[@]} -eq 0 ] || warn "you are not in the group(s) ${missing_groups[*]}, so the app cannot use the panel. Fix:  sudo usermod -aG $(IFS=,; echo "${missing_groups[*]}") $(id -un)  then log out and in again."
		# your spi, i2c and gpio groups go into the container with you: that is what lets the app open the devices
		devices+=(--group-add keep-groups)
	fi
	local token=()
	# passed by name, so the token is not on a command line (anyone on the Pi can read those)
	[ -n "${EINK_API_TOKEN:-}" ] && token=(-e EINK_API_TOKEN)
	# HTTPS is the app's own (uvicorn): a certificate you gave is mounted as secrets that only the app's user can read, else the app makes its own
	local tls_mounts=() tls_args=() uid gid
	if ssl_on; then
		tls_args=(--ssl)
		if own_certificate; then
			uid=$(podman run --rm --network none "$IMAGE" id -u 2>/dev/null) && gid=$(podman run --rm --network none "$IMAGE" id -g 2>/dev/null) \
				|| fail "the app's user in the image could not be found, so the certificate cannot be given to it. '$SCRIPT check' looks at everything."
			tls_mounts=(--secret "$SECRET_CERT,uid=$uid,gid=$gid,mode=0400" --secret "$SECRET_KEY,uid=$uid,gid=$gid,mode=0400")
			tls_args+=(--ssl-certfile "/run/secrets/$SECRET_CERT" --ssl-keyfile "/run/secrets/$SECRET_KEY")
		fi
	fi

	if ! podman run -d --name "$NAME" --restart unless-stopped \
		-p "$PORT:8080" -v "$VOLUME:/data" \
		-e EINK_PUBLIC_URL="$url" -e EINK_ALLOW_HOSTS="$hosts" "${token[@]}" \
		"${devices[@]}" "${tls_mounts[@]}" \
		"$IMAGE" uv run --no-sync python -m python.eink-billboard --host 0.0.0.0 --port 8080 --storage /data --app /work/app/dist "${tls_args[@]}" >/dev/null; then
		fail "the app did not start: the lines above say why. '$SCRIPT check' looks at everything."
	fi
	# the container must run the image that was just built (not an older one that still has the name): the update says which code it is
	local made built_id
	made=$(podman inspect -f '{{.Image}}' "$NAME" 2>/dev/null)
	built_id=$(podman image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)
	[ -z "$made" ] || [ -z "$built_id" ] || [ "$made" = "$built_id" ] 		|| fail "the container runs another image than the one just built (the old app is still running). Remove it and start again:  podman rm -f $NAME && $SCRIPT start"
	say "Running commit $(image_commit)."
	say "Started. The web app: $url"
	wait_ready
	cmd_code
}

cmd_stop() {
	if exists; then
		podman rm -f "$NAME" >/dev/null 2>&1 || fail "it could not be stopped: podman rm -f $NAME"
		say "Stopped. The settings, schedules and password are kept (in the volume '$VOLUME'); '$SCRIPT start' starts it again."
		systemctl --user is-enabled "$UNIT_NAME" >/dev/null 2>&1 && say "(Autostart is on but has no container to start until then; '$SCRIPT autostart off' turns it off.)"
	else
		say "The app is not running."
	fi
}

cmd_logs() {
	exists || fail "the app is not running, so there is no log. Start it with:  $SCRIPT start"
	case "${1:-}" in
		'') podman logs "$NAME" 2>&1 ;;
		-f) podman logs -f "$NAME" 2>&1 ;;
		*) fail "logs takes nothing, or -f to follow it." ;;
	esac
}

cmd_code() {
	need_running
	local access
	access=$(access_json) || fail "the app does not answer yet. Wait a little, or look at its log:  $SCRIPT logs"
	if printf '%s' "$access" | grep -qE '"setupRequired": ?true'; then
		# the last code the log gave: a code is replaced (and logged again) after too many wrong ones
		local lines
		lines=$(podman logs "$NAME" 2>&1 | grep -E "Open the web app:|Setup code:" | tail -2 | sed 's/^ *//')
		if [ -n "$lines" ]; then
			say ""
			say "The device is not set up yet. Open the web app and enter the setup code to choose its password:"
			say "$lines" | sed 's/^/    /'
			say ""
		else
			fail "the device is not set up yet, but its log has no setup code. Restart it:  $SCRIPT start"
		fi
	elif printf '%s' "$access" | grep -qE '"passwordSet": ?true'; then
		say "The device is set up: open $(public_url) and sign in with its password. Forgotten: $SCRIPT reset-password"
	else
		say "The device needs no setup code (it has a token for scripts): $(public_url)"
	fi
}

cmd_check() {
	local ok=0 problems=0 g d
	note() { say "  ok    $*"; ok=$((ok + 1)); }
	problem() { say "  FIX   $*"; problems=$((problems + 1)); }
	info() { say "        $*"; }

	section "the Pi"
	info "$( { tr -d '\0' < /proc/device-tree/model; } 2>/dev/null || echo "unknown model"), $( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"), $(uname -m), kernel $(uname -r)"
	info "addresses: $(hostname -I 2>/dev/null); the web app: $(public_url)"
	if ssl_on; then
		if own_certificate; then info "HTTPS with your certificate (Podman secrets $SECRET_CERT, $SECRET_KEY)"; else info "HTTPS with the device's own self-signed certificate ('$SCRIPT logs' gives its fingerprint)"; fi
	else
		info "plain HTTP ('$SCRIPT ssl on' for HTTPS)"
	fi
	[ "$(uname -m)" = "aarch64" ] && note "64-bit" || problem "not 64-bit ($(uname -m)): install Raspberry Pi OS 64-bit"
	if podman_version_ok; then note "Podman $(podman version --format '{{.Client.Version}}' 2>/dev/null)"; else problem "Podman $(podman version --format '{{.Client.Version}}' 2>/dev/null) is older than 4.3"; fi
	local driver
	driver=$(store_driver)
	case "$driver" in
		overlay) note "Podman keeps images with overlay" ;;
		vfs) problem "Podman keeps images the slow way (vfs: every layer a full copy, far more written and far slower per update):  $SCRIPT storage  (keeps the app's data)" ;;
		*) info "Podman keeps images with ${driver:-an unknown driver}" ;;
	esac
	for g in "${GROUPS_NEEDED[@]}"; do
		if in_group "$g"; then note "you are in the $g group"; else problem "you are not in the $g group:  sudo usermod -aG $g $(id -un)  then log out and in again"; fi
	done
	local cfg=/boot/firmware/config.txt
	[ -f "$cfg" ] || cfg=/boot/config.txt
	if grep -qE "^[[:space:]]*dtparam=spi=on" "$cfg" 2>/dev/null; then note "SPI is on"; else problem "SPI is off:  sudo raspi-config  (Interface Options, SPI), then reboot"; fi
	if grep -qE "^[[:space:]]*dtparam=i2c_arm=on" "$cfg" 2>/dev/null; then note "I2C is on"; else problem "I2C is off (an Inky panel needs it):  sudo raspi-config  (Interface Options, I2C), then reboot"; fi
	# memory: a Chromium render costs about 75 to 110 MB and the app about 135 MB, so a board with less than 1 GB (a Pi Zero 2 W: 512 MB) runs with swap or not at all well
	local mem_kb swap_kb
	mem_kb=$(board_mem_kb)
	swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null)
	if [ -n "$mem_kb" ]; then
		swap_kb=${swap_kb:-0}
		if ! small_board; then
			note "memory $((mem_kb / 1024)) MB, swap $((swap_kb / 1024)) MB"
		elif [ "$swap_kb" -ge 256000 ]; then
			note "memory $((mem_kb / 1024)) MB, swap $((swap_kb / 1024)) MB"
			info "less than 1 GB of memory: the app draws one page at a time here (small boards are experimental)"
		else
			problem "only $((mem_kb / 1024)) MB of memory and $((swap_kb / 1024)) MB of swap: add swap (sudo apt install zram-tools, or raise CONF_SWAPSIZE in /etc/dphys-swapfile to 512) or the app can be stopped for lack of memory"
		fi
	fi

	section "the devices"
	for d in "${DEVICES[@]}"; do
		if [ -L "$d" ]; then info "$d is a link to $(readlink "$d") (not needed)"
		elif [ -c "$d" ]; then note "$d ($(stat -c '%G' "$d") group)"
		else problem "$d is missing (is SPI/I2C on? then reboot)"; fi
	done

	section "the app"
	info "the code: $(version_name), on the $(channel) channel ('$SCRIPT update --stable' or '--insider' changes it)"
	if podman image exists "$IMAGE"; then
		local built
		built=$(image_commit)
		local checkout
		checkout=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)
		note "image $IMAGE, made by $(image_maker) $(podman image inspect -f '{{.Created}}' "$IMAGE" | cut -c1-16) from commit $built"
		if podman image exists "$PREVIOUS"; then
			note "the image before it (for '$SCRIPT rollback'): commit $(image_commit "$PREVIOUS"), made by $(image_maker "$PREVIOUS")"
		fi
		if same_commit "$built"; then
			note "the image is this checkout's commit"
		elif [ "$built" = unknown ] || [ "$checkout" = unknown ]; then
			info "cannot tell whether the image is this checkout's commit ($checkout); to be sure: '$SCRIPT update'"
		else
			# not a fault (the app runs as built), but the clone has moved on since: what runs is not what is checked out
			info "this checkout is at commit $checkout, the image at $built: to run the checkout, '$SCRIPT update'"
		fi
	else
		problem "no image yet:  $SCRIPT update"
	fi
	if ! running; then
		if exists; then
			problem "the app stopped. Its last lines:"
			podman logs --tail 15 "$NAME" 2>&1 | sed 's/^/        /'
		else
			problem "the app is not running:  $SCRIPT start"
		fi
		say ""
		say "$ok fine, $problems to fix."
		return
	fi
	note "running"
	if access_json >/dev/null; then note "answers on port $PORT"; else problem "does not answer on port $PORT (look at:  $SCRIPT logs)"; fi
	# what the app sees from inside: its lines start with "ok" or "FIX" (read here, not in a pipe, so the counts are kept)
	local inside line
	inside=$(podman exec -i "$NAME" "$PY" - "${DEVICES[@]}" 2>&1 <<'EOF'
import os, shutil, sys
# the app's code is in /work; importing lgpio moves the working directory (to LG_WD), so the path is set here, not left to the working directory
sys.path.insert(0, "/work")
for path in sys.argv[1:]:
	if not os.path.exists(path):
		continue
	try:
		os.close(os.open(path, os.O_RDWR))
		print("ok the app can open", path)
	except OSError as e:
		print("FIX the app cannot open", path, "(" + (e.strerror or type(e).__name__) + "): are you in its group? then  start  again")
for module in ("inky", "spidev", "smbus2", "gpiod", "gpiozero", "lgpio"):
	try:
		__import__(module)
		print("ok driver library", module)
	except Exception as e:
		print("FIX driver library", module, "does not load (" + type(e).__name__ + "): build the image again")
print("ok the page renderer is there" if shutil.which("chromium-headless-shell") else "FIX the page renderer (chromium) is missing: build the image again")
from python.model.configuration_manager import ConfigurationManager
_, doc = ConfigurationManager(storage_path="/data").settings_manager().open("display").get()
doc = doc or {}
kind = doc.get("display_type")
print("display chosen:", kind, ("model " + str(doc.get("model"))) if kind == "waveshare" else "")
EOF
)
	while IFS= read -r line; do
		case "$line" in
			"ok "*) note "${line#ok }" ;;
			"FIX "*) problem "${line#FIX }" ;;
			*) info "$line" ;;
		esac
	done <<< "$inside"
	cmd_code | sed 's/^/        /'

	local auto
	if auto=$(cmd_autostart status); then note "autostart $auto"; else info "autostart $auto"; fi
	local detected
	detected=$(cmd_detect); info "$detected"

	section "the display, from the log"
	local shown
	shown=$(display_lines)
	say "$shown" | sed 's/^/        /'
	case "$shown" in *"DID NOT START"*) problems=$((problems + 1)) ;; esac
	say ""
	if [ "$problems" -eq 0 ]; then say "$ok fine, nothing to fix."; else say "$ok fine, $problems to fix (the lines marked FIX)."; fi
}

# what the display did at its last start, from the log: which one was loaded and whether it started (in the app's words, no traceback); $1: since when (optional)
display_lines() {
	local line time summary=()
	while IFS= read -r line; do
		time=${line%% *}
		case "$line" in
			*"Starting EInk Billboard"*)
				# the app started (again): what came before belongs to an older start
				summary=() ;;
			*"Loading display "*)
				summary+=("$time  loaded the display: ${line##*Loading display }") ;;
			*"ConfigureNotify display False"*)
				summary+=("$time  the display started") ;;
			*"ConfigureNotify display True "*)
				line=${line##*ConfigureNotify display True }
				summary+=("$time  THE DISPLAY DID NOT START: ${line%.}") ;;
		esac
	done < <(podman logs ${1:+--since "$1"} "$NAME" 2>&1 | grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}' | grep -E "Starting EInk Billboard|Loading display |ConfigureNotify display ")
	[ ${#summary[@]} -eq 0 ] && summary=("(nothing about the display in the log yet)")
	printf '%s\n' "${summary[@]}"
}

models() { find "$HERE/python/display/waveshare_epd" -maxdepth 1 -name 'epd[0-9]*.py' -printf '%f\n' | sed 's/\.py$//' | sort; }

cmd_models() {
	say "Waveshare models there are drivers for (the name on the panel's box or wiki page, e.g. 7.3inch e-Paper HAT (E) is epd7in3e):"
	models | pr -4 -t -w 100
}

cmd_display() {
	local kind=${1:-} model=${2:-}
	case "$kind" in
		mock|inky)
			[ -z "$model" ] || fail "only a Waveshare display takes a model." ;;
		waveshare)
			if [ -z "$model" ]; then cmd_models; fail "a Waveshare display needs its model, e.g.  $SCRIPT display waveshare epd7in3e"; fi
			models | grep -qx "$model" || { cmd_models; fail "'$model' is not one of the models above."; } ;;
		*) fail "say which display:  $SCRIPT display mock  |  $SCRIPT display inky  |  $SCRIPT display waveshare MODEL" ;;
	esac
	need_running
	# through the app's own settings code (a safe save that checks nobody changed them meanwhile), never by editing the file
	podman exec -i "$NAME" "$PY" - "$kind" "$model" <<'EOF' || fail "the display was not changed: the lines above say why."
import sys
sys.path.insert(0, "/work")
from python.model.configuration_manager import ConfigurationManager
kind, model = sys.argv[1], sys.argv[2]
cob = ConfigurationManager(storage_path="/data").settings_manager().open("display")
rev, doc = cob.get()
doc = dict(doc or {})
doc["display_type"] = kind
if model:
	doc["model"] = model
saved, _ = cob.save(rev, doc)
if not saved:
	sys.exit("The display settings were being changed at the same moment: run it again.")
print("The display is now:", kind, model)
EOF
	say "Restarting the app to load it..."
	local since
	since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
	podman restart "$NAME" >/dev/null || fail "the app did not restart:  $SCRIPT start"
	wait_ready
	say "The display:"
	display_lines "$since" | sed 's/^/    /'
}

# asks the I2C bus whether an Inky panel is attached (it says what it is from a small memory chip on the board): prints what answered;
# returns 0 for an Inky, 3 for none, 4 when it could not tell (no I2C device in the container, the app not running)
cmd_detect() {
	running || { say "The app is not running, so the panel cannot be asked:  $SCRIPT start"; return 4; }
	podman exec "$NAME" test -e /dev/i2c-1 2>/dev/null || { say "The app has no I2C bus (is I2C on? '$SCRIPT check' says), so an Inky cannot be detected."; return 4; }
	local answer
	answer=$(podman exec -i "$NAME" "$PY" - 2>&1 <<'EOF'
import sys
sys.path.insert(0, "/work")
try:
	from inky.eeprom import read_eeprom
	found = read_eeprom()
except Exception as e:
	print("error", type(e).__name__)
	sys.exit(4)
if found is None:
	print("none")
	sys.exit(3)
print("inky", found.get_variant(), f"{found.width}x{found.height}")
EOF
)
	local status=$?
	case "$status" in
		0) say "An Inky panel answered: ${answer#inky }." ;;
		3) say "No Inky panel answered on the I2C bus (none attached, or not seated on the pins)." ;;
		*) say "Could not ask the I2C bus (${answer:-no answer})." ; status=4 ;;
	esac
	return "$status"
}

UNIT_NAME=eink-billboard.service
unit_file() { say "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT_NAME"; }

# start at boot: a unit of your own (systemd --user) that starts the container, and "linger", which runs your units at boot without a login
cmd_autostart() {
	case "${1:-status}" in
		on)
			exists || fail "start the app first (the unit starts the container 'start' made):  $SCRIPT start"
			[ -n "${XDG_RUNTIME_DIR:-}" ] && systemctl --user show-environment >/dev/null 2>&1 \
				|| fail "your user's systemd is not reachable from this shell (logged in with su or sudo?). Log in as $(id -un) directly (or over ssh) and run it again."
			mkdir -p "$(dirname "$(unit_file)")"
			cat > "$(unit_file)" <<EOF
# made by $SCRIPT autostart on: starts the eInk Billboard container when the Pi starts
[Unit]
Description=eInk Billboard (the Podman container $NAME)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$(command -v podman) start $NAME
ExecStop=$(command -v podman) stop -t 15 $NAME

[Install]
WantedBy=default.target
EOF
			systemctl --user daemon-reload && systemctl --user enable "$UNIT_NAME" >/dev/null 2>&1 || fail "the unit could not be enabled:  systemctl --user status $UNIT_NAME"
			if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
				say "Your units run at boot only with 'linger' on; turning it on (sudo asks for your password):"
				sudo loginctl enable-linger "$(id -un)" || fail "linger is not on, so the app will not start at boot:  sudo loginctl enable-linger $(id -un)"
			fi
			say "The app now starts when the Pi starts." ;;
		off)
			systemctl --user disable "$UNIT_NAME" >/dev/null 2>&1
			rm -f "$(unit_file)"
			systemctl --user daemon-reload >/dev/null 2>&1
			say "The app no longer starts when the Pi starts (it keeps running now; '$SCRIPT stop' stops it)." ;;
		status)
			if systemctl --user is-enabled "$UNIT_NAME" >/dev/null 2>&1; then
				if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" = "yes" ]; then say "on: the app starts when the Pi starts."
				else say "the unit is on, but linger is off, so it does not start at boot:  sudo loginctl enable-linger $(id -un)"; return 1; fi
			else
				say "off: the app does not start when the Pi starts ('$SCRIPT autostart on')."; return 1
			fi ;;
		*) fail "autostart takes on, off or status." ;;
	esac
}

confirm() {
	# $1: what will happen; $2: the word to type
	say "$1"
	[ -t 0 ] || fail "this needs a yes from a person at the keyboard."
	local answer
	read -r -p "Type $2 to go on (anything else stops): " answer
	[ "$answer" = "$2" ] || fail "nothing was changed."
}

cmd_reset_password() {
	need_running
	confirm "This forgets the device password. Until someone enters the new setup code (shown next) and chooses a password, the device shows nothing else." "yes"
	podman exec "$NAME" "$PY" -m python.eink-billboard --storage /data --reset-password || fail "the password was not forgotten: the lines above say why."
	podman restart "$NAME" >/dev/null || fail "the app did not restart:  $SCRIPT start"
	wait_ready
	cmd_code
}

# Podman keeps images as vfs: change it to overlay. That needs "podman system reset", which deletes everything Podman holds, so the app's data is saved to a
# file first (and checked), put back after, and the app is downloaded again and started if it was running.
cmd_storage() {
	local driver conf backup was_running=0 others
	driver=$(store_driver)
	[ -n "$driver" ] || fail "Podman did not say how it keeps images: 'podman info' says why."
	if [ "$driver" != vfs ]; then
		say "Podman keeps images with $driver: nothing to change."
		return 0
	fi
	section "Podman keeps images the slow way (vfs)"
	say "Every layer of an image is a full copy of all the layers under it, so an update writes and takes far more than it needs to. Overlay keeps each layer once."
	conf=$(overlay_conf) || fail "overlay does not work for your user on this Pi, so nothing was changed. Install fuse-overlayfs and run this again:
       sudo apt-get install -y fuse-overlayfs && $SCRIPT storage"
	backup="$HOME/eink-data-$(date +%Y%m%d-%H%M%S).tar"
	others=$(podman volume ls -q 2>/dev/null | grep -cvx "$VOLUME")
	say ""
	say "This needs 'podman system reset', which deletes ALL of your Podman images, containers and volumes."
	say "  - The app's data (the volume '$VOLUME': settings, API keys, schedules, password) is saved to $backup first, checked, and put back after."
	[ "$others" -eq 0 ] || say "  - $others other volume(s) of yours are NOT saved: 'podman volume ls' lists them; stop here and export them first if you need them."
	say "  - The app is downloaded again and started if it is running now. The image kept for '$SCRIPT rollback' is not kept."
	confirm "" "reset"
	running && was_running=1
	exists && { podman rm -f "$NAME" >/dev/null 2>&1 || fail "the app could not be stopped, so nothing was reset: podman rm -f $NAME"; }
	if podman volume exists "$VOLUME"; then
		podman volume export "$VOLUME" -o "$backup" || fail "the app's data could not be saved, so nothing was reset: podman volume export $VOLUME -o $backup"
		tar -tf "$backup" >/dev/null 2>&1 || fail "the saved data in $backup cannot be read back, so nothing was reset."
		say "Saved the app's data to $backup ($(du -h "$backup" | cut -f1))."
	else
		backup=""
		say "There is no volume '$VOLUME' yet: no data to save."
	fi
	local safe=""
	[ -z "$backup" ] || safe=" The app's data is safe in $backup; once Podman works, put it back with:  podman volume create $VOLUME && podman volume import $VOLUME $backup"
	podman system reset --force >/dev/null 2>&1 || fail "podman system reset failed: 'podman system reset' says why.$safe"
	write_storage_conf "$conf" || fail "$STORAGE_CONF could not be written.$safe"
	driver=$(store_driver)
	[ "$driver" = overlay ] || warn "Podman says it keeps images with '${driver:-nothing}', not overlay: '$SCRIPT check' and 'podman info' say more. The data is put back all the same."
	if [ -n "$backup" ]; then
		{ podman volume create "$VOLUME" >/dev/null && podman volume import "$VOLUME" "$backup"; } \
			|| fail "the app's data could not be put back. It is safe in $backup:  podman volume create $VOLUME; podman volume import $VOLUME $backup"
		say "Put the app's data back into the volume '$VOLUME'."
	fi
	say "Podman keeps images with ${driver:-?} now."
	IN_UPDATE=1 cmd_get
	[ "$was_running" -eq 0 ] || cmd_start
	[ -z "$backup" ] || say "The saved copy $backup holds your settings, API keys included: delete it once the app works:  rm $backup"
}

cmd_wipe() {
	confirm "This DELETES everything the app keeps: its settings (API keys too), playlists, schedules and password (the volume '$VOLUME'). It cannot be undone." "$VOLUME"
	podman rm -f "$NAME" >/dev/null 2>&1
	if podman volume exists "$VOLUME"; then
		podman volume rm "$VOLUME" >/dev/null || fail "the volume '$VOLUME' could not be deleted: podman volume rm $VOLUME"
	fi
	say "Deleted. '$SCRIPT start' starts it as a new device (with a new setup code)."
}

cmd_ssl() {
	case "${1:-status}" in
		on)
			if [ $# -eq 3 ]; then
				local cert=$2 key=$3
				[ -r "$cert" ] && [ -r "$key" ] || fail "both files must be there and readable by you: $cert and $key"
				grep -q "BEGIN CERTIFICATE" "$cert" || fail "$cert is not a certificate in PEM form (it starts with -----BEGIN CERTIFICATE-----)."
				grep -q "PRIVATE KEY" "$key" || fail "$key is not a private key in PEM form (-----BEGIN PRIVATE KEY----- or similar; without a passphrase)."
				grep -q "ENCRYPTED" "$key" && fail "$key has a passphrase; the app needs it without one (openssl pkey -in $key -out key.pem)."
				# a secret in use cannot be replaced: the container goes first, and start makes it again
				if exists; then podman rm -f "$NAME" >/dev/null 2>&1 || fail "the running app could not be stopped to change its certificate: podman rm -f $NAME"; fi
				podman secret rm "$SECRET_CERT" "$SECRET_KEY" >/dev/null 2>&1
				podman secret create "$SECRET_CERT" "$cert" >/dev/null && podman secret create "$SECRET_KEY" "$key" >/dev/null \
					|| fail "the certificate could not be kept as Podman secrets: podman secret ls"
				say "Kept your certificate and key as the Podman secrets $SECRET_CERT and $SECRET_KEY (you may delete the files you gave)."
			elif [ $# -ne 1 ]; then
				fail "ssl on takes nothing (the device's own certificate, or the one you gave before), or a certificate and its key:  $SCRIPT ssl on cert.pem key.pem"
			fi
			mkdir -p "$(dirname "$SSL_FILE")" && echo on > "$SSL_FILE" || fail "$SSL_FILE could not be written."
			if own_certificate; then say "HTTPS with your certificate."; else say "HTTPS with the device's own certificate: a browser warns the first time (it is self-signed); compare the fingerprint '$SCRIPT logs' gives with the one the browser shows, then accept it."; fi
			cmd_start ;;
		off)
			mkdir -p "$(dirname "$SSL_FILE")" && echo off > "$SSL_FILE" || fail "$SSL_FILE could not be written."
			say "Plain HTTP again."
			cmd_start ;;
		forget)
			own_certificate || { say "There is no certificate of yours to forget."; return; }
			if exists; then podman rm -f "$NAME" >/dev/null 2>&1 || fail "the running app could not be stopped: podman rm -f $NAME"; fi
			podman secret rm "$SECRET_CERT" "$SECRET_KEY" >/dev/null 2>&1 || fail "the secrets could not be removed: podman secret rm $SECRET_CERT $SECRET_KEY"
			say "Your certificate is forgotten."
			if ssl_on; then say "HTTPS goes on with the device's own certificate."; fi
			cmd_start ;;
		status)
			if ! ssl_on; then say "Plain HTTP. '$SCRIPT ssl on' for HTTPS."
			elif own_certificate; then say "HTTPS with your certificate (Podman secrets $SECRET_CERT, $SECRET_KEY)."
			else say "HTTPS with the device's own self-signed certificate."; fi ;;
		*) fail "ssl takes on, on CERT KEY, off, forget, or nothing (which it is)." ;;
	esac
}

cmd_help() { sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

command=${1:-help}
case "$command" in
	help|-h|--help) cmd_help; exit 0 ;;
esac
preflight "$command"
shift
case "$command" in
	build) cmd_build ;;
	get) cmd_get ;;
	update) cmd_update "$@" ;;
	rollback) cmd_rollback ;;
	start|restart) cmd_start ;;
	stop) cmd_stop ;;
	logs) cmd_logs "$@" ;;
	code) cmd_code ;;
	check) cmd_check ;;
	display) cmd_display "$@" ;;
	models) cmd_models ;;
	detect) cmd_detect ;;
	autostart) cmd_autostart "$@" ;;
	ssl) cmd_ssl "$@" ;;
	reset-password) cmd_reset_password ;;
	storage) cmd_storage ;;
	wipe) cmd_wipe ;;
	*) say "There is no command '$command'."; say ""; cmd_help; exit 2 ;;
esac
