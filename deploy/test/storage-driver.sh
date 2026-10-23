#!/usr/bin/env bash
# How Podman keeps its images (#552), end to end, with no Pi and no GitHub: in a Debian Bookworm container (the Pi's Podman 4.3), a Podman that keeps its
# images as vfs (every layer a full copy, as one Pi did) is changed to overlay by "deploy/eink-container.sh storage", with the app's data saved, checked and put
# back and the app downloaded again from a registry of its own; one that holds nothing yet is changed by "get" without asking; and "check" says which it is.
#
#   podman run --rm --privileged -v "$PWD:/src:ro" docker.io/library/debian:bookworm bash /src/deploy/test/storage-driver.sh
#   (Git Bash on Windows: MSYS_NO_PATHCONV=1, and "$(pwd -W)" for the folder)
#
# Podman's store is on a tmpfs; EINK_TEST_STORE=disk leaves it on the container's own file system (itself an overlay). Either way the kernel's overlay worked
# for a user here (WSL's kernel 6.18), so the fuse-overlayfs way is not what this exercises. Exit 0: every check passed.
set -u
set -o pipefail

REGISTRY=localhost:5000/eink-billboard
CLONE=/home/pi/eink-billboard

if [ "$(id -u)" -eq 0 ]; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq && apt-get install -y -qq --no-install-recommends podman fuse-overlayfs uidmap git curl ca-certificates docker-registry procps bsdutils >/dev/null || { echo "could not install the tools"; exit 1; }
	printf 'version: 0.1\nstorage:\n  filesystem:\n    rootdirectory: /tmp/registry\nhttp:\n  addr: 127.0.0.1:5000\n' > /tmp/registry.yml
	/usr/bin/docker-registry serve /tmp/registry.yml >/tmp/registry.log 2>&1 &
	id pi >/dev/null 2>&1 || useradd -m -s /bin/bash pi
	grep -q '^pi:' /etc/subuid || echo "pi:100000:65536" >> /etc/subuid
	grep -q '^pi:' /etc/subgid || echo "pi:100000:65536" >> /etc/subgid
	install -d -o pi -g pi /home/pi/.config/containers /home/pi/.local/share /run/user-pi
	chmod 700 /run/user-pi
	if [ "${EINK_TEST_STORE:-tmpfs}" = tmpfs ]; then
		mount -t tmpfs -o size=2g,mode=755,uid="$(id -u pi)",gid="$(id -g pi)" tmpfs /home/pi/.local/share || { echo "could not mount a tmpfs (is the container --privileged?)"; exit 1; }
	fi
	# no systemd in here
	printf '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n' > /home/pi/.config/containers/containers.conf
	chown -R pi:pi /home/pi/.config
	install -d -o pi -g pi "$CLONE"
	tar -C /src --exclude=.git --exclude=node_modules --exclude=.venv --exclude='.storage*' --exclude=.env -cf - . | tar -C "$CLONE" -xf -
	chown -R pi:pi "$CLONE"
	for _ in $(seq 50); do curl -fs http://localhost:5000/v2/ >/dev/null && break; sleep 0.2; done
	exec runuser -u pi -- env HOME=/home/pi XDG_RUNTIME_DIR=/run/user-pi EINK_TEST_STORE="${EINK_TEST_STORE:-tmpfs}" bash /src/deploy/test/storage-driver.sh
fi

passed=0
failed=0
check() {
	local what=$1
	shift
	if "$@"; then passed=$((passed + 1)); echo "  ok    $what"; else failed=$((failed + 1)); echo "  FAIL  $what"; fi
}
kit() { (cd "$CLONE" && EINK_VERIFY=0 EINK_REGISTRY=$REGISTRY EINK_REGISTRY_TLS_VERIFY=false deploy/eink-container.sh "$@"); }
answer() { local reply=$1; shift; printf '%s\n' "$reply" | script -qec "cd $CLONE && EINK_VERIFY=0 EINK_REGISTRY=$REGISTRY EINK_REGISTRY_TLS_VERIFY=false deploy/eink-container.sh $*" /dev/null 2>&1; }
driver() { podman info --format '{{.Store.GraphDriverName}}' 2>/dev/null; }
label() { podman image inspect -f "{{index .Labels \"$2\"}}" "$1" 2>/dev/null; }
CONF=/home/pi/.config/containers/storage.conf
APP=localhost/eink-device

