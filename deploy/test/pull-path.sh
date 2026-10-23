#!/usr/bin/env bash
# The pull path of deploy/eink-container.sh (#310), end to end, with no Pi and no GitHub: in a Debian Bookworm container (the Pi's Podman 4.3), a registry of its
# own on localhost:5000 stands in for ghcr.io, small images labelled as GitHub labels them stand in for its builds, and a `podman build` shim makes a "build"
# in a second. The real script then gets, refuses what it cannot download (it never builds unless asked), keeps the previous image, tidies the older ones and
# rolls back; and "update" follows its channel (#504) over a repository of its own standing in for GitHub's, with snapshot tags and a release.
#
#   podman run --rm --privileged -v "$PWD:/src:ro" docker.io/library/debian:bookworm bash /src/deploy/test/pull-path.sh
#   (Git Bash on Windows: MSYS_NO_PATHCONV=1, and "$(pwd -W)" for the folder)
#
# Run as root it installs what it needs, makes a user and runs itself again as that user (the script refuses root, as on a Pi). Exit 0: every check passed.
set -u
set -o pipefail

REGISTRY=localhost:5000/eink-billboard
CLONE=/home/pi/eink-billboard
SHIM=/home/pi/shim
BUILDS=/tmp/builds.log

if [ "$(id -u)" -eq 0 ]; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq && apt-get install -y -qq --no-install-recommends podman uidmap git curl ca-certificates docker-registry netcat-openbsd procps >/dev/null || { echo "could not install the tools"; exit 1; }
	# the registry ghcr.io stands in for, on this container's own loopback, open to all (Debian's own configuration asks for a password)
	printf 'version: 0.1\nstorage:\n  filesystem:\n    rootdirectory: /tmp/registry\nhttp:\n  addr: 127.0.0.1:5000\n' > /tmp/registry.yml
	/usr/bin/docker-registry serve /tmp/registry.yml >/tmp/registry.log 2>&1 &
	id pi >/dev/null 2>&1 || useradd -m -s /bin/bash pi
	grep -q '^pi:' /etc/subuid || echo "pi:100000:65536" >> /etc/subuid
	grep -q '^pi:' /etc/subgid || echo "pi:100000:65536" >> /etc/subgid
	# rootless Podman inside a container: no systemd, and storage without overlay mounts
	install -d -o pi -g pi /home/pi/.config/containers /run/user-pi
	chmod 700 /run/user-pi
	printf '[storage]\ndriver = "vfs"\n' > /home/pi/.config/containers/storage.conf
	printf '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n' > /home/pi/.config/containers/containers.conf
	chown -R pi:pi /home/pi/.config
	# the checkout as it is (with changes not yet committed), as a clone of its own
	install -d -o pi -g pi "$CLONE"
	tar -C /src --exclude=.git --exclude=node_modules --exclude=.venv --exclude='.storage*' --exclude=.env -cf - . | tar -C "$CLONE" -xf -
	chown -R pi:pi "$CLONE"
	for _ in $(seq 50); do curl -fs http://localhost:5000/v2/ >/dev/null && break; sleep 0.2; done
	exec runuser -u pi -- env HOME=/home/pi XDG_RUNTIME_DIR=/run/user-pi bash /src/deploy/test/pull-path.sh
fi

passed=0
failed=0
check() {
	# $1: what is checked; the rest: the command that must succeed
	local what=$1
	shift
	if "$@"; then passed=$((passed + 1)); echo "  ok    $what"; else failed=$((failed + 1)); echo "  FAIL  $what"; fi
}
# the images here are unsigned: the signature check (#555) is off unless a test turns it on
kit() { (cd "$CLONE" && EINK_VERIFY=${KIT_VERIFY:-0} EINK_REGISTRY=${KIT_REGISTRY:-$REGISTRY} EINK_REGISTRY_TLS_VERIFY=false PATH="$SHIM:$PATH" deploy/eink-container.sh "$@"); }
label() { podman image inspect -f "{{index .Labels \"$2\"}}" "$1" 2>/dev/null; }
short() { git -C "$CLONE" rev-parse --short=7 HEAD; }
full() { git -C "$CLONE" rev-parse HEAD; }
commit() { git -C "$CLONE" commit -q --allow-empty -m "$1"; }
builds() { [ -f "$BUILDS" ] && wc -l < "$BUILDS" || echo 0; }
no_bars() { ! grep -q 'Copying blob' <<< "$1"; }
# "[p]" so the pattern never finds the command line that holds it
no_pull_left() { ! pgrep -f '[p]odman pull -q' >/dev/null; }

