# Service Desk: one container, FastAPI serving the built React app on a single port —
# the same house pattern as deploy/Dockerfile for MM OS.

FROM node:20.20.2-bookworm-slim AS frontend-build
WORKDIR /src
COPY servicedesk/frontend/package.json servicedesk/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY servicedesk/frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm AS runtime
RUN useradd --create-home --shell /usr/sbin/nologin sd
WORKDIR /app/servicedesk

COPY servicedesk/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY servicedesk/app ./app
# http mode does `from mmos_client.core import MMOS`; the package lives in the monorepo
# (build context is repo root) and must be present in the image or the app crashes on boot.
COPY packages/mmos-client-py/mmos_client ./mmos_client
COPY servicedesk/alembic ./alembic
COPY servicedesk/alembic.ini ./alembic.ini
COPY --from=frontend-build /src/dist ./frontend/dist

COPY servicedesk/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && chown -R sd:sd /app

USER sd
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
