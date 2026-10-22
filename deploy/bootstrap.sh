#!/usr/bin/env bash
# eInk Billboard: set up a Raspberry Pi 4 or 5 (Raspberry Pi OS 64-bit) to run it, in one command:
#
#   curl -fsSL https://raw.githubusercontent.com/escape-llc/eink-billboard/master/deploy/bootstrap.sh | bash
#
# Run it as your own user (it asks for your password where it needs sudo). It says what it will do and asks before doing it.
# Run the same command again at any time: it continues where it stopped (after a reboot it asks for), and later it updates the app.
#
# What it does on the Pi itself (everything else, Python, the browser that draws the pages, the panel drivers, is inside the container):
#   installs Podman and git; turns on SPI and I2C (the panel's connections); adds you to the spi, i2c and gpio groups;
#   clones the app to ~/eink-billboard, on the newest release (or with --insider the newest snapshot: every change, a few minutes after it);
#   asks which display you have; downloads the app (GitHub makes the image: nothing is built on the Pi);
#   starts it on port 8080; makes it start when the Pi starts; prints the address and the setup code.
#
# Options:     --yes      do not ask (the display is EINK_DISPLAY, or mock)       --dry-run   say what it would do, change nothing
#              --stable   the releases (the default)                              --insider   every change (--master is the same)
# Settings:    EINK_CHANNEL  stable or insider, as the options (a Pi that has one keeps it)
#              EINK_REF      a branch or tag to install instead of a channel's newest version
#              EINK_DIR      where the app is cloned (~/eink-billboard)
#              EINK_DISPLAY  the display without asking: mock, inky, or waveshare:MODEL (e.g. waveshare:epd7in3e)
#              EINK_REPO     the repository (https://github.com/escape-llc/eink-billboard)
#
# Everything is inside main(), called on the last line: a download cut short runs nothing.

main() {
	set -u
	set -o pipefail

	local REPO=${EINK_REPO:-https://github.com/escape-llc/eink-billboard}
	local REF=${EINK_REF:-}
	local CHANNEL=${EINK_CHANNEL:-}
	local DIR=${EINK_DIR:-$HOME/eink-billboard}
	local STATE_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/eink-billboard
	local YES=0 DRY=0 FROM_CLONE=0 NEEDS_REBOOT=0 arg
	for arg in "$@"; do
		case "$arg" in
			--yes|-y) YES=1 ;;
			--dry-run) DRY=1 ;;
			--from-clone) FROM_CLONE=1 ;;
			--needs-reboot) NEEDS_REBOOT=1 ;;
			--stable) CHANNEL=stable ;;
			--insider|--master) CHANNEL=insider ;;
			# written out here, not read from this file: piped from curl, there is no file to read
			--help|-h) cat <<'EOF'
eInk Billboard setup for a Raspberry Pi 4 or 5 (Raspberry Pi OS 64-bit). Run it as your own user:

  curl -fsSL https://raw.githubusercontent.com/escape-llc/eink-billboard/master/deploy/bootstrap.sh | bash

It says what it will do and asks once, then: installs Podman and git, turns on SPI and I2C, adds you to the spi, i2c and gpio
groups, clones the app to ~/eink-billboard, asks which display you have, downloads the app (a few minutes),
starts it on port 8080, makes it start when the Pi starts, and prints the address and the setup code.
Run it again at any time: it continues after a restart it asked for, and later it updates the app.

Options (after "| bash -s --"):  --dry-run  say what it would do, change nothing     --yes  ask nothing     --help  this text
                                 --stable   the releases (the default)               --insider  every change (--master too)
Settings:  EINK_DISPLAY  mock, inky or waveshare:MODEL      EINK_CHANNEL  stable or insider
           EINK_DIR      where to clone (~/eink-billboard)  EINK_REF      a branch or tag instead of a channel
           EINK_REPO     the repository
