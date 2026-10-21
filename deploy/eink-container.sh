#!/usr/bin/env bash
# eInk Billboard in a Podman container on a Raspberry Pi 4 or 5, built from this checkout.
# Everything needed to build it, run it and find out why it does not work. Run it as yourself (not with sudo), from anywhere:
#
#   deploy/eink-container.sh update [TAG]        bring it up to date: fetch the latest code, build it, start it (data kept); TAG switches to that release
#   deploy/eink-container.sh build               build the image from this checkout as it is (15 to 20 minutes the first time, a few after a change)
#   deploy/eink-container.sh start               start the app (or start it again), with the panel's devices, on port 8080 of every address of the Pi
#   deploy/eink-container.sh stop                stop it (the settings, schedules and password are kept)
#   deploy/eink-container.sh logs [-f]           the app's log (-f follows it; Ctrl+C to stop)
#   deploy/eink-container.sh code                the setup code and where to enter it, while the device is not set up
#   deploy/eink-container.sh check               when something does not work: the Pi, its devices, the container, the app, the display
#   deploy/eink-container.sh display TYPE [MODEL]
#                                                choose the display and restart: mock, inky, or waveshare with its model (e.g. "display waveshare epd7in3e")
#   deploy/eink-container.sh models              the Waveshare models there are drivers for
#   deploy/eink-container.sh detect              ask whether an Inky panel is attached (an Inky says what it is; a Waveshare cannot)
#   deploy/eink-container.sh autostart on|off    start the app when the Pi starts, or not (status: which it is)
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
#
# What the Pi needs: Raspberry Pi OS 64-bit, Podman (sudo apt install podman), SPI on (and I2C for an Inky panel: sudo raspi-config, Interface Options),
# and your user in the spi, i2c and gpio groups. "check" says which of these is missing and how to fix it.
# After a reboot the app starts again only with "autostart on" (the bootstrap turns it on).
# This script never prints the settings: they can hold API keys and passwords.
set -u
set -o pipefail

NAME=${EINK_NAME:-eink}
IMAGE=${EINK_IMAGE:-localhost/eink-device}
VOLUME=${EINK_VOLUME:-eink-data}
PORT=${EINK_PORT:-8080}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="deploy/eink-container.sh"
LOG_DIR=${XDG_CACHE_HOME:-$HOME/.cache}/eink-billboard
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
	say "http://${address:-$(hostname).local}:$PORT"
}
in_group() { id -nG | tr ' ' '\n' | grep -qx "$1"; }
access_json() { curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/access" 2>/dev/null; }

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
	say "The first build takes 15 to 20 minutes on a Pi; later ones reuse what did not change. Everything is also written to $log."
	# EINK_BUILD_NETWORK=host builds on the Pi's own network, with no slirp4netns or pasta in between: for a Pi whose container networking fails (see below)
	local network=()
	[ -z "${EINK_BUILD_NETWORK:-}" ] || network=(--network "$EINK_BUILD_NETWORK")
	if ! podman build "${network[@]}" --target app-device --build-arg "EINK_COMMIT=$commit" --label "eink.commit=$commit" -t "$IMAGE" "$HERE" 2>&1 | tee "$log"; then
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

# the commit the image was built from (its label), or "unknown"
image_commit() {
	local built
	built=$(podman image inspect -f '{{index .Labels "eink.commit"}}' "$IMAGE" 2>/dev/null)
	case "$built" in ''|'<no value>') echo unknown ;; *) echo "$built" ;; esac
}

# fetch the latest code, build it, start it: the one command for "bring it up to date" ($1, optional: a branch or tag to switch to)
cmd_update() {
	local want=${1:-}
	command -v git >/dev/null || fail "git is not installed. Install it with:  sudo apt install -y git"
	git -C "$HERE" rev-parse --git-dir >/dev/null 2>&1 || fail "$HERE is not a git clone, so it cannot be updated. Run the setup command again, it makes one."
	git -C "$HERE" diff --quiet && git -C "$HERE" diff --cached --quiet \
		|| fail "the clone in $HERE has changes of its own, and updating would mix them in. Undo them (git -C $HERE stash), then run it again."

	section "Getting the latest code"
	local before branch
	before=$(git -C "$HERE" rev-parse --short HEAD)
	git -C "$HERE" fetch --tags --prune origin || fail "the latest code could not be fetched: is the Pi on the internet?"
	if [ -n "$want" ]; then
		git -C "$HERE" rev-parse -q --verify "origin/$want^{commit}" >/dev/null 2>&1 || git -C "$HERE" rev-parse -q --verify "refs/tags/$want^{commit}" >/dev/null 2>&1 \
			|| fail "there is no branch or tag '$want'. The branches and tags there are:  git -C $HERE branch -r; git -C $HERE tag"
		git -C "$HERE" checkout -q "$want" || fail "could not switch to '$want'."
	fi
	if branch=$(git -C "$HERE" symbolic-ref -q --short HEAD); then
		git -C "$HERE" rev-parse -q --verify "origin/$branch" >/dev/null \
			|| fail "the branch '$branch' is not in the repository the clone came from, so there is nothing to update it from. Go back to the usual one:  $SCRIPT update master"
		# a branch moves on: take what is new (only forward; a clone with commits of its own is not touched)
		git -C "$HERE" merge -q --ff-only "origin/$branch" 2>/dev/null \
			|| fail "the clone cannot simply move forward to the latest '$branch' (it has commits of its own). Nothing was changed."
		say "On $branch, now at commit $(git -C "$HERE" rev-parse --short HEAD) (was $before)."
	else
		# a tag stays where it is: a newer release is chosen by name, "update v1.2"
		say "On $(git -C "$HERE" describe --tags --exact-match 2>/dev/null || echo "commit $before"), which does not move. For another release:  $SCRIPT update <tag>"
	fi

	local now
	now=$(git -C "$HERE" rev-parse --short HEAD)
	if [ "$now" = "$(image_commit)" ] && podman image exists "$IMAGE"; then
		if running; then
			say "The app already runs this code: nothing to do."
			return 0
		fi
		say "The image is already built from this code."
	else
		section "Building"
		IN_UPDATE=1 cmd_build
	fi

	section "Starting"
	cmd_start

	# the build moved the image's name to the new one, and the old one (and the layers only it used) are left behind, a few GB each time; the
	# container now runs the new image, so they are unused. Only unused images go; a failure here is not one for the update.
	local before_kb after_kb
	before_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
	if podman image prune -f >/dev/null 2>&1; then
		after_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
		[ -n "$before_kb" ] && [ -n "$after_kb" ] && [ "$after_kb" -gt "$before_kb" ] && say "Removed old images: $(( (after_kb - before_kb) / 1024 )) MB freed."
	fi
}

