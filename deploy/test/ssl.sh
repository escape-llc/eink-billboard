#!/usr/bin/env bash
# The kit's HTTPS (deploy/eink-container.sh ssl), end to end, with no Pi: in a Debian Bookworm container (the Pi's Podman 4.3), rootless Podman runs a
# stand-in for the app's image (its user is a system user, as the real one's is, and its "uv" serves /api/access over HTTPS with the files it was given,
# the way uvicorn does). The real script then turns HTTPS on with the device's own certificate (the stand-in makes one, as the app does), with a
# certificate of one's own (two Podman secrets that only the app's user can read), off again, and forgets the certificate.
#
#   podman run --rm --privileged -v "$PWD:/src:ro" docker.io/library/debian:bookworm bash /src/deploy/test/ssl.sh
#   (Git Bash on Windows: MSYS_NO_PATHCONV=1, and "$(pwd -W)" for the folder)
#
# Run as root it installs what it needs, makes a user and runs itself again as that user (the script refuses root, as on a Pi). Exit 0: every check passed.
set -u
set -o pipefail

CLONE=/home/pi/eink-billboard

if [ "$(id -u)" -eq 0 ]; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq && apt-get install -y -qq --no-install-recommends podman uidmap slirp4netns curl ca-certificates openssl procps >/dev/null || { echo "could not install the tools"; exit 1; }
	id pi >/dev/null 2>&1 || useradd -m -s /bin/bash pi
	# a range inside this container's own (a container has 65536 ids)
	grep -q '^pi:' /etc/subuid || echo "pi:2000:60000" >> /etc/subuid
	grep -q '^pi:' /etc/subgid || echo "pi:2000:60000" >> /etc/subgid
	install -d -o pi -g pi /home/pi/.config/containers /run/user-pi
	chmod 700 /run/user-pi
	printf '[storage]\ndriver = "vfs"\n' > /home/pi/.config/containers/storage.conf
	printf '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n' > /home/pi/.config/containers/containers.conf
	chown -R pi:pi /home/pi/.config
	install -d -o pi -g pi "$CLONE"
	tar -C /src --exclude=.git --exclude=node_modules --exclude=.venv --exclude='.storage*' --exclude='.e2e-storage' --exclude=.env -cf - . | tar -C "$CLONE" -xf -
	chown -R pi:pi "$CLONE"
	exec runuser -u pi -- env HOME=/home/pi XDG_RUNTIME_DIR=/run/user-pi bash /src/deploy/test/ssl.sh
fi

passed=0
failed=0
check() {
	local what=$1
	shift
	if "$@"; then passed=$((passed + 1)); echo "  ok    $what"; else failed=$((failed + 1)); echo "  FAIL  $what"; fi
}
kit() { (cd "$CLONE" && EINK_PUBLIC_URL="$1://localhost:8080" EINK_ALLOW_HOSTS=localhost deploy/eink-container.sh "${@:2}"); }
contains() { grep -qF -- "$2" <<< "$1"; }
args_of() { podman inspect -f '{{join .Config.Cmd " "}}' eink 2>/dev/null; }

# the stand-in: "uv run --no-sync python -m python.eink-billboard ... [--ssl [--ssl-certfile C --ssl-keyfile K]]" serves the app's /api/access
mkdir -p ~/standin && cd ~/standin || exit 1
cat > serve.py <<'PY'
import http.server, json, os, ssl, subprocess, sys
args = sys.argv[1:]
def value(name):
	return args[args.index(name) + 1] if name in args else None
class Answer(http.server.BaseHTTPRequestHandler):
	def do_GET(self):
		body = json.dumps({ "setupRequired": False, "scheme": "https" if "--ssl" in args else "http" }).encode()
		self.send_response(200)
		self.send_header("content-type", "application/json")
		self.end_headers()
		self.wfile.write(body)
server = http.server.HTTPServer(("0.0.0.0", 8080), Answer)
if "--ssl" in args:
	cert, key = value("--ssl-certfile"), value("--ssl-keyfile")
	if not cert:
		# the device's own, in its storage (the app makes it with the configuration manager)
		cert, key = "/data/tls/certificate.pem", "/data/tls/key.pem"
		os.makedirs("/data/tls", exist_ok=True)
		subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-subj", "/CN=localhost",
			"-days", "30", "-keyout", key, "-out", cert], check=True, capture_output=True)
	# the app's user must read both, as uvicorn does
	context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
	context.load_cert_chain(cert, key)
	server.socket = context.wrap_socket(server.socket, server_side=True)