# an image as GitHub publishes it: its commit's label, and (unless $3 says otherwise) the label of the commit it is published for
publish() {
	# $1: tag, $2: the commit label it carries
	local dir
	dir=$(mktemp -d)
	echo "$1 $2" > "$dir/stamp"
	printf 'FROM scratch\nCOPY stamp /stamp\n' > "$dir/Containerfile"
	podman build -q --label "eink.commit=$2" --label "eink.built-by=github" -t "$REGISTRY:$1" "$dir" >/dev/null || return 1
	podman push -q --tls-verify=false "$REGISTRY:$1" >/dev/null || return 1
	# gone from here, so "get" really downloads it
	podman rmi -f "$REGISTRY:$1" >/dev/null
}

# `podman build` in a second: an image with the labels and the name the script asks for; anything else is the real Podman
mkdir -p "$SHIM"
cat > "$SHIM/podman" <<'SHIM'
#!/usr/bin/env bash
if [ "${1:-}" = build ]; then
	shift
	args=() name=""
	while [ $# -gt 0 ]; do
		case "$1" in
			--label) args+=(--label "$2"); shift 2 ;;
			-t) name=$2; shift 2 ;;
			--target|--build-arg|--network) shift 2 ;;
			*) shift ;;
		esac
	done
	echo "build $name" >> /tmp/builds.log
	dir=$(mktemp -d)
	date +%s%N > "$dir/stamp"
	printf 'FROM scratch\nCOPY stamp /stamp\n' > "$dir/Containerfile"
	exec /usr/bin/podman build -q "${args[@]}" -t "$name" "$dir"
fi
exec /usr/bin/podman "$@"
SHIM
chmod +x "$SHIM/podman"

git -C "$CLONE" init -q -b master
git -C "$CLONE" config user.email test@example.invalid
git -C "$CLONE" config user.name test
git -C "$CLONE" add -A
git -C "$CLONE" commit -q -m "the checkout"
APP=localhost/eink-device
PREV=localhost/eink-device-previous

echo "== a commit GitHub published is downloaded, not built"
A=$(short)
check "published $A" publish "sha-$(full)" "$A"
out=$(kit get 2>&1)
check "it says it downloaded" grep -q "Downloaded $APP (commit $A, made by GitHub)" <<< "$out"
check "nothing was built" [ "$(builds)" -eq 0 ]
check "the app's image is $A, made by GitHub" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "$A/github" ]
check "the registry's name is not kept beside the app's" bash -c "! podman image exists '$REGISTRY:sha-$(full)'"
check "no progress bars on the screen" no_bars "$out"
check "Podman's own words are in pull.log" [ -s /home/pi/.cache/eink-billboard/pull.log ]

echo "== the same commit again: nothing to do"
out=$(kit get 2>&1)
check "it says the image is already this checkout's" grep -q "already this checkout's" <<< "$out"

echo "== a commit with nothing published is refused, not built"
commit B
B=$(short)
out=$(kit get 2>&1)
check "it fails" [ $? -ne 0 ]
check "it says there is nothing to download" grep -q "no image to download" <<< "$out"
check "it says what to do instead" grep -q "update --insider" <<< "$out"
check "nothing was built" [ "$(builds)" -eq 0 ]
check "the app's image is still $A" [ "$(label "$APP" eink.commit)" = "$A" ]

echo "== EINK_PULL=0 builds it here, and the one before is kept"
EINK_PULL=0 kit get >/dev/null 2>&1
check "it built once" [ "$(builds)" -eq 1 ]
check "the app's image is $B, built here" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "$B/local" ]
check "the previous image is $A" [ "$(label "$PREV" eink.commit)" = "$A" ]

echo "== the next download: $B becomes the previous, $A goes"
commit C
C=$(short)
check "published $C" publish "sha-$(full)" "$C"
kit get >/dev/null 2>&1
check "the app's image is $C" [ "$(label "$APP" eink.commit)" = "$C" ]
check "the previous image is $B" [ "$(label "$PREV" eink.commit)" = "$B" ]
check "no image of $A is left" [ -z "$(podman images -q --filter "label=eink.commit=$A")" ]

echo "== a release is downloaded by its commit (its image is the snapshot's, there before the release's name)"
commit D
D=$(short)
git -C "$CLONE" tag v9.9.9-test
check "published $D" publish "sha-$(full)" "$D"
out=$(kit get 2>&1)
check "it asked for the commit" grep -q "(sha-$(full))" <<< "$out"
check "the app's image is $D" [ "$(label "$APP" eink.commit)" = "$D" ]

