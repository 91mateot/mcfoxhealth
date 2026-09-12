# McFox Health — Architecture

Personal health/fitness dashboard for Mateo. Serverless AWS backend (Python 3.13
Lambdas behind an HTTP API, DynamoDB storage, SAM-managed) with scheduled ingest
from external providers. This document is the human-readable companion to
`architecture.json`; keep them in sync (shared-dev-conventions § Architecture Map
Maintenance).

> Scope note: this map was introduced alongside the Hevy set-level ingestion
> work and documents the backend (`backend/`) with emphasis on the ingest →
> compute → lift-learning data flow. It reflects the structure that has been
> directly verified in the code; extend it as other areas are touched.

## Runtime topology

```
External providers                 Lambdas (functions/)            DynamoDB (fitness-*)
──────────────────                 ────────────────────            ───────────────────
HealthAutoExport ──POST /ingest/health ─┐
Withings webhook ──POST /ingest/withings├─▶ IngestFunction ──▶ health-metrics, workouts,
Strava webhook   ──POST /ingest/strava  ┘   (handler.lambda_handler)  exercises, user-config,
Hevy API (poll)  ──Schedule hevy_poll  ──▶                            daily-scores
                                             │  invokes (async) ▼
                                             └────────────▶ ComputeFunction ──▶ daily-scores,
                                                            (baselines/scores)   baselines,
                                                                                 correlations
Browser / app  ──HTTP API /api/* ─────────▶ ApiFunction  (read models)
Browser / app  ──HTTP API /nutrition/* ───▶ NutritionFunction
Browser / app  ──HTTP API /coach/* ───────▶ CoachFunction (Bedrock ConverseStream + tool use)
```

Shared business logic lives in `backend/shared/shared/` and is packaged as a
Lambda layer (`SharedLayer`) imported by every function.

## Temporal semantics

Absolute timestamps are source truth; DynamoDB `date` fields are derived
analysis context. `backend/shared/shared/timezone.py` centralizes parsing,
source-date provenance, and calendar attribution. Aware timestamps use
trustworthy source-local offsets when the ingestion contract supplies them;
otherwise they are converted to the configured home timezone
(`America/Los_Angeles`). Naive timestamps never acquire a fabricated timezone.

For new Hevy ids, the workout and derived exercise rows use the Pacific
analysis date because Hevy exposes absolute UTC instants without event-local
timezone context. Rolled-up workout rows retain raw `start_time` / `end_time`
and additive source/analysis metadata. Existing Hevy ids retain their stored
partition-key date during updates/backfills; a differing `analysis_date` is
recorded additively so this release does not re-key history. Strava continues
to use `start_date_local`; HAE trusts explicit source offsets and preserves
date-only/naive values through an explicit source-date fallback; Withings epoch
values are converted from their absolute instant to the home timezone.

## Lift-learning engine (the core of the Hevy work)

A complete set-level lift-tracking engine already existed and reads exclusively
from the `fitness-exercises` table (PK=`canonical`, SK=`date`, one row per
exercise per day). Any writer into that table lights up e1RM, PR detection,
stall detection, weekly volume, the coach, the workout proposer, and the API —
for free.

Two writers now feed `fitness-exercises`:

1. **LLM lift-parser path** — `workout_service.annotate_workout` parses free-form
   notes (Bedrock) and calls `_write_exercise_rows`.
2. **Hevy poller path** — `ingest/handler._handle_hevy_sync` maps Hevy's
   structured `exercises[]`/`sets[]` into the same row shape via
   `hevy_client.workout_to_exercise_rows` + `_write_hevy_exercise_rows`.

Both canonicalize through the SAME vocabulary
(`shared.exercise_canonical.canonicalize`) so the same lift never splits across
two keys. After writing, both call `lift_compute.recompute_prs_for_canonicals`
and `recompute_weekly_volume`.

## Hevy ingestion data flow (added)

`IngestFunction` runs a daily `hevy_poll` schedule (and an explicit
`hevy_backfill` action). Per poll:

