# 09 · Build plan for parallel agents

MM OS gets built by **nine agents across two runs**. Six build in parallel, three integrate.

The reason this can be parallel at all is that the contracts are already written and the
shared spine is already code. No agent has to guess what another agent will produce, and no
two agents ever open the same file.

## Before anything: make it a repo

```bash
cd "C:/Users/Anura/OneDrive/Desktop/MM OS"
git init -b main
git add -A
git commit -m "MM OS: contracts, frozen spine, agent briefs"
```

Everything below assumes this commit exists. It is the shared base every agent branches from.

## The frozen spine — no agent may edit these

These files are the contract. They are already written, they compile, and an agent that
"improves" one of them breaks every other agent silently.

```
backend/app/config.py        settings and the env contract
backend/app/models.py        the entire schema
backend/app/db.py            engine and session
backend/app/security.py      keys, JWT mint, sessions, PIN hashing
backend/app/deps.py          current user, guards, audit(), client_ip()
backend/app/middleware.py    network gate, request id, security headers
backend/app/main.py          app assembly and router wiring
docs/01 … docs/08            the specification
```

If an agent believes a frozen file is wrong, it **must not edit it**. It writes the problem
into `handoff/<agent>.md` under `## Contract objections` and proceeds with a local
workaround. I reconcile objections between runs. This single rule is what keeps six parallel
agents from producing an unmergeable mess.

## File ownership — one owner per path, no exceptions

| Agent | Owns exclusively |
|---|---|
| **A1** Identity and People | `backend/app/routers/{auth,me,people}.py`, `backend/app/seed.py`, `backend/alembic/**`, `backend/tests/test_identity*.py` |
| **A2** Tokens and Control Plane | `backend/app/routers/{tokens,agent,platform}.py`, `backend/tests/test_security*.py`, `backend/tests/test_platform*.py` |
| **A3** Shell frontend | `frontend/**` |
| **A4** Integration kit | `packages/mmos-client-py/**`, `packages/embed/**`, `examples/echo-service/**` |
| **A5** Service Desk | `servicedesk/**` |
| **A6** Infra and runbooks | `deploy/**`, `.github/workflows/**`, `scripts/**` |
| **B1** Assembly | anything, but only to make the parts fit — no new features |
| **B2** Retrofit | the ATT and Item Code Studio repos, plus `handoff/b2-retrofit.md` |
| **B3** Hardening | `docs/10-runbook.md`, `docs/11-security-review.md`, `scripts/verify/**` |

`backend/alembic/**` has exactly one owner (A1) because two agents both generating an initial
migration is the one merge conflict that cannot be auto-resolved.

## Run 1 — six agents, fully parallel

Launch each in its own worktree so they cannot see or disturb each other:

```bash
git worktree add ../mmos-a1 -b agent/a1-identity
git worktree add ../mmos-a2 -b agent/a2-tokens
git worktree add ../mmos-a3 -b agent/a3-shell
git worktree add ../mmos-a4 -b agent/a4-kit
git worktree add ../mmos-a5 -b agent/a5-desk
git worktree add ../mmos-a6 -b agent/a6-infra
```

Then open one Claude Code session per worktree and paste the matching brief from `agents/`
as the first message. Nothing else is needed — each brief is self-contained.

```
agents/A1-identity.md     agents/A2-tokens.md      agents/A3-shell.md
agents/A4-integration.md  agents/A5-servicedesk.md agents/A6-infra.md
```

**Dependency graph for run 1: there isn't one.** All six are independent because
`docs/03-api-contract.md` fixes every shape they exchange, and `models.py` is already written.
A3 builds the shell against the documented JSON without waiting for A1 to serve it.

## Run 2 — three agents

```bash
git worktree add ../mmos-b1 -b agent/b1-assembly
git worktree add ../mmos-b2 -b agent/b2-retrofit
git worktree add ../mmos-b3 -b agent/b3-hardening
```

B1 must merge first. B2 and B3 branch from B1 output, so run B1 to completion, then launch
B2 and B3 in parallel against the merged branch.

```
agents/B1-assembly.md   agents/B2-retrofit.md   agents/B3-hardening.md
```

## Merge order

```
a6-infra  →  a1-identity  →  a2-tokens  →  a4-kit  →  a3-shell  →  a5-desk
```

Infra first so there is something to run against. Identity before tokens because the
migration lands with A1. Frontend late because it is the least likely to conflict and the
most likely to need a tweak once the API is real.

Merge conflicts should be near zero. If two branches touch one file, that is a brief
violation — record it in the handoff rather than resolving it creatively.

## Every agent ends by writing its handoff

`handoff/<agent-id>.md`, and nothing is considered done without it:

```markdown
# A1 · Identity and People
## Delivered            what exists now, file by file
## Deviations           where I departed from the docs, and why
## Contract objections  frozen-file problems I did NOT fix
## Assumptions          decisions I made that a human should confirm
## Not done             what I left, and what it blocks
## How to verify        exact commands, expected output
```

The `Assumptions` and `Contract objections` sections are the ones that matter. An agent that
silently guesses is worse than one that guesses loudly.

## Credit guardrails

These are instructions to the agents, repeated in every brief:

1. **Do not refactor.** Not the frozen spine, not another agent's code, not the docs. Add only.
2. **No new dependencies** beyond `backend/requirements.txt` without recording it in the
   handoff. No package that needs a compiler.
3. **Do not write the same thing twice.** If a doc already specifies it, implement it — do not
   restate it in comments or a new markdown file.
4. **Tests are targeted, not exhaustive.** The listed acceptance tests, plus anything
   security-relevant. No coverage chasing.
5. **Stop and hand off** rather than escalating: if the same failure resists two fixes, write
   it up under `Not done` and move on.
6. **No demo data beyond the seed.** No fixtures generating hundreds of fake rows.
7. **Never touch `.env`, real secrets, or the live ERPNext instance.**

## Definition of done for run 1

- `docker compose -f deploy/docker-compose.yml up` brings up Postgres and the API
- `GET /healthz` returns `{"ok":true,"db":"up"}`
- `GET /.well-known/jwks.json` returns one RSA key
- all 74 employees import from the spreadsheet with a dry-run diff first
- a Google login and a PIN login both produce a session, and `/api/me` returns the documented shape
- `POST /api/token/service` mints a token that `examples/echo-service` accepts, and rejects one minted for a different `aud`
- removing a grant blocks access at the echo service within 60 seconds
- the shell renders tiles from a real `/api/me` and the OS bar appears on the echo service
- Service Desk runs standalone and takes an automation request through the full approval chain
- every agent left a handoff file

## Definition of done for run 2

- one branch, one deploy, everything wired
- ATT and Item Code Studio authenticate through MM OS, PIN gates deleted, public item-code lookup still anonymous
- the acceptance script in `scripts/verify/` passes end to end
- `docs/10-runbook.md` exists and a restore from backup has been performed once
- the eight v1 criteria in `docs/08-v1-plan.md` are each ticked with evidence
