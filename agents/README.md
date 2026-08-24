# Run sheet — launching the build agents

Full rationale is in [`../docs/09-build-agents.md`](../docs/09-build-agents.md). This page is
the operating instructions.

## 0 · Once, before anything

```bash
cd "C:/Users/Anura/OneDrive/Desktop/MM OS"
git init -b main
git add -A
git commit -m "MM OS: contracts, frozen spine, agent briefs"
```

## 1 · Run one — six agents, in parallel

```bash
git worktree add ../mmos-a1 -b agent/a1-identity
git worktree add ../mmos-a2 -b agent/a2-tokens
git worktree add ../mmos-a3 -b agent/a3-shell
git worktree add ../mmos-a4 -b agent/a4-kit
git worktree add ../mmos-a5 -b agent/a5-desk
git worktree add ../mmos-a6 -b agent/a6-infra
```

Open one Claude Code session per worktree. As the **first message** in each session, paste the
whole matching brief:

| Worktree | Brief | Builds |
|---|---|---|
| `../mmos-a1` | [`A1-identity.md`](A1-identity.md) | Google login, PIN login, `/api/me`, admin people, spreadsheet importer, the only migration |
| `../mmos-a2` | [`A2-tokens.md`](A2-tokens.md) | Token minting, JWKS, deny-list, heartbeat, admin services/grants/LLM/audit |
| `../mmos-a3` | [`A3-shell.md`](A3-shell.md) | The React shell — login, tiles, admin screens, PWA |
| `../mmos-a4` | [`A4-integration.md`](A4-integration.md) | `mmos-client-py`, `embed.js`, and an echo service that proves the contract |
| `../mmos-a5` | [`A5-servicedesk.md`](A5-servicedesk.md) | Service Desk, its own container and database |
| `../mmos-a6` | [`A6-infra.md`](A6-infra.md) | Dockerfile, compose, Coolify, WireGuard, DNS-01 certs, backups, CI |

Nothing else needs saying to them. Each brief carries its own context, its file ownership, its
acceptance tests and its guardrails.

**They are genuinely independent** — no agent waits on another, because the contracts in
`docs/02` through `docs/05` fix every shape they exchange.

## 2 · Between runs — 15 minutes of your time

Read the six `handoff/*.md` files, and only these two sections in each:

- `## Contract objections` — an agent claims a frozen file is wrong. You decide.
- `## Assumptions` — an agent guessed. Confirm or correct it.

Everything else is reference. This step is what stops a wrong guess from being built on twice.

## 3 · Run two — assemble, retrofit, harden

```bash
git worktree add ../mmos-b1 -b agent/b1-assembly
```

Run **B1 alone and to completion** — it merges the six branches and produces the acceptance
script. Then branch the other two from its result and run them together:

```bash
git worktree add ../mmos-b2 -b agent/b2-retrofit agent/b1-assembly
git worktree add ../mmos-b3 -b agent/b3-hardening agent/b1-assembly
```

| Worktree | Brief | Does |
|---|---|---|
| `../mmos-b1` | [`B1-assembly.md`](B1-assembly.md) | Merges everything, fixes the seams, writes `scripts/verify/acceptance.sh` |
| `../mmos-b2` | [`B2-retrofit.md`](B2-retrofit.md) | Moves ATT Platform and Item Code Studio onto MM OS, deletes their PIN gates |
| `../mmos-b3` | [`B3-hardening.md`](B3-hardening.md) | Security review, runbook, verification scripts, floor guide |

B2 works in the *other* repos on the Desktop and commits to a branch in each — never `main`,
never force-push. Those are tools people use daily.

## Cleaning up

```bash
git worktree list
git worktree remove ../mmos-a1        # after merging
```

## If an agent goes off the rails

The three rules it was given, in order of importance:

1. **It may not edit the frozen spine** — `backend/app/{config,models,db,security,deps,middleware,main}.py`. An objection goes in the handoff instead.
2. **It may not touch another agent's paths.** The ownership table is in `docs/09`.
3. **It stops after two failed fixes** and writes the problem under `## Not done`.

A stuck agent that documented where it stopped is a good outcome. Restart it with the same
brief plus a line naming what to skip.