1. **Exercise-template cache** — `fetch_exercise_templates` (paginated, `pageSize`
   capped at Hevy's max of 10) → cached in `fitness-user-config` under key
   `hevy_exercise_templates` with a `fetched_at`; refreshed only when older than
   ~7 days (or forced on a backfill). Provides real `primary_muscle_group` per
   exercise.
2. **Workout fetch** — three modes: **incremental** via
   `GET /v1/workouts/events?since=<watermark>` (`fetch_workout_events`, applies
   updates AND deletions) when a `hevy_last_sync` watermark exists; **cold-start**
   bounded page-walk (`fetch_recent_workouts_full`) when no watermark; **backfill**
   (`action=hevy_backfill`, or a poll carrying `force_full`/`reset_watermark`)
   which IGNORES the watermark and does a full page-walk (default `pageSize` 10 ×
   `max_pages` 20 = up to 200 workouts, both event-overridable). Watermark
   persisted in `fitness-user-config` under key `hevy_last_sync`.
3. **Write (decoupled)** — per workout, `_apply_hevy_workout` writes a rolled-up
   session row to `fitness-workouts` (`workout_to_row`, preserving `description`,
   `routine_id`, `start_time`, `end_time`, `updated_at`, a per-set-type breakdown,
   `avg_rpe`/`max_rpe`, and an explicit `cal_unavailable` flag) AND per-exercise
   rows to `fitness-exercises` (`workout_to_exercise_rows` →
   `_write_hevy_exercise_rows`, `source="hevy"`). The two writes are
   **independent**: the rolled-up-row dupe-check (`_hevy_row_is_duplicate`) only
   suppresses the redundant `fitness-workouts` put — it NEVER gates the
   exercise-row write. A workout whose session row is unchanged but whose
   exercise rows are missing is **backfilled** (existence checked via
   `_hevy_exercise_rows_exist` on `(canonical, date)`); a fully-synced workout is
   a cheap skip. `backfill`/`force_full` rewrites both rows unconditionally. All
   writes are idempotent overwrites, so re-polling never duplicates rows or
   corrupts PR flags.
4. **Deletions** — a workout deleted in Hevy is removed from `fitness-workouts`
   and its `source="hevy"` rows removed from `fitness-exercises`.
5. **Recompute** — `recompute_prs_for_canonicals` + `recompute_weekly_volume`
   for touched canonicals (including backfilled ones); `_trigger_compute` for
   touched dates.
6. **Body measurements** — `GET /v1/body_measurements` (`fetch_body_measurements`,
   `pageSize` capped at Hevy's max of 10 — a larger value 400s, which was the
   root cause of the early `measurements_written: 0` runs) + `body_measurement_to_metrics`
   → `fitness-health-metrics` under a `#hevy` source suffix (e.g. `weight#hevy`,
   `waist#hevy`, `bodyfat_hevy#hevy`, `lean_mass#hevy`), converting cm→in and
   kg→lb, routed through the existing merge / ordering-guard helpers (never a
   bare `put_item` overwrite). The summary distinguishes `measurements_status`
   `ok` / `empty` (genuinely none logged) / `error` (fetch/parse failure) so a
   zero is never ambiguous.

The response summary reports: `mode`, `fetched`, `workouts_written`,
`backfilled`, `exercise_rows_written`, `deleted`, `measurements_written`,
`measurements_available`, `measurements_status`, `canonicals_touched`, `dates`.

Read-only integration: no POST/PUT to Hevy. Calories/HR are not available from
Hevy's public API — strain is estimated and calories are flagged unavailable
rather than reported as a misleading 0.

**Superset grouping field name (important):** `workout_to_exercise_rows` reads
the superset group id from `superset_id` (SINGULAR) — the key the LIVE Hevy API
actually returns on each exercise. Hevy's published OpenAPI spec documents it as
`supersets_id` (plural), but the live API disagrees with its own spec; reading
the plural key silently returned `None` for every exercise, so `superset_with`
was never populated. The mapper now prefers `superset_id` and falls back to
`supersets_id` (so it keeps working if Hevy ever conforms its API to the spec),
and tests grouping membership with `is not None` (group ids start at 0, so a
truthiness check would drop group 0). Do NOT "fix" this back to the plural
spelling to match the spec — the spec is wrong. Each grouped exercise row
carries both `superset_with` (a single partner canonical, kept for backward
compatibility with the lift engine / LLM-parser convention / frontend) and
`superset_group` (the sorted list of ALL other member canonicals, which
preserves 3+ member groups without loss).

## Modules — `backend/shared/shared/`

| Module | Responsibility |
|---|---|
| `exercise_canonical.py` | **(new)** Single source of truth for exercise-name → `canonical` slug (`canonicalize`, `_SYNONYMS`) and the app's 10-value `MUSCLE_GROUPS` vocabulary. Imported by both the LLM parser and the Hevy poller. |
| `hevy_client.py` | Hevy API client: workout → rolled-up row + exercise rows, muscle-group mapping (20 Hevy enum values → app vocabulary), template cache, events-based incremental sync, body-measurement mapping. HTTP isolated behind an injectable `http_get` seam. |
| `workout_service.py` | LLM lift-parser path (`annotate_workout`), `_write_exercise_rows`, coach debrief. Re-exports canonicalization from `exercise_canonical`. |
| `lift_compute.py` | Epley e1RM, PR detection, stall detection, `recompute_prs_for_canonicals`, `recompute_weekly_volume` over `fitness-exercises`. |
| `coach_context.py` | Assembles coach prompt context (reads `fitness-exercises`, scores, user-config). |
| `workout_proposer.py` | Proposes next workout from history + program config. |
| `scoring.py` | TRIMP / strain / HR-zone math + hot-swappable scoring weights. |
| `sleep_quality.py` | Sleep-quality evaluation. |
| `samples_ledger.py` | **(new)** Shard-aware per-day HAE samples ledger. Reads/writes the `<metric_source>_samples` sidecar across shards (`_samples`, `_samples#001`, ...) capped at 2000 samples/shard to stay under DynamoDB's 400KB item limit. Shared by ingest (write/merge) and compute (shard-reassembling reader). |
| `cost_service.py`, `db.py`, `timezone.py` | Cost tracking, DynamoDB helpers, and centralized source-timestamp/analysis-date semantics. |

## Functions — `backend/functions/`

| Function | Routes / triggers | Notes |
|---|---|---|
| `ingest/` | `POST /ingest/{health,withings,strava}`, `GET /ingest/strava`, `Schedule hevy_poll`, `action=hevy_backfill` | Writes health-metrics, workouts, exercises, user-config, daily-scores; invokes ComputeFunction. |
| `compute/` | daily + weekly schedules | Baselines, daily scores, correlations, lift roll-ups. |
| `api/` | `GET/POST /api/*` | Read models for the dashboard. |
| `nutrition/` | `/nutrition/*` | Meal logging, favorites, workout annotation route. |
| `coach/` | `/coach/*` | Bedrock ConverseStream tool-use coach (FastAPI app); model and reasoning effort are explicit environment settings. |

## DynamoDB tables (`fitness-*`)

| Table | Key schema | Purpose |
|---|---|---|
| `fitness-health-metrics` | date (PK), metric_source (SK) | Per-metric daily values; source-suffixed (`#hae`, `#hevy`, …). |
| `fitness-daily-scores` | date (PK) | Daily composite scores + weekly volume roll-ups (`week_<date>`). |
| `fitness-workouts` | date (PK), strava_id (SK) | Rolled-up sessions (Strava cardio + Hevy strength, `hevy_<id>`). New Hevy rows add source timestamp/offset plus analysis-date provenance; legacy keys remain unchanged until a separate migration. |
| `fitness-exercises` | canonical (PK), date (SK) | Per-exercise-per-day rows; the lift-learning engine's substrate. |
| `fitness-user-config` | key (PK) | Config + caches (scoring weights, favorites, `hevy_exercise_templates`, `hevy_last_sync`). |
| `fitness-nutrition` | date (PK), meal_id (SK) | Meals. |
| `fitness-journal` | date (PK) | Journal entries / tags. |
| `fitness-baselines` | type (PK) | Rolling baselines. |
| `fitness-correlations` | tag (PK), metric (SK) | Tag↔metric correlations. |
| `fitness-calibration` | date (PK) | Nutrition calibration. |
| `fitness-conversations` | user_id (PK), conversation_id (SK) | Coach conversations. |
| `fitness-feedback` | user_id (PK), target_key (SK) | Coach feedback. |
| `fitness-events` | (see template.yaml) | Event log. |

## Testing

Offline pytest suite in `backend/tests/`. External HTTP is injected via seams
(`http_get`) and DynamoDB is stubbed with fake tables, so no live keys/AWS are
needed. Run: `cd backend && .venv/bin/python -m pytest tests --deselect tests/test_api_contract.py`
(`test_api_contract.py` hits live endpoints; `test_coach_auth.py` needs an
optional `fastapi` dep — both are known-excluded from the offline run).