echo "== an image that says it is another commit is refused, and nothing is built"
commit E
check "published sha-E labelled $A" publish "sha-$(full)" "$A"
before=$(builds)
out=$(kit get 2>&1)
check "it says the image is another commit" grep -q "says it is commit $A" <<< "$out"
check "nothing was built" [ "$(builds)" -eq "$before" ]
check "the app's image is still $D" [ "$(label "$APP" eink.commit)" = "$D" ]

echo "== EINK_PULL=0 builds even when there is a download"
commit F
F=$(short)
check "published $F" publish "sha-$(full)" "$F"
before=$(builds)
out=$(EINK_PULL=0 kit get 2>&1)
check "it built" [ "$(builds)" -eq $((before + 1)) ]
check "the app's image is $F, built here" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "$F/local" ]

echo "== a download that stops moving is given up, and nothing is built"
# a port that takes the connection and never answers: the network that went away halfway
nc -lk 127.0.0.1 5001 >/dev/null 2>&1 &
sink=$!
commit G
before=$(builds)
out=$(KIT_REGISTRY=localhost:5001/eink-billboard EINK_PULL_TICK=1 EINK_PULL_STALL=4 kit get 2>&1)
kill "$sink" 2>/dev/null
check "it said how it was going, in plain lines" grep -q "MB written so far" <<< "$out"
check "it said the download stopped moving" grep -q "stopped moving" <<< "$out"
check "nothing was built" [ "$(builds)" -eq "$before" ]
check "the app's image is still $F" [ "$(label "$APP" eink.commit)" = "$F" ]
check "no download is left running" no_pull_left

echo "== rollback swaps the app's image and the previous one (the start after it fails here: there is no app in these images)"
now=$(label "$APP" eink.commit)
was=$(label "$PREV" eink.commit)
# a person at a keyboard answers "yes": script(1) gives the command a terminal
printf 'yes\n' | script -qec "cd $CLONE && deploy/eink-container.sh rollback" /dev/null >/tmp/rollback.log 2>&1
check "the app's image is $was" [ "$(label "$APP" eink.commit)" = "$was" ]
check "the previous image is $now" [ "$(label "$PREV" eink.commit)" = "$now" ]
check "no swap name is left" bash -c "! podman image exists '$APP-swap'"
out=$(printf 'no\n' | script -qec "cd $CLONE && deploy/eink-container.sh rollback" /dev/null 2>&1)
check "anything but yes changes nothing" [ "$(label "$APP" eink.commit)" = "$was" ]

echo "== channels: the clone's repository stands in for GitHub's, a second clone makes the commits and the tags"
ORIGIN=/home/pi/origin.git
WORK=/home/pi/work
CHANNEL_FILE=/home/pi/.config/eink-billboard/channel
git clone -q --bare "$CLONE" "$ORIGIN"
git -C "$CLONE" remote add origin "$ORIGIN"
git -C "$CLONE" fetch -q origin
git clone -q "$ORIGIN" "$WORK"
git -C "$WORK" config user.email test@example.invalid
git -C "$WORK" config user.name test
at() { git -C "$CLONE" rev-parse HEAD; }
on_branch() { git -C "$CLONE" symbolic-ref -q HEAD >/dev/null; }
# a change on master as GitHub's workflow makes it: the commit, its snapshot tag ($1), and its image (unless $2 is "none")
snapshot() {
	git -C "$WORK" commit -q --allow-empty -m "change $1"
	git -C "$WORK" tag "$1"
	git -C "$WORK" push -q origin master "$1"
	[ "${2:-}" = none ] || publish "sha-$(git -C "$WORK" rev-parse HEAD)" "$(git -C "$WORK" rev-parse --short=7 HEAD)"
}
# a person at the keyboard answers $1
answer() { local reply=$1; shift; printf '%s\n' "$reply" | script -qec "cd $CLONE && EINK_VERIFY=0 EINK_REGISTRY=$REGISTRY EINK_REGISTRY_TLS_VERIFY=false PATH=$SHIM:\$PATH deploy/eink-container.sh $*" /dev/null 2>&1; }

rm -f "$CHANNEL_FILE"
was=$(at)
out=$(kit update 2>&1)
check "a Pi on master with no channel follows insider, and with no snapshot yet it says so" grep -q "no version to download yet" <<< "$out"
check "nothing moved" bash -c "[ '$(at)' = '$was' ]"
check "it is still on its branch" on_branch

check "a snapshot is published" snapshot 20261022100000
H=$(git -C "$WORK" rev-parse HEAD)
out=$(kit update 2>&1)
check "update goes to the newest snapshot" [ "$(at)" = "$H" ]
check "it says the channel" grep -q "Channel: insider" <<< "$out"
check "it downloaded the snapshot's image" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "${H::7}/github" ]
check "the channel is kept" [ "$(cat "$CHANNEL_FILE")" = insider ]