git -C "$CLONE" init -q -b master
git -C "$CLONE" config user.email test@example.invalid
git -C "$CLONE" config user.name test
git -C "$CLONE" add -A
git -C "$CLONE" commit -q -m "the checkout"
A=$(git -C "$CLONE" rev-parse --short=7 HEAD)

# an image as GitHub publishes it for this checkout
publish() {
	local dir
	dir=$(mktemp -d)
	echo "$A" > "$dir/stamp"
	printf 'FROM scratch\nCOPY stamp /stamp\n' > "$dir/Containerfile"
	podman build -q --label "eink.commit=$A" --label "eink.built-by=github" -t "$REGISTRY:sha-$(git -C "$CLONE" rev-parse HEAD)" "$dir" >/dev/null || return 1
	podman push -q --tls-verify=false "$REGISTRY:sha-$(git -C "$CLONE" rev-parse HEAD)" >/dev/null || return 1
	podman rmi -f "$REGISTRY:sha-$(git -C "$CLONE" rev-parse HEAD)" >/dev/null
}
# a Podman that chose vfs when it first ran, and remembers it with no storage.conf (as the Pi did)
as_vfs() {
	podman system reset --force >/dev/null 2>&1
	printf '[storage]\ndriver = "vfs"\n' > "$CONF"
	podman info >/dev/null 2>&1
	rm -f "$CONF"
}

echo "== a Podman that holds the app and its data, as vfs (store: $EINK_TEST_STORE)"
as_vfs
check "the registry has the app" publish
mkdir -p /tmp/data/settings && echo '{ "marker": "kept" }' > /tmp/data/settings/system-settings.json
tar -C /tmp/data -cf /tmp/data.tar settings
podman volume create eink-data >/dev/null && podman volume import eink-data /tmp/data.tar
podman volume create other >/dev/null
out=$(kit get 2>&1)
check "get, with data there, only warns that vfs is slow" grep -q "storage. changes it to overlay" <<< "$out"
check "it keeps images as vfs" [ "$(driver)" = vfs ]
check "the app's image is there" podman image exists "$APP"
out=$(kit check 2>&1)
check "check says vfs and what to run" grep -q "slow way (vfs.*storage" <<< "$out"

echo "== 'storage', answered no: nothing changes"
out=$(answer no storage)
check "it stops" grep -q "nothing was changed" <<< "$out"
check "it says the other volume is not saved" grep -q "1 other volume(s) of yours are NOT saved" <<< "$out"
check "still vfs" [ "$(driver)" = vfs ]
check "the data is still there" podman volume exists eink-data

echo "== 'storage', answered reset"
out=$(answer reset storage)
echo "$out" | sed 's/^/    | /'
check "Podman keeps images with overlay" [ "$(driver)" = overlay ]
check "the storage.conf says so, and who wrote it" bash -c "grep -q 'driver = \"overlay\"' $CONF && grep -q 'written by deploy/eink-container.sh' $CONF"
backup=$(ls /home/pi/eink-data-*.tar 2>/dev/null | head -1)
check "the data was saved to a file in the home folder" [ -s "$backup" ]
check "the data is back, the same" bash -c "podman volume export eink-data | tar -xOf - settings/system-settings.json | grep -q kept"
check "the app is downloaded again" [ "$(label "$APP" eink.commit)" = "$A" ]
check "the other volume is gone, as it said" bash -c "! podman volume exists other"
check "it says to delete the saved copy" grep -q "delete it once the app works" <<< "$out"
out=$(kit storage 2>&1)
check "again: nothing to change" grep -q "Podman keeps images with overlay: nothing to change" <<< "$out"
out=$(kit check 2>&1)
check "check says overlay" grep -q "ok    Podman keeps images with overlay" <<< "$out"

echo "== a Podman that holds nothing yet, as vfs: get changes it without asking"
as_vfs
check "it keeps images as vfs" [ "$(driver)" = vfs ]
out=$(kit get 2>&1)
check "get says it uses overlay now" grep -q "it uses overlay now" <<< "$out"
check "Podman keeps images with overlay" [ "$(driver)" = overlay ]
check "and the app is downloaded" [ "$(label "$APP" eink.commit)" = "$A" ]

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