Afterwards:  ~/eink-billboard/deploy/eink-container.sh help      (update: ~/eink-billboard/deploy/eink-container.sh update)
EOF
				return 0 ;;
			*) printf 'eink-billboard bootstrap: unknown option %s (--yes, --dry-run, --stable, --insider, --help)\n' "$arg" >&2; return 2 ;;
		esac
	done

	say() { printf '%s\n' "$*"; }
	case "$CHANNEL" in
		""|stable|insider) ;;
		*) printf 'eink-billboard bootstrap: EINK_CHANNEL is stable or insider (it is %s)\n' "$CHANNEL" >&2; return 2 ;;
	esac
	# the copy in the clone does not repeat what the downloaded one already said about this computer
	first() { [ "$FROM_CLONE" -eq 1 ] || "$@"; }
	step() { printf '\n==> %s\n' "$*"; }
	warn() { printf '\nWARNING: %s\n' "$*" >&2; }
	fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
	# runs a command, or only shows it with --dry-run
	run() { if [ "$DRY" -eq 1 ]; then printf '    would run: %s\n' "$*"; else "$@"; fi; }

	# questions come from the keyboard: when this script is piped into bash, its own input is the download
	local TTY=""
	if [ "$YES" -eq 0 ]; then
		if [ -t 0 ]; then TTY=/dev/stdin
		elif { : < /dev/tty; } 2>/dev/null; then TTY=/dev/tty
		else fail "there is no keyboard to ask questions on. Run it in a terminal, or with --yes (and EINK_DISPLAY) to answer every question with the default."
		fi
	fi
	ask() {
		# $1 the question, $2 the default; the answer is in REPLY
		if [ "$YES" -eq 1 ]; then REPLY=$2; return; fi
		read -r -p "$1 " REPLY < "$TTY" || REPLY=""
		[ -n "$REPLY" ] || REPLY=$2
	}
	yes_no() {
		# $1 the question; returns 0 for yes (the default is yes)
		ask "$1 [Y/n]" y
		case "$REPLY" in [Yy]|[Yy][Ee][Ss]) return 0 ;; *) return 1 ;; esac
	}

	# ---- what this Pi is -----------------------------------------------------------------------------------------------------------------------
	first step "Checking this computer"
	[ "$(uname -s)" = "Linux" ] || fail "this is for a Raspberry Pi with Raspberry Pi OS."
	[ "$(id -u)" -ne 0 ] || fail "run this as your own user, not with sudo or as root (it asks for your password when it needs it):
       curl -fsSL https://raw.githubusercontent.com/escape-llc/eink-billboard/master/deploy/bootstrap.sh | bash"
	local arch model os
	arch=$(uname -m)
	model=$( { tr -d '\0' < /proc/device-tree/model; } 2>/dev/null || echo "not a Raspberry Pi")
	os=$( . /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")
	first say "$model, $os, $arch"
	[ "$arch" = "aarch64" ] || fail "this needs the 64-bit Raspberry Pi OS (this one is $arch). Install it with Raspberry Pi Imager (Raspberry Pi OS 64-bit), then run this again."
	case "$model" in
		*"Raspberry Pi 4"*|*"Raspberry Pi 5"*|*"Compute Module 4"*|*"Compute Module 5"*) ;;  # the 400 and 500 too
		*"Raspberry Pi"*) first warn "this was made for a Raspberry Pi 4 or 5; on $model it may be too slow or short of memory. Going on." ;;
		*) first warn "this does not look like a Raspberry Pi: the app will run, but without a panel to drive. Going on." ;;
	esac
	command -v apt-get >/dev/null || fail "this needs Raspberry Pi OS (or another Debian): apt-get is missing."
	command -v sudo >/dev/null || fail "sudo is missing: it is needed to install Podman. Ask whoever set up this Pi."
	command -v curl >/dev/null || first say "(curl will be installed)"
	if ! curl -fsS --max-time 15 -o /dev/null https://github.com 2>/dev/null; then
		command -v curl >/dev/null && fail "github.com cannot be reached: is the Pi on the internet?"
	fi

	# ---- what needs doing ----------------------------------------------------------------------------------------------------------------------
	local packages=() p need_spi=0 need_i2c=0 groups_missing=() g
	for p in podman git curl uidmap; do
		dpkg -s "$p" >/dev/null 2>&1 || packages+=("$p")
	done
	# on is when the device is there (a change in config.txt waits for a restart, so a run before it asks again: harmless)
	[ -c /dev/spidev0.0 ] || need_spi=1
	[ -c /dev/i2c-1 ] || need_i2c=1
	if { [ "$need_spi" -eq 1 ] || [ "$need_i2c" -eq 1 ]; } && ! command -v raspi-config >/dev/null; then
		first warn "SPI or I2C is off and raspi-config is missing: add dtparam=spi=on and dtparam=i2c_arm=on to /boot/firmware/config.txt yourself and restart. Going on."
		need_spi=0; need_i2c=0
	fi
	# a group is added to the system's list at once, but reaches you only at your next login: so a group in the list and not in this session needs a restart, not adding again
	local relogin=0
	for g in spi i2c gpio; do
		getent group "$g" >/dev/null || continue
		if ! id -nG "$(id -un)" | tr ' ' '\n' | grep -qx "$g"; then groups_missing+=("$g")
		elif ! id -nG | tr ' ' '\n' | grep -qx "$g"; then relogin=1; fi
	done
	local subids=1
	grep -q "^$(id -un):" /etc/subuid 2>/dev/null && grep -q "^$(id -un):" /etc/subgid 2>/dev/null || subids=0

	if [ "$FROM_CLONE" -eq 0 ]; then
		say ""
		say "This will:"
		[ ${#packages[@]} -eq 0 ] || say "  - install ${packages[*]} (sudo apt-get install)"
		[ "$subids" -eq 1 ] || say "  - give your user the ID ranges Podman needs to run containers as you"
		[ "$need_spi" -eq 0 ] || say "  - turn on SPI (the panel's data connection)"
		[ "$need_i2c" -eq 0 ] || say "  - turn on I2C (how an Inky panel says what it is)"
		[ ${#groups_missing[@]} -eq 0 ] || say "  - add you to the group(s) ${groups_missing[*]} (so the app may use the panel)"
		if [ -n "$REF" ]; then say "  - get the app into $DIR (from $REPO, $REF)"
		else say "  - get the app into $DIR (from $REPO, the newest version of the ${CHANNEL:-stable} channel)"; fi
		say "  - ask which display you have"
		say "  - download the app and start it on port 8080"
		say "  - make it start when the Pi starts"
		[ "$DRY" -eq 0 ] || say "(--dry-run: nothing will be changed)"
		say ""
		yes_no "Go ahead?" || fail "nothing was changed."
	fi

	# ---- the Pi itself (sudo) --------------------------------------------------------------------------------------------------------------------
	local reboot=$relogin
	if [ ${#packages[@]} -gt 0 ] || [ "$subids" -eq 0 ] || [ "$need_spi" -eq 1 ] || [ "$need_i2c" -eq 1 ] || [ ${#groups_missing[@]} -gt 0 ]; then
		step "Setting up the Pi (sudo asks for your password)"
		if [ ${#packages[@]} -gt 0 ]; then
			run sudo apt-get update || fail "the package lists could not be updated: is the Pi on the internet? Run this again."
			run sudo apt-get install -y "${packages[@]}" || fail "${packages[*]} could not be installed: the lines above say why. Run this again."
		fi
		if [ "$subids" -eq 0 ]; then
			run sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$(id -un)" || fail "the ID ranges for Podman could not be added."
		fi
		if [ "$need_spi" -eq 1 ]; then run sudo raspi-config nonint do_spi 0 || fail "SPI could not be turned on: sudo raspi-config, Interface Options, SPI."; reboot=1; fi
		if [ "$need_i2c" -eq 1 ]; then run sudo raspi-config nonint do_i2c 0 || fail "I2C could not be turned on: sudo raspi-config, Interface Options, I2C."; reboot=1; fi
		if [ ${#groups_missing[@]} -gt 0 ]; then
			run sudo usermod -aG "$(IFS=,; echo "${groups_missing[*]}")" "$(id -un)" || fail "you could not be added to ${groups_missing[*]}."
			reboot=1
		fi
	fi

	# ---- the app's code ---------------------------------------------------------------------------------------------------------------------------
	if [ "$FROM_CLONE" -eq 0 ]; then
		step "Getting the app${REF:+ ($REF)}"
		local fresh=0
		if [ -d "$DIR/.git" ]; then
			git -C "$DIR" diff --quiet && git -C "$DIR" diff --cached --quiet \
				|| fail "$DIR has changes of your own; this would not overwrite them. Move them away (git -C $DIR stash) and run this again."
			# the snapshots GitHub removed go from here too, so the newest one here is one GitHub still has an image of
			run git -C "$DIR" fetch -q --tags --prune --prune-tags origin || fail "the app could not be updated: is the Pi on the internet?"
		elif [ -e "$DIR" ]; then
			fail "$DIR is there but is not the app. Move it away, or choose another folder: EINK_DIR=~/somewhere ..."
		else
			run git clone -q --branch "${REF:-master}" "$REPO" "$DIR" || fail "the app could not be downloaded from $REPO."
			fresh=1
		fi
		if [ -n "$REF" ]; then
			run git -C "$DIR" checkout -q "$REF" || fail "there is no branch or tag '$REF'."
			# a branch moves forward; a tag stays where it is
			if git -C "$DIR" symbolic-ref -q HEAD >/dev/null 2>&1; then run git -C "$DIR" merge -q --ff-only "origin/$REF" || fail "$DIR cannot be brought up to date (it has commits of its own)."; fi
		elif [ "$DRY" -eq 1 ] && [ ! -d "$DIR/.git" ]; then
			say "    would go to the newest version of the ${CHANNEL:-stable} channel"
		else
			# the channel: the one asked for, else the one this Pi has, else (a Pi set up before channels) insider when it follows master; a new Pi: stable
			[ -n "$CHANNEL" ] || CHANNEL=$(cat "$STATE_DIR/channel" 2>/dev/null || true)
			case "$CHANNEL" in
				stable|insider) ;;
				pinned|branch) CHANNEL="" ;;
				*)
					CHANNEL=stable
					if [ "$fresh" -eq 0 ] && [ "$(git -C "$DIR" symbolic-ref -q --short HEAD 2>/dev/null)" = master ]; then CHANNEL=insider; fi ;;
			esac
			if [ -n "$CHANNEL" ]; then
				# the same two rules as eink-container.sh's newest_release and newest_snapshot
				local target=""
				[ "$CHANNEL" = insider ] || target=$(git -C "$DIR" tag -l 'v*' --sort=-v:refname | grep -E '^v[0-9A-Za-z._-]{1,100}$' | head -n 1)
				[ -n "$target" ] || target=$(git -C "$DIR" tag -l '[0-9]*' | grep -E '^[0-9]{14}$' | sort | tail -n 1)
				[ -n "$target" ] || fail "GitHub has made no version to download yet (it makes one a few minutes after each change). Run this again in a few minutes."
				run git -C "$DIR" checkout -q "refs/tags/$target" || fail "could not switch to $target."
				if [ "$DRY" -eq 0 ]; then mkdir -p "$STATE_DIR"; printf '%s\n' "$CHANNEL" > "$STATE_DIR/channel"; fi
				say "The $CHANNEL channel: $target"
			else
				say "This Pi stays on the version it has ('deploy/eink-container.sh update --stable' or '--insider' follows a channel again)."
			fi
		fi
		if [ "$DRY" -eq 1 ]; then say "(--dry-run: the rest is done by $DIR/deploy/bootstrap.sh, which a real run continues with)"; return 0; fi
		# the rest is done by the copy that came with the app, so the steps always match the app being installed
		local pass=(--from-clone)
		[ "$YES" -eq 0 ] || pass+=(--yes)
		[ "$reboot" -eq 0 ] || pass+=(--needs-reboot)
		exec bash "$DIR/deploy/bootstrap.sh" "${pass[@]}"
	fi
	# (from here on this is the copy in the clone)

	local HERE
	HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
	local KIT="$HERE/deploy/eink-container.sh"
	[ -x "$KIT" ] || fail "$KIT is missing: the clone in $HERE is incomplete. Delete it and run the command again."
	[ "$NEEDS_REBOOT" -eq 0 ] || reboot=1

	# ---- the display ------------------------------------------------------------------------------------------------------------------------------
	step "Your display"
	mkdir -p "$STATE_DIR"
	local chosen="${EINK_DISPLAY:-}"
	[ -n "$chosen" ] || chosen=$(cat "$STATE_DIR/display" 2>/dev/null || true)
	local kind model=""
	if [ "$YES" -eq 1 ]; then
		[ -n "$chosen" ] || chosen=mock
	else
		say "Which display is attached?"
		say "  1) none yet (try the app without a panel)"
		say "  2) Pimoroni Inky (it says what it is, nothing more to choose)"
		say "  3) Waveshare e-Paper (choose its model next)"
		local default=1
		case "$chosen" in inky) default=2 ;; waveshare:*) default=3 ;; esac
		while :; do
			ask "Your choice [$default]:" "$default"
			case "$REPLY" in
				1) chosen=mock; break ;;
				2) chosen=inky; break ;;
				3)
					local previous=""
					case "$chosen" in waveshare:*) previous=${chosen#waveshare:} ;; esac
					"$KIT" models
					while :; do
						ask "The model${previous:+ [$previous]}:" "$previous"
						if [ -n "$REPLY" ] && "$KIT" models | tr -s ' \t' '\n\n' | grep -qx "$REPLY"; then break; fi
						say "'$REPLY' is not one of the models above (the name is on the Waveshare wiki page of your panel, e.g. epd7in3e)."
					done
					chosen="waveshare:$REPLY"; break ;;
				*) say "Type 1, 2 or 3." ;;
			esac
		done
	fi
	case "$chosen" in
		mock|inky) kind=$chosen ;;
		waveshare:?*) kind=waveshare; model=${chosen#waveshare:} ;;
		*) fail "EINK_DISPLAY must be mock, inky or waveshare:MODEL (it is '$chosen')." ;;
	esac
	printf '%s\n' "$chosen" > "$STATE_DIR/display"
	say "Display: $kind${model:+ $model}"

	# ---- the app's image ---------------------------------------------------------------------------------------------------------------------------
	step "Getting the app (a download of a few minutes)"
	"$KIT" get || exit 1

	if [ "$reboot" -eq 1 ]; then
		step "Restart the Pi"
		say "SPI, I2C or your groups were just changed, and they take effect only after a restart."
		say "After it, run the same command again: it finishes in a minute or two."
		say "    curl -fsSL https://raw.githubusercontent.com/escape-llc/eink-billboard/master/deploy/bootstrap.sh | bash"
		if [ "$YES" -eq 0 ] && yes_no "Restart now?"; then sudo reboot; fi
		return 0
	fi

	# ---- start ---------------------------------------------------------------------------------------------------------------------------------
	step "Starting the app"
	EINK_PORT=8080 "$KIT" start || exit 1
	step "Choosing the display"
	"$KIT" display "$kind" ${model:+"$model"} || warn "the display could not be chosen; choose it in the web app (Settings, Display) and restart:  $KIT start"
	if [ "$kind" = "inky" ]; then
		# an Inky says what it is: a warning if it does not answer, never a reason to stop
		"$KIT" detect || warn "no Inky panel answered. Check that it sits on all the pins of the header, then:  $KIT check"
	fi
	step "Starting the app when the Pi starts"
	"$KIT" autostart on || warn "the app will not start by itself after a restart:  $KIT autostart on"

	step "Done"
	"$KIT" code
	say "When something does not work:  $KIT check"
}

main "$@"