print("serving", flush=True)
server.serve_forever()
PY
printf '#!/bin/sh\n# uv run --no-sync python -m python.eink-billboard ARGS\nshift 3\nshift 2\nexec python3 /serve.py "$@"\n' > uv
cat > Containerfile <<'CF'
FROM docker.io/library/debian:bookworm-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 openssl >/dev/null && rm -rf /var/lib/apt/lists/*
RUN useradd --system --create-home eink && mkdir /data && chown eink /data
COPY serve.py /serve.py
COPY uv /usr/local/bin/uv
RUN chmod 755 /usr/local/bin/uv
USER eink
CMD ["uv", "run", "--no-sync", "python", "-m", "python.eink-billboard"]
CF
podman build -q -t localhost/eink-device . >/dev/null || { echo "the stand-in image could not be built"; exit 1; }
cd ~ || exit 1

echo "== plain HTTP"
out=$(kit http start 2>&1)
check "it starts and answers on http" contains "$out" "ready."
check "no --ssl" bash -c '! grep -q -- "--ssl" <<< "$1"' _ "$(args_of)"
check "ssl alone says plain HTTP" contains "$(kit http ssl 2>&1)" "Plain HTTP"

echo "== HTTPS with the device's own certificate"
out=$(kit https ssl on 2>&1)
check "it starts again and answers on https" contains "$out" "ready."
check "it says the browser warns (self-signed)" contains "$out" "self-signed"
check "--ssl, and no files of one's own" bash -c 'grep -q -- "--ssl" <<< "$1" && ! grep -q -- "--ssl-certfile" <<< "$1"' _ "$(args_of)"
check "the app answers https" bash -c 'curl -fsSk https://127.0.0.1:8080/api/access | grep -q "\"scheme\": \"https\""'
check "plain http is not served" bash -c '! curl -fsS --max-time 3 http://127.0.0.1:8080/api/access >/dev/null 2>&1'
check "remembered" bash -c '[ "$(cat ~/.config/eink-billboard/ssl)" = on ]'
check "check says which" contains "$(kit https check 2>&1)" "device's own self-signed"

echo "== HTTPS with a certificate of one's own"
umask 077
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj /CN=localhost -days 30 -keyout mine.key -out mine.pem 2>/dev/null
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -subj /CN=localhost -days 30 -passout pass:secret -keyout locked.key -out locked.pem 2>/dev/null
check "a key with a passphrase is refused" contains "$(kit https ssl on ~/locked.pem ~/locked.key 2>&1)" "has a passphrase"
check "a key is not a certificate" contains "$(kit https ssl on ~/mine.key ~/mine.key 2>&1)" "not a certificate"
out=$(kit https ssl on ~/mine.pem ~/mine.key 2>&1)
check "kept as secrets, started, answering" bash -c 'grep -q "Podman secrets" <<< "$1" && grep -q "ready." <<< "$1"' _ "$out"
check "the files are passed from /run/secrets" contains "$(args_of)" "--ssl-certfile /run/secrets/eink-tls-cert --ssl-keyfile /run/secrets/eink-tls-key"
check "the key is the app's user's only" bash -c '[ "$(podman exec eink stat -c "%a %U" /run/secrets/eink-tls-key)" = "400 eink" ]'
served=$(echo | openssl s_client -connect 127.0.0.1:8080 2>/dev/null | openssl x509 -noout -fingerprint -sha256)
check "the certificate served is the one given" bash -c '[ "$1" = "$(openssl x509 -in mine.pem -noout -fingerprint -sha256)" ]' _ "$served"
check "the files given were not copied into the data" bash -c '! podman exec eink ls /data/tls/key.pem 2>/dev/null | grep -q . || [ "$(podman exec eink cat /data/tls/certificate.pem | openssl x509 -noout -fingerprint -sha256)" != "$1" ]' _ "$served"
check "giving another replaces it" contains "$(kit https ssl on ~/mine.pem ~/mine.key 2>&1)" "ready."

echo "== off, and forget"
out=$(kit http ssl off 2>&1)
check "plain HTTP again" bash -c 'grep -q "Plain HTTP again" <<< "$1" && grep -q "ready." <<< "$1" && ! grep -q -- "--ssl" <<< "$2"' _ "$out" "$(args_of)"
check "the certificate given is kept for the next on" bash -c 'podman secret inspect eink-tls-cert >/dev/null 2>&1'
out=$(kit https ssl on 2>&1)
check "on again uses it" contains "$(args_of)" "--ssl-certfile /run/secrets/eink-tls-cert"
out=$(kit https ssl forget 2>&1)
check "forget removes the secrets and goes on with the device's own" bash -c 'grep -q "device'"'"'s own" <<< "$1" && ! podman secret inspect eink-tls-cert >/dev/null 2>&1 && grep -q "ready." <<< "$1"' _ "$out"
check "nothing of one's own is passed after forget" bash -c '! grep -q -- "--ssl-certfile" <<< "$1"' _ "$(args_of)"
check "forget again says there is nothing" contains "$(kit https ssl forget 2>&1)" "no certificate of yours"
check "a wrong word is refused" contains "$(kit https ssl maybe 2>&1)" "ssl takes on"

podman rm -f eink >/dev/null 2>&1
echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
