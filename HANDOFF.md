# Mateo Fitness Dashboard — Handoff

Personal performance dashboard. iPhone-first PWA, dark theme, real data from
Apple Health + Withings + Strava + Hevy, AI coach on Bedrock.

> ⚙️ **Operating this system?** See [`RUNBOOK.md`](RUNBOOK.md) — deploy recipe, health checks, feed ownership (which breakages only Mateo can fix), and the traps that have already caused real bugs. This file covers *what* the system is; the runbook covers *how to run it without breaking it*.

## Live

- **Frontend:** https://mcfoxhealth.vercel.app (Vercel, auto-deploys from GitHub `main`)
- **GitHub:** https://github.com/91mateot/mcfoxhealth (private)
- **API:** https://5vvp43vamk.execute-api.us-west-2.amazonaws.com (AWS API Gateway, us-west-2)

## Stack

### Frontend (`src/`)
- Vite + React 18 + TypeScript strict
- SWR for data fetching (60s refresh on Today, on-demand for others)
- `vite-plugin-pwa` → service worker + offline + standalone iOS install
- No CSS framework; inline styles with palette tokens from `src/theme.ts`
- 3 palettes: Lime (default), Zine, Graphite

```
src/
  App.tsx                root, tab shell
  api.ts                 SWR hooks + POST helpers
  theme.ts               palette tokens (lime/zine/graphite)
  types.ts               TypeScript data models
  screens/               Today, Train, Fuel, Progress
  modals/                Chat, Journal, LogMeal, LogWorkout, RingDetail
  components/            Ring, Panel, Stat, Sheet, TabBar, etc.
```

### Backend (`backend/`)
- AWS SAM (`template.yaml`), Python 3.13 Lambdas
- 5 functions: `ingest`, `compute`, `api`, `nutrition`, `coach`
- 13 DynamoDB tables: health-metrics, daily-scores, workouts, nutrition,
  journal, baselines, correlations, user-config, calibration, exercises,
  conversations, events, feedback
- EventBridge schedules: compute daily 2am PT, correlations Sunday 6am PT
- Secrets in AWS Secrets Manager (strava-oauth, withings-oauth, fitness-api-key)

Scoring engine in `backend/shared/shared/scoring.py`:
- **Recovery:** 6-signal weighted composite (HRV 40% / RHR 25% / sleep 20% /
  resp 5% / spo2 5% / wrist temp 5%), weakest-link penalty on core signals
- **Strain:** Edwards TRIMP from zone-weighted HR samples, log curve to 0–21
- **Sleep:** Oura-style 35/25/20/20 (duration / efficiency / deep / REM)

Tested in `backend/tests/test_scoring.py` (Whoop-proxy calibration + sanity).

### Ingestion
- **Apple Health:** `POST /ingest/health` from HealthAutoExport (backfill script in `backend/scripts/hae_backfill.py`)
- **Withings:** `POST /ingest/withings` webhook + backfill script
- **Workouts (dual-source):**
  - **Hevy (strength/lifting):** daily scheduled poll on the `ingest` Lambda
    (EventBridge `HevyPoll`, ~1:30am PT) → pulls recent Hevy v1 workouts and
    upserts into the workouts table (`source="hevy"`, `type="Workout"`,
    `strava_id="hevy_<id>"`). Client: `backend/shared/shared/hevy_client.py`;
    handler: `_handle_hevy_sync` in `backend/functions/ingest/handler.py`.
    Reads the `hevy-api-key` secret (Secrets Manager, us-west-2); if the secret
    is missing it logs a clear message and no-ops (does not crash the cron).
    Also invokable directly with `{"action": "hevy_poll"}`.
  - **Strava (cardio/outdoor):** `POST /ingest/strava` webhook + OAuth refresh.
    Strength-type activities (WeightTraining/Workout/CrossFit) are dropped here
    so Hevy stays the single source of truth for lifting; cardio is kept.
  - **De-dupe:** Hevy is preferred for strength, Strava for cardio. Hevy
    re-polls are idempotent (keyed on the Hevy id); a session logged in both
    sources cannot double-count because Strava drops strength activities.

> **Note (2026-06):** Workout ingest was frozen 2026-05-08 when commit `7a8bf27`
> paused Strava on the assumption Hevy would replace it, but the Hevy path was
> never built — leaving `strain=0` with no workout feed. This dual-source setup
> (Hevy for strength + Strava for cardio) restores it.

### Companion tools
- `withings-mcp/` — separate public repo `partymola/withings-mcp`, registered MCP server for Claude Code queries against local Withings data

## Data contract (frontend ↔ backend)

| Endpoint                   | Method | Purpose                                   |
| :------------------------- | :----- | :---------------------------------------- |
| `/api/today`               | GET    | Today dashboard (recovery/strain/sleep…) |
| `/api/progress`            | GET    | Body comp + 30-day trends + lifts         |
| `/api/workouts`            | GET    | Recent sessions                           |
| `/api/nutrition/{date}`    | GET    | Per-day macros + meals                    |
| `/api/meal`                | POST   | Log a meal                                |
| `/api/water`               | POST   | Log water intake                          |
| `/api/journal`             | POST   | Morning check-in                          |
| `/api/coach`               | POST   | Chat (streaming, resumes last thread)     |
| `/api/conversation/latest` | GET    | Most recent coach thread (6h TTL)         |

The freshness control on Today revalidates `/api/today`, `/api/workouts`,
`/api/progress`, and the current day's nutrition in parallel. Before a manual
check, its label shows backend source age. After every refresh read and cache
update succeeds, it shows both check age and source age; checking does not
change `updatedAt`. Rejected refreshes show `refresh failed · retry`.
The next Coach
request receives the refreshed Today snapshot; its remaining context and tools
read the backend tables during that request.

## Deploy

- **Frontend:** `git push origin main` → Vercel auto-deploys in ~60s.
  Env var: `VITE_API_BASE` in Vercel production.
- **Backend:** `cd backend && sam build && sam deploy` (manual).
- **Scoring tweaks:** update `fitness-user-config` DynamoDB row with key `scoring`; weights hot-swap.

## Known gaps

1. **No auth on the API.** CORS is `*`, no API key enforcement on the read
   endpoints (`/api/today`, `/api/progress`, `/api/workouts`,
   `/api/nutrition/{date}`). Write endpoints (`/api/meal`, `/api/water`) check
   `x-api-key` via `_verify_api_key()` in `backend/functions/nutrition/handler.py`.
   Non-guessable URL is the only moat on reads.
2. **Prototype folder.** `prototype/` holds the original Babel Standalone
   export (Apr 2026). Archived — do not touch.

## Context

- **User:** Mateo (34, Pacific Beach SD, recomp goal, on retatrutide post-back-surgery).
- **Devices:** iPhone 17 Pro, Apple Watch S10, Withings scale.
- **Reta + back surgery** info is known to the coach (via Secrets Manager / user config) but **hidden from the UI** unless asked.