cmd_start() {
	podman image exists "$IMAGE" || fail "there is no image yet. Build it first:  $SCRIPT build"
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

	if ! podman run -d --name "$NAME" --restart unless-stopped \
		-p "$PORT:8080" -v "$VOLUME:/data" \
		-e EINK_PUBLIC_URL="$url" -e EINK_ALLOW_HOSTS="$hosts" "${token[@]}" \
		"${devices[@]}" \
		"$IMAGE" uv run --no-sync python -m python.eink-billboard --host 0.0.0.0 --port 8080 --storage /data --app /work/app/dist >/dev/null; then
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
	[ "$(uname -m)" = "aarch64" ] && note "64-bit" || problem "not 64-bit ($(uname -m)): install Raspberry Pi OS 64-bit"
	if podman_version_ok; then note "Podman $(podman version --format '{{.Client.Version}}' 2>/dev/null)"; else problem "Podman $(podman version --format '{{.Client.Version}}' 2>/dev/null) is older than 4.3"; fi
	for g in "${GROUPS_NEEDED[@]}"; do
		if in_group "$g"; then note "you are in the $g group"; else problem "you are not in the $g group:  sudo usermod -aG $g $(id -un)  then log out and in again"; fi
	done
	local cfg=/boot/firmware/config.txt
	[ -f "$cfg" ] || cfg=/boot/config.txt
	if grep -qE "^[[:space:]]*dtparam=spi=on" "$cfg" 2>/dev/null; then note "SPI is on"; else problem "SPI is off:  sudo raspi-config  (Interface Options, SPI), then reboot"; fi
	if grep -qE "^[[:space:]]*dtparam=i2c_arm=on" "$cfg" 2>/dev/null; then note "I2C is on"; else problem "I2C is off (an Inky panel needs it):  sudo raspi-config  (Interface Options, I2C), then reboot"; fi
	# memory: a Chromium render costs about 75 to 110 MB and the app about 135 MB, so a board with less than 1 GB (a Pi Zero 2 W: 512 MB) runs with swap or not at all well
	local mem_kb swap_kb
	mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null)
	swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null)
	if [ -n "$mem_kb" ]; then
		swap_kb=${swap_kb:-0}
		if [ "$mem_kb" -ge 800000 ]; then
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
	if podman image exists "$IMAGE"; then
		local built
		built=$(image_commit)
		local checkout
		checkout=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)
		note "image $IMAGE, built $(podman image inspect -f '{{.Created}}' "$IMAGE" | cut -c1-16) from commit $built"
		if [ "$built" = "$checkout" ]; then
			note "the image is this checkout's commit"
		elif [ "$built" = unknown ] || [ "$checkout" = unknown ]; then
			info "cannot tell whether the image is this checkout's commit ($checkout); to be sure: '$SCRIPT update'"
		else
			# not a fault (the app runs as built), but the clone has moved on since: what runs is not what is checked out
			info "this checkout is at commit $checkout, the image at $built: to run the checkout, '$SCRIPT update'"
		fi
	else
		problem "no image yet:  $SCRIPT build"
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

cmd_wipe() {
	confirm "This DELETES everything the app keeps: its settings (API keys too), playlists, schedules and password (the volume '$VOLUME'). It cannot be undone." "$VOLUME"
	podman rm -f "$NAME" >/dev/null 2>&1
	if podman volume exists "$VOLUME"; then
		podman volume rm "$VOLUME" >/dev/null || fail "the volume '$VOLUME' could not be deleted: podman volume rm $VOLUME"
	fi
	say "Deleted. '$SCRIPT start' starts it as a new device (with a new setup code)."
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
	update) cmd_update "$@" ;;
	start|restart) cmd_start ;;
	stop) cmd_stop ;;
	logs) cmd_logs "$@" ;;
	code) cmd_code ;;
	check) cmd_check ;;
	display) cmd_display "$@" ;;
	models) cmd_models ;;
	detect) cmd_detect ;;
	autostart) cmd_autostart "$@" ;;
	reset-password) cmd_reset_password ;;
	wipe) cmd_wipe ;;
	*) say "There is no command '$command'."; say ""; cmd_help; exit 2 ;;
esac
