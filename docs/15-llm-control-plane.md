# 15 · LLM control plane — the service-facing contract

MM OS is the ONE place every AI feature across every service is governed from. This document is
the contract a registered service implements to (1) fetch the AI policy MM OS imposes on it and
(2) report how much it used — authenticated by its service key, over plain HTTP.

The single most important line first:

> **MM OS never holds a provider API key.** Keys live in the service that calls the provider.
> MM OS governs *policy, enablement and usage*; it is a control plane, not a data plane. Every
> service-facing endpoint below strips any key-shaped field (`api_key`, `secret`, `password`,
> `access_token`, or a bare `key`) before it can be stored, and records that it did so in the
> audit log. `key_present` — a boolean — is the only key-adjacent thing MM OS keeps, so an admin
> can see *that* a service has a key configured without MM OS ever seeing the key itself.

## The model

- **Service level.** Each service has one `LlmRegistration` row: a service-wide kill switch
  (`enabled`), the provider/model it last reported, and `key_present`. Populated by the heartbeat.
- **Feature level.** A service has SEVERAL named AI features (e.g. Sales Hub's `lead_enrichment`,
  the matcher's `code_match`). Each is an `LlmFeature` row carrying: the provider/model the service
  *declared*, the policy MM OS *imposes* (`allowed_providers` / `allowed_models` allowlists — an
  empty list means "no restriction"), and a per-feature kill switch.
- **Effective enablement** for a feature is `service.enabled AND feature.enabled`. The service is
  handed the combined value and never has to AND them itself.
- **Usage** is metered per feature per day (`LlmFeatureUsageDaily`), accumulated, never overwritten.

None of these tables has a column that can store a secret (asserted by
`backend/tests/test_llm_control.py::test_control_plane_models_carry_no_key_field`).

## Endpoints (all `Authorization: Bearer <service_key>`)

### `GET /api/agent/llm/policy` — fetch my allowed AI policy

Poll this on your heartbeat cycle and cache the result; no LLM call belongs in the request path.

```json
{
  "llm_enabled": true,                 // service-level kill switch
  "config_version": 7,                 // monotonic; poll it, re-fetch policy when it changes
  "poll_after_seconds": 300,           // drops to 5s for 10 min after an admin kill
  "features": [
    {
      "feature_key": "lead_enrichment",
      "name": "Lead enrichment",
      "enabled": true,                 // EFFECTIVE (service AND feature) — honour this one
      "feature_enabled": true,         // the feature's own switch, for display
      "provider": "anthropic",
      "model": "claude-...",
      "allowed_providers": ["anthropic"],  // [] = unrestricted
      "allowed_models": []
    }
  ]
}
```

`config_version` is a single monotonically-increasing integer that bumps on ANY policy or
kill-switch change, service-level or feature-level. Cache against it: if it hasn't moved, your
cached policy is current.

### `POST /api/agent/llm/register` — declare my features

Declare features so they appear in MM OS governance *before* they are ever used. Idempotent —
re-declaring updates the declared provider/model, never resets the admin's policy or kill switch.

```json
{ "features": [ { "feature_key": "lead_enrichment", "name": "Lead enrichment",
                  "provider": "anthropic", "model": "claude-..." } ] }
```

Returns the same `{ llm_enabled, config_version, features }` shape as `/policy`, so you can act on
policy immediately after registering.

### `POST /api/agent/llm/usage` — report usage for one feature

```json
{ "feature_key": "lead_enrichment", "requests": 1,
  "input_tokens": 812, "output_tokens": 143, "day": "2026-08-29" }
```

Auto-registers the feature if MM OS has never seen it (so nothing is ever metered invisibly).
`day` is optional (defaults to today). Returns:

```json
{ "llm_enabled": true, "feature_enabled": true, "config_version": 7 }
```

so you can honour a kill switch on your next call without a separate policy fetch.

The service-wide `POST /api/agent/heartbeat` also carries an `llm` block (`provider`, `model`,
`key_present`) and a service-level `usage` block; that keeps the `LlmRegistration` row and the
service-level daily usage current. Per-feature detail comes from the three endpoints above.

## What a service must do

1. On boot, `POST /api/agent/llm/register` your features.
2. Before each AI call, check your cached `enabled` for that feature (refreshed from `/policy` or
   the heartbeat). If false, do not call the provider — degrade the same way `mmos_client.llm_guard()`
   does (503 `llm_disabled`), never drop the user's request silently.
3. Respect `allowed_providers` / `allowed_models` when non-empty.
4. After each AI call, `POST /api/agent/llm/usage`.
5. **Keep your provider API key in your own environment. Never send it to MM OS.** If you do, MM OS
   drops it and audits `heartbeat.key_rejected`; nothing breaks, but the key was needless risk.

## The admin side (for reference)

Behind `require_admin`, in `routers/platform.py`: `GET /api/admin/llm` (service-level overview),
`GET /api/admin/llm/features` (every feature everywhere), `GET /api/admin/llm/{slug}/features`,
`POST /api/admin/llm/{slug}/toggle`, `POST /api/admin/llm/{slug}/features/{feature_key}/toggle`,
`POST /api/admin/llm/{slug}/features/{feature_key}/policy`. All of these bump `config_version`.

Tested end-to-end in `backend/tests/test_llm_control.py`.
