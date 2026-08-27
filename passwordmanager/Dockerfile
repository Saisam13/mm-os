# Password Manager: one container, FastAPI serving the built frontend on a single port —
# the same house pattern as servicedesk/Dockerfile / deploy/Dockerfile.

FROM node:20.20.2-bookworm-slim AS frontend-build
WORKDIR /src
COPY passwordmanager/frontend/package.json passwordmanager/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY passwordmanager/frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm AS runtime
RUN useradd --create-home --shell /usr/sbin/nologin pwmgr
WORKDIR /app/passwordmanager

COPY passwordmanager/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY passwordmanager/app ./app
COPY --from=frontend-build /src/dist ./frontend/dist

COPY passwordmanager/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && chown -R pwmgr:pwmgr /app

USER pwmgr
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["/app/entrypoint.sh"]
