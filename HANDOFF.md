# Mateo Fitness Dashboard — Handoff

Personal performance dashboard. iPhone-first PWA, dark theme, real data from
Apple Health + Withings + Strava, AI coach on Bedrock.

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
  screens/               Today, Train, Fuel, Body, Trends, Coach
  modals/                Chat, Journal, LogMeal, LogWorkout, RingDetail
  components/            Ring, Panel, Stat, Sheet, TabBar, etc.
```

### Backend (`backend/`)
- AWS SAM (`template.yaml`), Python 3.13 Lambdas
- 5 functions: `ingest`, `compute`, `api`, `nutrition`, `coach`
- 8 DynamoDB tables: health-metrics, daily-scores, workouts, nutrition,
  journal, baselines, correlations, user-config, calibration
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
- **Strava:** `POST /ingest/strava` webhook + OAuth refresh

### Companion tools
- `withings-mcp/` — separate public repo `partymola/withings-mcp`, registered MCP server for Claude Code queries against local Withings data

## Data contract (frontend ↔ backend)

| Endpoint                   | Method | Purpose                                   |
| :------------------------- | :----- | :---------------------------------------- |
| `/api/today`               | GET    | Today dashboard (recovery/strain/sleep…) |
| `/api/trends`              | GET    | 30-day metrics + learned correlations     |
| `/api/workouts`            | GET    | Recent sessions                           |
| `/api/body`                | GET    | Weight/BF/lean mass/steps                 |
| `/api/nutrition/{date}`    | GET    | Per-day macros + meals                    |
| `/api/meal`                | POST   | Log a meal                                |
| `/api/water`               | POST   | Log water intake                          |
| `/api/journal`             | POST   | Morning check-in                          |
| `/api/coach`               | POST   | Chat (streaming via `stream: true`)       |

## Deploy

- **Frontend:** `git push origin main` → Vercel auto-deploys in ~60s.
  Env var: `VITE_API_BASE` in Vercel production.
- **Backend:** `cd backend && sam build && sam deploy` (manual).
- **Scoring tweaks:** update `fitness-user-config` DynamoDB row with key `scoring`; weights hot-swap.

## Known gaps

1. **Chat is non-streaming.** `askCoachStream()` exists in `src/api.ts:100` but
   `src/modals/Chat.tsx:6` imports `askCoach` instead.
2. **LogWorkout doesn't persist.** `src/modals/LogWorkout.tsx` — `onAdd` is
   currently a no-op callback. Needs a POST endpoint or Strava auto-match.
3. **No auth on the API.** CORS is `*`, no API key enforcement. Non-guessable
   URL is the only moat.
4. **PWA icons missing.** `public/` only has `favicon.svg`. Need
   `icon-192.png`, `icon-512.png`, and `apple-touch-icon.png` for the
   home-screen icon to look right.
5. **Prototype folder.** `prototype/` holds the original Babel Standalone
   export (Apr 2026). Archived — do not touch.

## Context

- **User:** Mateo (34, Pacific Beach SD, recomp goal, on retatrutide post-back-surgery).
- **Devices:** iPhone 17 Pro, Apple Watch S10, Withings scale.
- **Reta + back surgery** info is known to the coach (via Secrets Manager / user config) but **hidden from the UI** unless asked.
