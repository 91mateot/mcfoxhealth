# McFox Health Tracker

Personal health/fitness dashboard. Vite+TS PWA on Vercel, AWS Lambda backend, Whoop-calibrated scoring.

## Stack

- **Frontend**: Vite 5 + React 18 + TypeScript + SWR. No CSS framework. Deployed to Vercel (`mcfoxhealth.vercel.app`, auto-deploy on push to `main`).
- **Backend**: AWS SAM, Python 3.13 Lambdas, DynamoDB, EventBridge. Stack name `fitness-dashboard` in `us-west-2`.
- **Integrations**: Apple Health (via HealthAutoExport), Withings, Strava, Claude Bedrock.

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

- **ingest** — `POST /ingest/{health,withings,strava}`, HAE uses `x-api-key`
- **compute** — Daily cron 2am PT (baselines, scores), weekly cron Sun 6am PT (correlations)
- **api** — `GET /api/*` reads (today, progress, workouts, nutrition, insights, conversations)
- **nutrition** — `POST/PATCH/DELETE /api/{meal,water,journal,workout,favorites,calibration}` writes
- **coach** — Streaming chat via Function URL (RESPONSE_STREAM, not behind API Gateway)

## Auth

- Every `/api/*` request requires `x-api-key` header. Value lives in Secrets Manager (`fitness-api-key`) with env-var fallback (`INGEST_API_KEY`).
- Frontend reads `VITE_API_KEY` (set in Vercel env) and sends on every API call.
- Coach Function URL is currently **unauthenticated** (streaming + EventSource interaction — deferred).
- Ingest endpoints: HAE checks `x-api-key`; Withings/Strava webhooks rely on OAuth signature (can't send custom headers).

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
- **Recovery** = weighted composite of HRV/RHR/sleep/resp/SpO2/wrist_temp. Missing signals redistribute weight proportionally (Oura convention).
- **Strain** = 21 × (1 − e^(−TRIMP/300)), zone-weighted TRIMP (Edwards 1993).
- **Sleep** = duration + efficiency + deep + REM + wake-disruption composite.
- Weights live in `fitness-user-config` (hot-swappable). Each daily score row snapshots the `recovery_weights_used` + `strain_coefficient` that produced it, so retrospective scores stay reproducible after tuning.
- Baselines: rolling 14-day average, recomputed nightly.

## Known gaps / deferred

- Coach Function URL is open (no auth). Need to think about how header auth interacts with streaming before adding.
- Withings/Strava ingest webhooks — rely on the URL being obscure; should be replaced with OAuth signature verification.
- HealthKit sleep queries return truncated sessions; fallback (iOS Shortcut bridge) documented in scoring doc, not implemented.
- 4 tests in `test_api_contract.py` hit live endpoints and will fail without network — deselect them for local runs.
