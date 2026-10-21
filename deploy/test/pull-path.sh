#!/usr/bin/env bash
# The pull path of deploy/eink-container.sh (#310), end to end, with no Pi and no GitHub: in a Debian Bookworm container (the Pi's Podman 4.3), a registry of its
# own on localhost:5000 stands in for ghcr.io, small images labelled as GitHub labels them stand in for its builds, and a `podman build` shim makes a "build"
# in a second. The real script then gets, falls back, keeps the previous image, tidies the older ones and rolls back.
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
	apt-get update -qq && apt-get install -y -qq --no-install-recommends podman uidmap git curl ca-certificates docker-registry >/dev/null || { echo "could not install the tools"; exit 1; }
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
kit() { (cd "$CLONE" && EINK_REGISTRY=$REGISTRY EINK_REGISTRY_TLS_VERIFY=false PATH="$SHIM:$PATH" deploy/eink-container.sh "$@"); }
label() { podman image inspect -f "{{index .Labels \"$2\"}}" "$1" 2>/dev/null; }
short() { git -C "$CLONE" rev-parse --short=7 HEAD; }
full() { git -C "$CLONE" rev-parse HEAD; }
commit() { git -C "$CLONE" commit -q --allow-empty -m "$1"; }
builds() { [ -f "$BUILDS" ] && wc -l < "$BUILDS" || echo 0; }

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

echo "== the same commit again: nothing to do"
out=$(kit get 2>&1)
check "it says the image is already this checkout's" grep -q "already this checkout's" <<< "$out"

echo "== a commit with nothing published is built here, and the one before is kept"
commit B
B=$(short)
out=$(kit get 2>&1)
check "it says there is nothing to download" grep -q "no image to download" <<< "$out"
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

echo "== a release tag is downloaded by its name"
commit D
D=$(short)
git -C "$CLONE" tag v9.9.9-test
check "published v9.9.9-test" publish v9.9.9-test "$D"
out=$(kit get 2>&1)
check "it asked for the tag" grep -q "(v9.9.9-test)" <<< "$out"
check "the app's image is $D" [ "$(label "$APP" eink.commit)" = "$D" ]

echo "== an image that says it is another commit is refused, and built here"
commit E
E=$(short)
check "published sha-E labelled $A" publish "sha-$(full)" "$A"
out=$(kit get 2>&1)
check "it says the image is another commit" grep -q "says it is commit $A" <<< "$out"
check "the app's image is $E, built here" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "$E/local" ]

echo "== EINK_PULL=0 builds even when there is a download"
commit F
F=$(short)
check "published $F" publish "sha-$(full)" "$F"
before=$(builds)
out=$(EINK_PULL=0 kit get 2>&1)
check "it built" [ "$(builds)" -eq $((before + 1)) ]
check "the app's image is $F, built here" [ "$(label "$APP" eink.commit)/$(label "$APP" eink.built-by)" = "$F/local" ]

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

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