check "a newer snapshot is published" snapshot 20261022110000
I=$(git -C "$WORK" rev-parse HEAD)
kit update >/dev/null 2>&1
check "update goes to it" [ "$(at)" = "$I" ]

echo "== an update that brings a change to the script runs the rest of itself from the new copy (#561)"
sed -i 's/section "Getting the app"/section "Getting the app (said by the new copy)"/' "$WORK/deploy/eink-container.sh"
git -C "$WORK" commit -q -am "the script says something new"
check "a snapshot changing the script is published" snapshot 20261022113000
N=$(git -C "$WORK" rev-parse HEAD)
out=$(kit update 2>&1)
check "update goes to it" [ "$(at)" = "$N" ]
check "the download is the new copy's" grep -q "Getting the app (said by the new copy)" <<< "$out"
check "the code part is said once" [ "$(grep -c "Getting the latest code" <<< "$out")" -eq 1 ]
check "it downloaded the snapshot's image" [ "$(label "$APP" eink.commit)" = "${N::7}" ]
# back to the script as it is, for the rest
git -C "$WORK" revert -q --no-edit HEAD
check "a snapshot with the script as it was is published" snapshot 20261022114500
I=$(git -C "$WORK" rev-parse HEAD)
kit update >/dev/null 2>&1
check "update goes to it" [ "$(at)" = "$I" ]

out=$(kit update --stable 2>&1)
check "the release is older: without a person to say yes, nothing moves" grep -q "needs a yes" <<< "$out"
check "still on the newest snapshot" [ "$(at)" = "$I" ]
out=$(answer yes update --stable)
check "with a yes, stable goes back to the release" [ "$(git -C "$CLONE" describe --tags --exact-match)" = v9.9.9-test ]
check "it downloaded the release's image" [ "$(label "$APP" eink.commit)" = "$D" ]
check "the channel is stable" [ "$(cat "$CHANNEL_FILE")" = stable ]

kit update 20261022100000 >/dev/null 2>&1
check "a snapshot named is gone to (forward, no question)" [ "$(at)" = "$H" ]
check "and kept: the channel is pinned" [ "$(cat "$CHANNEL_FILE")" = pinned ]
check "a newer snapshot is published" snapshot 20261022120000
out=$(kit update 2>&1)
check "a pinned Pi stays where it is" [ "$(at)" = "$H" ]
check "and says how to follow a channel again" grep -q "which stays" <<< "$out"

git -C "$WORK" push -q origin :refs/tags/20261022120000
kit update --master >/dev/null 2>&1
check "--master is insider" [ "$(cat "$CHANNEL_FILE")" = insider ]
check "a snapshot GitHub removed is gone from the clone too" bash -c "! git -C '$CLONE' rev-parse -q --verify refs/tags/20261022120000 >/dev/null"
check "so the newest left is used" [ "$(at)" = "$I" ]

check "a snapshot without an image" snapshot 20261022130000 none
J=$(git -C "$WORK" rev-parse HEAD)
before=$(builds)
out=$(kit update 2>&1)
check "the clone goes to it" [ "$(at)" = "$J" ]
check "nothing is built" [ "$(builds)" -eq "$before" ]
check "the app keeps its image" [ "$(label "$APP" eink.commit)" = "${I::7}" ]
check "and it says what to do" grep -q "update --insider" <<< "$out"

out=$(kit update --bogus 2>&1)
check "an unknown option is refused by name" grep -q "no option '--bogus'" <<< "$out"
out=$(kit update no-such-thing 2>&1)
check "an unknown name is refused" grep -q "no release, snapshot or branch 'no-such-thing'" <<< "$out"

echo "== with the signature check on, an image GitHub did not sign is refused (#555)"
commit V
V=$(short)
check "published $V, unsigned" publish "sha-$(full)" "$V"
before_app=$(label "$APP" eink.commit)
out=$(KIT_VERIFY=1 kit get 2>&1)
check "it fails" [ $? -ne 0 ]
check "it says it could not be shown to be GitHub's" grep -q "could not be shown to be GitHub's for this version" <<< "$out"
check "the app keeps the image it had" [ "$(label "$APP" eink.commit)" = "$before_app" ]
check "the downloaded name is not kept" bash -c "! podman image exists '$REGISTRY:sha-$(full)'"
check "cosign's words are in verify.log" [ -s /home/pi/.cache/eink-billboard/verify.log ]
out=$(kit get 2>&1)
check "EINK_VERIFY=0 says the signature is not checked" grep -q "EINK_VERIFY=0: the image's signature is not checked" <<< "$out"

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
