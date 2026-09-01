# MM OS — single container, single port.
#
# FastAPI (backend/app/main.py) serves the API and mounts the built React shell from
# frontend/dist on the same port — the ATT_Platform pattern already used on this VPS.
# main.py resolves both frontend/dist and packages/embed/embed.js relative to the repo
# root (three parents up from backend/app/main.py), so the directory layout below is
# not cosmetic: it is what main.py's Path(__file__).resolve().parents[2] expects.
#
# Build from the REPO ROOT, not from deploy/:
#   docker build -f deploy/Dockerfile -t mmos:local .
#
# Stage 1 builds frontend/dist. A3 (shell frontend) lands after this Dockerfile is
# written, so frontend/ may contain only frontend/README.md and an empty src/ — no
# package.json yet. The stage below guards for that: no package.json means no build,
# and an empty dist/ is copied forward. backend/app/main.py already treats a missing
# frontend/dist as optional (it only mounts StaticFiles when the directory exists), so
# an API-only image is a correct, working artifact — not a broken one.

# ---- Stage 1: frontend build -------------------------------------------------------
FROM node:20.20.2-bookworm-slim AS frontend-build
WORKDIR /src
COPY frontend/ ./
RUN set -eux; \
    mkdir -p dist; \
    if [ -f package.json ]; then \
        if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
        else npm install --no-audit --no-fund; fi; \
        npm run build; \
    else \
        echo "frontend/package.json not present yet (A3 not landed) — shipping API-only image"; \
    fi

# ---- Stage 2: python runtime --------------------------------------------------------
FROM python:3.12.14-slim-bookworm AS runtime

# Non-root user. No shell login needed; this only ever runs uvicorn.
RUN groupadd --system mmos && useradd --system --gid mmos --home-dir /app --no-create-home mmos
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Dependencies first for layer caching. requirements.txt is orchestrator-owned; this
# Dockerfile only installs it verbatim, never edits it.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY backend/app ./app

# Migrations. Added by the orchestrator after the first real `docker compose up`: this
# Dockerfile was written before A1's Alembic files existed, so the image shipped without them
# and `alembic upgrade head` inside the container failed with "No config file 'alembic.ini'
# found". /healthz still reported db:"up" because db_healthy() only issues SELECT 1, which
# needs no tables -- so nothing else caught it. Schema changes are applied by running
# `alembic upgrade head` in this container; without these two lines that is impossible.
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

# Everything main.py resolves relative to the repo root: embed.js and the built shell.
# packages/embed/ already exists as a directory (A4's deliverable, packages/embed/embed.js,
# has not landed yet at the time this Dockerfile was written) so COPY always succeeds; if
# embed.js itself is still absent inside it, GET /embed.js 500s at runtime rather than
# failing the build — that failure mode is A4's to close, not this Dockerfile's.
COPY packages/embed /app/packages/embed
COPY --from=frontend-build /src/dist /app/frontend/dist

# The signing key is a mounted secret file, never baked into the image — see
# deploy/docker-compose.yml and scripts/gen-signing-key.sh. This just makes sure the
# mount point exists with the right owner before uvicorn (running as `mmos`) starts.
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /run/secrets /data && chown -R mmos:mmos /app /run/secrets /data

# NOTE: no `USER mmos` here on purpose — entrypoint.sh starts as root only to chown the
# persisted /data volume, then re-execs itself as mmos via gosu, so the app runs unprivileged.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Pure python healthcheck: no curl in the base image, and adding one is an extra
# package for a single GET. /healthz is always open (see middleware.py ALWAYS_OPEN)
# regardless of MMOS_NETWORK_MODE, so this works in both private and public posture.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# Entrypoint runs optional migrate/seed steps, both default-off, then execs the same uvicorn
# command this CMD used to run directly. Production behaviour is unchanged unless
# MMOS_MIGRATE_ON_BOOT / MMOS_SEED_ON_BOOT are set.
CMD ["/app/entrypoint.sh"]
