# Agent Instructions — McFox Health

Personal health data warehouse (Mateo's). AWS SAM backend in **us-west-2** (stack `fitness-dashboard`), Python 3.13 Lambdas, DynamoDB, Vite/React PWA on Vercel.

## Read these first, in order

1. **[`RUNBOOK.md`](RUNBOOK.md)** — 🚨 **mandatory before touching the ingest pipeline.** Operational traps that have already caused real bugs, the deploy recipe, health checks, and which feeds only Mateo can fix.
2. [`CLAUDE.md`](CLAUDE.md) — stack, repo layout, the 5 Lambdas, auth, shared-layer conventions.
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) / [`architecture.json`](architecture.json) — data flows.
4. [`PRISM_PRODUCT_ARCHITECTURE.md`](PRISM_PRODUCT_ARCHITECTURE.md) — approved product north star, capability ownership, evidence layers, roadmap gates, and product references.
5. [`HANDOFF.md`](HANDOFF.md) — current product overview + frontend/backend API contract.

## Non-negotiable rules

1. **READ-ONLY against third-party APIs** (Hevy, Strava, Withings). Never POST/PUT to Mateo's accounts.
2. **Never fabricate health data.** No invented metrics, doses, or calibration values. If you can't verify something, say so explicitly.
3. **Do not try to fix Apple Health / HAE.** It's an iPhone app with on-device HealthKit data — no agent can restart, re-auth, or trigger it. Surface the problem to Mateo instead.
4. **Verify, don't trust.** A tool call returning `success` is not proof of effect. Query the data. This applies to Lambda summaries, CloudFormation status, and your own self-reports.
5. **Don't trust vendor OpenAPI specs for field names** — Hevy's is demonstrably wrong (`superset_id` live vs `supersets_id` documented). Dump a real payload and diff the keys. Make test fixtures mirror live payloads, never spec docs: fixtures that share the code's wrong assumption produce green tests over broken code.
6. **Report unexplained zeros as unexplained.** Don't attach a causal story to an empty field without evidence.
7. **PR-only by default.** Merging and deploying require Mateo's explicit approval. When a PR changes `template.yaml` IAM grants, merge and deploy together or production hits `AccessDenied`.
8. **Clone fresh** for deploys and agent work — don't reuse a stale local checkout.
9. **Update `RUNBOOK.md` in the same PR** that changes deploy steps, adds a Lambda action, or uncovers a new trap. Same discipline as `ARCHITECTURE.md`.
10. **Do not start PR5 before foundation closeout.** Read `PRISM_FOUNDATION_STATUS.md` and the gates in `PRISM_PRODUCT_ARCHITECTURE.md`; reverify their dated evidence. Active HR/Sleep outages block PR5. A real HAE workout payload gates PR7 workout ingestion only.
11. **Chat is the current PRISM Coach interface; McFox is the long-term integrated product.** Do not infer the Canonical Specification from a handoff pointer or runtime UI.

## Testing

```bash
cd backend && .venv/bin/python -m pytest tests \
  --deselect tests/test_api_contract.py --deselect tests/test_coach_auth.py -q
```
The **224 passing** count is historical (2026-07-27), not a current baseline.
`test_api_contract.py` includes live-network checks. Install the Coach test
dependencies before including `test_coach_auth.py`; a missing `fastapi` package
is an environment gap, not proof of a product failure. State actual exclusions
and results for each validation run.

## Conventions

- Branches: `hermes/<role>/<slug>` (e.g. `hermes/builder/fix-hevy-superset-id-field`)
- Conventional commits, plus an `Agent: hermes/<role>` trailer
- Shared code lives ONLY in `backend/shared/shared/` and ships as a Lambda layer — never create per-function copies
- `prototype/` is an archived April 2026 snapshot — do not touch
