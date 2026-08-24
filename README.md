# MM OS — MiniMines internal operating system

One login, one homepage, one permission map in front of every MiniMines service:
ERPNext, Item Code Studio, ATT Platform, Twenty CRM, Service Desk, and everything built next.

MM OS is **not** a reverse proxy and **not** a monolith. It is a control plane: it decides
*who you are*, *what you may open*, and *what a service is allowed to do* — then hands you
off to services that keep running independently in their own containers.

```
Google Workspace ──OIDC──▶ MM OS ──short-lived JWT──▶ each service (own container, own DB)
                            │
                            ├─ employees · services · grants   (authorization master)
                            ├─ /.well-known/jwks.json          (services verify offline)
                            ├─ /api/revocations                (services poll every 60s)
                            ├─ embed.js                        (shared "Back to MM OS" bar)
                            └─ LLM control plane               (see, enable, disable — never holds keys)
```

## Read in this order

| Doc | What it settles |
|---|---|
| [docs/01-architecture.md](docs/01-architecture.md) | The whole system, the decisions and why, what MM OS is not |
| [docs/02-data-model.md](docs/02-data-model.md) | Postgres schema, DDL, seeding from the employee sheet |
| [docs/03-api-contract.md](docs/03-api-contract.md) | Every endpoint, request/response shapes, token claims |
| [docs/04-auth-flow.md](docs/04-auth-flow.md) | Google OIDC, PIN fallback, JWT mint, deny-list revocation |
| [docs/05-service-integration.md](docs/05-service-integration.md) | The contract a service implements to join MM OS |
| [docs/06-network-security.md](docs/06-network-security.md) | Private-network mode, WireGuard, DNS-01 certs, threat notes |
| [docs/07-service-desk.md](docs/07-service-desk.md) | Tickets + automation requests, states, approval chain |
| [docs/08-v1-plan.md](docs/08-v1-plan.md) | Thinned v1 scope, milestones, task breakdown, definition of done |

## Layout

```
backend/                  FastAPI + SQLAlchemy; serves the built frontend on one port
frontend/                 Vite + React shell (tiles, admin, launcher)
packages/mmos-client-py/  drop-in auth client every Python service imports
packages/embed/embed.js   the OS bar injected into every service
deploy/                   Dockerfile, compose, .env.example, Coolify notes
demo/index.html           clickable look-and-feel prototype (no backend)
onepager/index.html       one-page architecture brief for management
```

## Start here

```bash
cp deploy/.env.example deploy/.env && docker compose -f deploy/docker-compose.yml up -d
```

Then seed people and services from the existing spreadsheet:

```bash
docker compose -f deploy/docker-compose.yml exec api python -m app.seed --xlsx /data/Employee_Role_Access_Mapping.xlsx
```

Open the demo with no setup at all: `demo/index.html` in any browser.
