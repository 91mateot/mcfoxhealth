# McFox Health Tracker

Personal health/fitness dashboard. Vite+TS PWA on Vercel, AWS Lambda backend, Whoop-calibrated scoring.

> **Product direction:** McFox is evolving into PRISM, a personal performance
> operating surface rather than another tracker or readiness-score clone. Read
> [`PRISM_PRODUCT_ARCHITECTURE.md`](PRISM_PRODUCT_ARCHITECTURE.md) before
> product, evidence-model, longitudinal-reasoning, source-health, or roadmap
> work. PR5 remains blocked on the manual HAE Source Validation Gate.

## Stack

- **Frontend**: Vite 5 + React 18 + TypeScript + SWR. No CSS framework. Deployed to Vercel (`mcfoxhealth.vercel.app`, auto-deploy on push to `main`).
- **Backend**: AWS SAM, Python 3.13 Lambdas, DynamoDB, EventBridge. Stack name `fitness-dashboard` in `us-west-2`.
- **Integrations**: Apple Health (via HealthAutoExport), Withings, Strava, **Hevy** (strength/lifting — daily API poll, set-level detail), Claude Bedrock.

> ⚠️ **Read [`RUNBOOK.md`](RUNBOOK.md) before touching the ingest pipeline.** It documents the operational traps that have already caused real bugs — Hevy's OpenAPI spec having wrong field names, the `pageSize` cap of 10, the DynamoDB `Scan` 1000-item cap, zeros that mean "unavailable" not "zero", and which feeds only Mateo can fix (HAE is iPhone-side).

## Repo layout

```
src/              Frontend — screens, modals, components, api.ts, types.ts
backend/
  template.yaml           SAM template (5 Lambdas, 11 DynamoDB tables, 1 Lambda Layer)
  shared/shared/          Canonical shared package (scoring, db, timezone, nutrition, ...)
  shared/Makefile         Builds SharedLayer during sam build
  functions/{api,coach,compute,ingest,nutrition}/  Lambda entrypoints
  scripts/                Backfill + auth helpers
  tests/                  pytest suite
prototype/        Archived Babel-standalone snapshot — DO NOT TOUCH
uploads/          Reference docs (scoring guides, protocols, training notes)
withings-mcp/     Separate public repo (submodule-like), Withings MCP server
HANDOFF.md        Stack overview + known gaps
SCORING-ALGORITHMSfromClaudeChat.md   Reference-quality scoring doc
```

## Five Lambdas

