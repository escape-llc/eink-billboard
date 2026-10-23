# Container images for eInk Billboard: `test` reproduces CI (Linux, headless Chromium), `app` runs the server.
# Build:  podman build --target test -t eink-test .     |     podman build --target app -t eink-billboard .
# Normally driven through compose.yaml.

# --- web app bundle -------------------------------------------------------------------------
FROM node:24-slim AS web
# The type-check imports the shared rule cases from python/tests, so keep the repository layout.
WORKDIR /repo/app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app/ ./
COPY python/tests/form_rules.json python/tests/form_visibility.json ../python/tests/
# The commit the image is built from, set only here, after the dependencies: a new commit always runs the build again (it is part of the bundle, so a build kept from
# an earlier commit can never be reused), and the page can say which build it is.
ARG EINK_COMMIT=dev
ENV EINK_COMMIT=$EINK_COMMIT
RUN npm run build

# --- Python base: same OS packages and Python as .github/workflows/unittest.yaml ----------
# Pinned by digest as uv is (#568): Docker Hub republishes a tag when Debian ships fixes, and a new base changes every layer above it, so every Pi would download
# the whole image again on a day nobody chose. Dependabot (docker) proposes the next one.
FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b AS base
# apt runs without anyone to ask: no debconf prompt (and no "Can't locate Term/ReadLine.pm" while it looks for one). An ARG, so it is not left in the image.
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update 	&& apt-get install -y --no-install-recommends chromium-headless-shell unzip zip 	&& rm -rf /var/lib/apt/lists/*
# uv pinned by version and digest (#456): the version setup-uv gave CI when it was pinned; Dependabot (docker) proposes the next
COPY --from=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /uvx /usr/local/bin/
# The environment lives outside the source tree so a bind-mounted checkout (with a Windows .venv) cannot clobber it. uv's download cache is a cache mount on
# every `uv sync` (#557): kept between builds, never in a layer (left in the image it was 157 MB of wheels nobody uses once they are installed).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv 	UV_LINK_MODE=copy 	PYTHONDONTWRITEBYTECODE=1 	PYTHONUNBUFFERED=1
WORKDIR /work
COPY pyproject.toml uv.lock ./

# --- test: lint, type-check and run the unit tests; the source is bind-mounted by compose ---
FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-group device --no-install-project
CMD ["sh", "-c", "uv run --no-sync ruff check && uv run --no-sync mypy && uv run --no-sync coverage run -m unittest discover . && uv run --no-sync coverage report"]

# The layers of an image change in the order they are listed, so what rarely changes comes first and the commit and the code last (#568): the dependencies, the
# app's user and the device drivers are the same layers from one commit to the next, and an update downloads only the code. (When the code came before the
# drivers, every commit built lgpio again and every Pi downloaded the drivers again.) `app` and `app-device` each end with the same few lines for that reason.

# --- deps: the app's dependencies and its user, with no code ---------------------------------
FROM base AS deps
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-group device --no-install-project
RUN useradd --system --create-home eink && mkdir /data && chown eink /data

# --- app: the server with the built web app --------------------------------------------------
FROM deps AS app
# after the dependencies, before the code: the server says which commit it is (GET /api/system), to be compared with the web app's
ARG EINK_COMMIT=dev
ENV EINK_COMMIT=$EINK_COMMIT
COPY python/ ./python/
COPY --from=web /repo/app/dist ./app/dist
USER eink
VOLUME /data
EXPOSE 8080
# The token comes from EINK_API_TOKEN. Publish the port on localhost only unless a token is set (see compose.yaml).
CMD ["uv", "run", "--no-sync", "python", "-m", "python.eink-billboard", "--host", "0.0.0.0", "--port", "8080", "--storage", "/data", "--app", "/work/app/dist"]

# --- device-deps: deps with the display drivers installed (the `device` group) -----------------
# The container has no panel, no SPI and no I2C: the driver imports and tries to read the board's EEPROM, finds nothing and fails the way a Pi with the board
# unplugged or I2C off does; scripts/fake_inky.py can pretend there is a board, to get the flow farther. (`spidev` has no wheel: it is built here.)
FROM deps AS device-deps
ARG DEBIAN_FRONTEND=noninteractive
# The Pi 5's pins need the `lgpio` Python package, which is built from its source package against the C library `lg`: Debian has no package for it (Raspberry Pi OS does), so
# that is built here from a pinned release of the same author (v0.2.2, checked by hash), with `swig` and the compiler. They are removed in the same step (#557), so
# they are never in a layer: kept, they were about 250 MB of the image that nothing uses once the drivers are built. ca-certificates stays (HTTPS needs it).
RUN --mount=type=cache,target=/root/.cache/uv apt-get update 	&& apt-get install -y --no-install-recommends build-essential swig curl ca-certificates 	&& rm -rf /var/lib/apt/lists/* 	&& curl -fsSL -o /tmp/lg.tgz https://github.com/joan2937/lg/archive/refs/tags/v0.2.2.tar.gz 	&& echo "b08d8569d6dc8fa91a42ba1e37f620fdcb19d6bf2330e4b7d7301431ddbe124c  /tmp/lg.tgz" | sha256sum -c - 	&& tar xzf /tmp/lg.tgz -C /tmp 	&& make -C /tmp/lg-0.2.2 liblgpio.so 	&& cp /tmp/lg-0.2.2/liblgpio.so /usr/local/lib/liblgpio.so.1 && ln -s liblgpio.so.1 /usr/local/lib/liblgpio.so 	&& cp /tmp/lg-0.2.2/lgpio.h /usr/local/include/ && ldconfig 	&& rm -rf /tmp/lg.tgz /tmp/lg-0.2.2 	&& uv sync --frozen --no-dev --group device --no-install-project 	&& apt-get purge -y --auto-remove build-essential swig curl 	&& rm -rf /var/lib/apt/lists/*
COPY scripts/fake_inky.py scripts/fake_waveshare.py ./scripts/

# --- app-device: the server with the drivers, to troubleshoot their failure flows (Inky #281, Waveshare); the image a Pi downloads -----
FROM device-deps AS app-device
ARG EINK_COMMIT=dev
ENV EINK_COMMIT=$EINK_COMMIT
COPY python/ ./python/
COPY --from=web /repo/app/dist ./app/dist
USER eink
VOLUME /data
EXPOSE 8080
# `import lgpio` makes a small notification file in its working directory, and /work is not the app user's: without this the import fails (FileNotFoundError '.lgd-nfy-3')
ENV LG_WD=/tmp
# the server through the pretend Inky board (`EINK_FAKE_INKY`, see scripts/fake_inky.py); with none set the driver is the real one and finds no board
# (the app-waveshare service starts scripts/fake_waveshare.py instead)
CMD ["uv", "run", "--no-sync", "python", "-m", "scripts.fake_inky", "--host", "0.0.0.0", "--port", "8080", "--storage", "/data", "--app", "/work/app/dist"]
