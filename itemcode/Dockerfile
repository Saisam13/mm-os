# Item Code Studio: one container, FastAPI serving a small built frontend on a single port —
# the same house pattern as servicedesk/Dockerfile / deploy/Dockerfile for MM OS.

FROM node:20.20.2-bookworm-slim AS frontend-build
WORKDIR /src
COPY itemcode/frontend/package.json itemcode/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY itemcode/frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm AS runtime
RUN useradd --create-home --shell /usr/sbin/nologin ic
WORKDIR /app/itemcode

COPY itemcode/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY itemcode/app ./app
COPY --from=frontend-build /src/dist ./frontend/dist

COPY itemcode/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && chown -R ic:ic /app

USER ic
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
