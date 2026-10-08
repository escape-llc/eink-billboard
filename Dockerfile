# Container images for eInk Billboard: `test` reproduces CI (Linux, headless Chromium), `app` runs the server.
# Build:  podman build --target test -t eink-test .     |     podman build --target app -t eink-billboard .
# Normally driven through compose.yaml.

# --- web app bundle -------------------------------------------------------------------------
FROM node:22-slim AS web
# The type-check imports the shared rule cases from python/tests, so keep the repository layout.
WORKDIR /repo/app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app/ ./
COPY python/tests/form_rules.json python/tests/form_visibility.json ../python/tests/
RUN npm run build

# --- Python base: same OS packages and Python as .github/workflows/unittest.yaml ----------
FROM python:3.13.7-slim AS base
RUN apt-get update \
	&& apt-get install -y --no-install-recommends chromium-headless-shell unzip zip \
	&& rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
# The environment lives outside the source tree so a bind-mounted checkout (with a Windows .venv) cannot clobber it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
	UV_LINK_MODE=copy \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1
WORKDIR /work
COPY pyproject.toml uv.lock ./

# --- test: lint, type-check and run the unit tests; the source is bind-mounted by compose ---
FROM base AS test
RUN uv sync --frozen --no-group device --no-install-project
CMD ["sh", "-c", "uv run --no-sync ruff check && uv run --no-sync mypy && uv run --no-sync coverage run -m unittest discover . && uv run --no-sync coverage report"]

# --- app: the server with the built web app --------------------------------------------------
FROM base AS app
RUN uv sync --frozen --no-dev --no-group device --no-install-project
COPY python/ ./python/
COPY --from=web /repo/app/dist ./app/dist
RUN useradd --system --create-home eink && mkdir /data && chown eink /data
USER eink
VOLUME /data
EXPOSE 8080
# The token comes from EINK_API_TOKEN. Publish the port on localhost only unless a token is set (see compose.yaml).
CMD ["uv", "run", "--no-sync", "python", "-m", "python.eink-billboard", "--host", "0.0.0.0", "--port", "8080", "--storage", "/data", "--app", "/work/app/dist"]