- **ingest** — `POST /ingest/{health,withings,strava}`; HAE uses `x-api-key`, Strava trusts the verify_token handshake + URL secrecy (no per-request signature — Strava doesn't send one), Withings checks a `userid` allowlist from the OAuth secret.
- **compute** — Daily cron 2am PT (baselines, scores, sleep quality), weekly cron Sun 6am PT (correlations + event rollup).
- **api** — `GET /api/*` reads (today, progress, workouts, nutrition, insights, conversations, infra-cost).
- **nutrition** — `POST/PATCH/DELETE /api/{meal,water,journal,workout,favorites,calibration,feedback,event}` writes.
- **coach** — Streaming chat via Function URL (RESPONSE_STREAM, not behind API Gateway). FastAPI + Lambda Web Adapter.

## Auth

- Every `/api/*` request requires `x-api-key` header. Value lives in Secrets Manager (`fitness-api-key`) with env-var fallback (`INGEST_API_KEY`).
- Frontend reads `VITE_API_KEY` (set in Vercel env) and sends on every API call, including the coach stream.
- Coach Function URL is `AuthType=NONE` (required for streaming) + app-level `x-api-key` check via a FastAPI dep. `/health` stays public for the Lambda Web Adapter health probe. `COACH_AUTH_REQUIRED=0` bypasses for local runs.
- Ingest endpoints: HAE checks `x-api-key`; Strava webhooks aren't per-POST signed — security is the GET verify_token handshake at subscription time + URL secrecy + the activity re-fetch on every event (a spoofed POST with an unknown id 200s as ignored); Withings notifications reject unknown userids when the `withings-oauth` secret carries `userid`/`user_id`/`userids`.

## Shared code = Lambda Layer

`backend/shared/shared/*.py` is the canonical source. `shared/Makefile` builds it into a `SharedLayer` that all 5 Lambdas reference. Do **not** create per-function copies of shared code — the layer is the single source of truth.

Gotcha: SAM's `CustomMakeBuilder` runs `make` from a random temp dir, so the Makefile uses `$(MAKEFILE_LIST)` to resolve source paths. Don't use relative paths in that Makefile.

## Common commands

```bash
# Frontend
npm run dev            # local dev server
npm run build          # prod build (runs tsc -b + vite build)
npm run typecheck      # typecheck only

# Backend
cd backend
.venv/bin/python -m pytest backend/tests --deselect backend/tests/test_api_contract.py   # unit tests (contract tests hit live API)
sam build
sam deploy --stack-name fitness-dashboard --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset
```

## Scoring

See `SCORING-ALGORITHMSfromClaudeChat.md` for the full reference. Key points:
- **Recovery** = weighted composite of HRV/RHR/sleep/resp/SpO2/wrist_temp. Missing signals redistribute weight proportionally (Oura convention). Sleep is treated as missing (not broken-0) when its `quality_flag != ok`, so truncated nights degrade HRV/RHR weighting rather than tanking the score.
- **Strain** = 21 × (1 − e^(−TRIMP/300)), zone-weighted TRIMP (Edwards 1993).
- **Sleep** = Oura-style 4-component (35/25/20/20) by default. When `continuity_idx` is available (segments from unaggregated HAE present), upgrades to 5-component (30/20/15/15/20) adding continuity — Bevel/Whoop-style "restorative vs disturbances." `shared/sleep_quality.py` owns quality flags + segment math; see the Sleep pipeline section below.
- Weights live in `fitness-user-config` (hot-swappable). Each daily score row snapshots the `recovery_weights_used` + `strain_coefficient` that produced it, so retrospective scores stay reproducible after tuning.
- Baselines: rolling 14-day average, recomputed nightly.

## Sleep pipeline

- **Ingest** auto-detects which shape HAE is sending:
  - Aggregated `{totalSleep, deep, rem, core, awake, sleepStart, sleepEnd}` (hours) → sums into minute fields.
  - Unaggregated `[{startDate, endDate, value}]` → preserves timestamps as `segments[]` on the sleep row.
  - Per-sample heart rate (timestamped points) → routed to a sidecar `hr#hae_samples` row used for sleep-window HR stats.
- **Quality** (`shared/sleep_quality.py::evaluate_quality`) stamps every row with `quality_flag` ∈ {ok, partial, truncated, missing}, reasons list, and `confidence` 0–1. Ingest uses an optimistic check; compute re-checks with wrist-temp context and can downgrade.
- **Compute** derives `arousal_count`, `onset_min`, `continuity_idx` from `segments[]`, and `avg_hr_sleep`/`min_hr_sleep` by intersecting `hr#hae_samples` with `sleep_start`/`sleep_end`. Missing segments or HR samples just mean those fields stay absent — no failure mode.
- **Frontend** (RingDetail.tsx): hypnogram strip when segments exist, incomplete-night badge when `quality_flag !== 'ok'`, rows for wake-ups / onset / sleeping HR. Today.tsx dims the sleep ring to grey on truncated nights.
- **No manual entry**: user explicitly rejected a manual-input path. Richer signals auto-activate when HAE exports unaggregated sleep + per-sample HR.

## Telemetry + cost

- **App telemetry**: `src/api.ts::track()` batches UI events (tab.view, chat.open, ring.open, *.log.open, fab.tap, …) and POSTs to `/api/event`. Backend writes to `fitness-events` (date pk, event_id sk, 90-day TTL). Weekly Sunday 6am PT compute cron rolls up into `user_config` key `event_rollup`.
- **Infra cost**: `GET /api/infra-cost` hits AWS Cost Explorer (filtered to this stack's services in `us-west-2` via the `FITNESS_APP_SERVICES` allowlist in `shared/cost_service.py`), cached 6h in `user_config`. Surfaced on the Progress tab.
- **Budget alarm**: `AWS::Budgets::Budget` with $20/mo default, emails `AlertEmail` parameter at 80% actual + 100% forecast. Filtered to the same service list + region. Pass `--parameter-overrides AlertEmail=...` on deploy to enable.

## Known gaps / deferred

- 4 tests in `test_api_contract.py` hit live endpoints and will fail without network — deselect them for local runs.
- Sleep pipeline is Band 2: truncation detection + 5-component score + sleep-window HR. Band 3 (Whoop-style sleep-need wired into the score + bed/wake consistency) is deferred; `compute_sleep_need` is already defined in `scoring.py` and can be layered on without touching the data model.
