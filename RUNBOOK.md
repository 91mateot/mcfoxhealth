# McFox Health — Operations Runbook

> **Read this before touching the ingest pipeline.** It exists so that any agent (Hermes, Claude Code, Codex, Cursor) or any human — including Mateo six months from now — can operate this system without rediscovering the traps below. Every entry here was paid for with a real bug.
>
> **Audience:** primarily AI coding tools; secondarily Mateo on periodic review.
> **Scope:** the AWS backend + data pipeline. Frontend/product docs live in `HANDOFF.md`, architecture in `ARCHITECTURE.md` / `architecture.json`, stack conventions in `CLAUDE.md`.
> **Last verified against live AWS:** 2026-07-27. HAE/API Gateway and Manual
> Export evidence was refreshed 2026-08-30; all unrelated entries retain their
> stated verification dates.

---

## 0. Ten-second orientation

Personal health data warehouse. Five feeds land in DynamoDB → a scoring engine computes daily recovery/strain/sleep → a React PWA and a Bedrock coach read it.

| | |
|---|---|
| Stack | AWS SAM, `fitness-dashboard`, **us-west-2** |
| Runtime | Python **3.13** Lambdas (5) + 1 shared layer |
| Storage | **13** DynamoDB tables, all `fitness-*` |
| Frontend | Vite + React + TS on Vercel, auto-deploys from `main` |
| Repo | `91mateot/mcfoxhealth` (private) |
| API | `https://5vvp43vamk.execute-api.us-west-2.amazonaws.com` |

---

## 1. Feed ownership — who can fix what

Critical for triage: **some breakages no agent can fix.**

| Feed | Mechanism | Who fixes a break |
|---|---|---|
| **Apple Health (HAE)** | Health Auto Export app on Mateo's iPhone POSTs to `/ingest/health` | 🧍 **MATEO ONLY.** iOS-only app, HealthKit data lives on-device. No agent can restart it, re-auth it, or trigger an export. If HAE is silent, the *only* correct action is to tell Mateo. |
| **Withings** | Webhook → `/ingest/withings` + OAuth refresh | 🤖 Agent (token refresh) |
| **Strava** | Webhook → `/ingest/strava` + OAuth refresh | 🤖 Agent |
| **Hevy** | Daily EventBridge poll (`hevy_poll`, 08:30 UTC) pulls the Hevy v1 API | 🤖 Agent |
| **Nutrition (Bevel)** | ⚠️ **No automated feed exists.** Manual markdown export only. Frozen since 2026-05-09 (98 rows, Apr 25–May 9). | 🧍 Mateo (manual export) |

**Corollary:** "the health data looks wrong" is usually an HAE problem, and HAE problems are Mateo's to fix. Verify freshness (§5) before blaming code.

---

## 2. 🚨 Traps that have already bitten — read before writing code

### 2.1 Hevy's published OpenAPI spec has WRONG field names

**Do not trust `https://api.hevyapp.com/docs` for field names.** Verified 2026-07-27 against a live payload:

| Live API returns | Spec documents | Impact |
|---|---|---|
| `superset_id` (singular) | `supersets_id` (plural) | Superset groupings silently dropped for every workout |

The mapper now prefers `superset_id` and falls back to `supersets_id`. **Do not "correct" it back to match the spec.**

Verified live keys — diff against these, not the spec:
- **exercise:** `exercise_template_id`, `index`, `notes`, `sets`, `superset_id`, `title`
- **set:** `custom_metric`, `distance_meters`, `duration_seconds`, `index`, `reps`, `rpe`, `type`, `weight_kg`
- **workout:** `created_at`, `description`, `end_time`, `exercises`, `id`, `routine_id`, `start_time`, `title`, `updated_at`

**Why this got past 219 green tests:** the code AND the test fixtures both used the wrong key, so they agreed with each other. **Green tests prove nothing when fixtures mirror the code's assumption instead of a real payload.** Always dump one real API response and diff its keys before writing or reviewing a mapping.

To dump the live shape:
```bash
KEY=$(aws secretsmanager get-secret-value --secret-id hevy-api-key --region us-west-2 \
  --query SecretString --output text | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
curl -s -H "api-key: $KEY" "https://api.hevyapp.com/v1/workouts?page=1&pageSize=3" | python3 -m json.tool | head -60
```

### 2.2 Every Hevy list endpoint caps `pageSize` at 10

Sending more returns **HTTP 400**, which `_http_get` swallows into an empty result — indistinguishable from "no data." This was the root cause of `measurements_written: 0` looking like "Mateo logs no body measurements."

Clamped via `_clamp_page_size` / `HEVY_MAX_PAGE_SIZE = 10`. **When any Hevy fetch returns suspiciously empty, check pageSize before concluding the data doesn't exist.**

### 2.3 `superset_id` values start at 0

`if sid:` silently skips group 0 — which is most real groups. **Always `is not None`.**

### 2.4 Superset groups can have 3+ members

`superset_with` holds one partner canonical (kept for backward compat). `superset_group` holds the full sorted member list. Use `superset_group` for anything that must be lossless.

### 2.5 DynamoDB unfiltered `Scan` silently caps ~1000 items

And returns **key order, not date order** — so "the newest row is X" from a plain Scan is often a lie. This once produced a false "HAE died on May 23" conclusion.

Use `Select='COUNT'` or a `FilterExpression` on a date threshold. `date`, `value`, and `unit` are **reserved words** — alias them:
```python
params={'TableName':'fitness-exercises', 'Select':'COUNT',
        'FilterExpression':'#d >= :s',
        'ExpressionAttributeNames':{'#d':'date'},
        'ExpressionAttributeValues':{':s':{'S':'2026-06-01'}}}
```

### 2.6 Zeros that mean "unavailable", not "zero"

| Field | Why it's 0 |
|---|---|
| `cal` on Hevy rows | **Hevy's API has no calorie field at all.** The phone shows calories by reading Apple Health/Watch, then writes the workout back to HealthKit. So lifting calories DO reach McFox — via `active_cal#hae` in the daily total, just unattributed to the session. Flagged with `cal_unavailable: true`. |
| `volume_lb` / `working_volume` | Volume = Σ(reps × weight). Bodyweight, timed, and distance work (planks, ski erg, rowing, air bike) legitimately score 0 despite being real training. **Do not read 0 as "no work done."** |

`GET /api/today` preserves this distinction in its read contract. Missing
observations are `null`, while a stored zero remains `0`. `metricSemantics`
labels values as `observed`, `derived`, `configured_target`, or `fallback` and
reports availability as `available`, `unavailable`, or
`insufficient_history`. History arrays retain their calendar slots with
`null` gaps; consumers must not connect or render those gaps as measurements.
Fixed goals may remain numeric, but their semantics must identify them as
targets/fallbacks rather than observations.

### 2.7 `hevy_backfill` exceeds the Lambda timeout — and that's survivable

IngestFunction is **30s / 256 MB**. A full backfill (~32 workouts × per-exercise writes + PR/volume recompute) reliably hits `Sandbox.Timedout`.

**Writes are idempotent and land incrementally before the timeout**, so repeated invokes still reach full coverage. But the invoke errors, so **you cannot read the returned summary** — verify completeness by querying date coverage (§5.3), never by trusting the Lambda response.

### 2.8 A `date + type` collision is a CANDIDATE, not a duplicate

Two same-day same-type rows are not evidence of double-counting. Differing duration/strain is the *expected* signature of two genuinely different sessions. **Compare content fields** (`exercise_count`, `set_count`, `volume_lb`, `hevy_id`) before calling anything a duplicate.

Known-good example: 2026-05-09/11/13/20 each have a short `"Prep - Day N"` session *and* a full `"Day N"` session. **These are real, distinct sessions. Do not de-dupe them.** A same-day same-source de-dupe rule would also destroy legitimate two-a-days.

### 2.9 Double-count audit — settled, don't re-litigate

| Vector | Status |
|---|---|
| Hevy ↔ Apple Health | ✅ Clean — **no path exists.** HAE automations push Health *Metrics* only, never Workouts. Zero AH-sourced workout rows. |
| Hevy ↔ Strava | ✅ Clean — Strava webhook drops strength types (`STRAVA_STRENGTH_TYPES`); Hevy owns strength, Strava owns cardio. |
| Hevy ↔ Hevy | ✅ Clean — see §2.8. |

Only revisit if a new `#hae`-sourced workout row appears.

### 2.10 `date` is analysis context — never truncate an absolute UTC timestamp

New writes derive calendar attribution through `shared/timezone.py`; the raw
instant remains source truth. The configured home timezone is
`America/Los_Angeles`.

- **Hevy workouts:** `start_time` is an absolute instant, but Hevy provides no
  trustworthy event-local timezone. Convert it to the home timezone before
  assigning the `date` key. Preserve `source_start_time`, `source_end_time`,
  `source_date`, `source_utc_offset`, `analysis_date`, `analysis_timezone`, and
  `date_derivation`. Do not infer a travel-local timezone.
- **Existing Hevy ids:** an update or explicit backfill retains the already
  stored partition-key date, even when it differs from the new
  `analysis_date`. This prevents a forward-only release from silently re-keying
  history or creating a second row. Historical repair is a separate approved
  migration.
- **Strava:** `start_date_local` remains the source-local calendar authority;
  its raw value is retained. If it is absent, an absolute `start_date` falls
  back to the home timezone.
- **HAE:** explicit source offsets are treated as event-local context. Legacy
  date-only/naive values retain their validated source date without claiming a
  timezone. Stored rows mark these paths as `source_offset` or
  `source_date_fallback`; mixed-confidence aggregates retain both derivations
  rather than a misleading offset. Raw sample timestamps remain in the
  existing samples ledgers and sleep segments.
- **Withings:** epoch timestamps are absolute instants and derive their date in
  the home timezone; the source UTC instant and temporal metadata are retained.

Never use `timestamp[:10]` to assign an analysis date. A date-only source value
may be preserved through the explicit source-date fallback, but it is not proof
of event-local timezone.

### 2.11 Fresh `sam build` drifts untouched Coach dependencies

`backend/functions/coach/requirements.txt` uses open lower bounds
(`fastapi>=0.115`, `uvicorn[standard]>=0.30`). Verified 2026-08-08: the live
Coach artifact contains FastAPI 0.140.1 / Uvicorn 0.51.0 / Starlette 1.3.1 /
WebSockets 16.1.1, while a fresh build resolves 0.141.1 / 0.52.1 / 1.6.0 /
17.0.1 even though `app.py`, `run.sh`, `requirements.txt`, and `__init__.py` are
byte-for-byte unchanged.

**A normal full-stack deploy can therefore propose an unrelated
`CoachFunction` code update.** Always inspect the CloudFormation change set.
For a narrowly scoped release, preserve the currently deployed Coach artifact
or stop; dependency pinning/lockfiles require their own reviewed PR. Do not
silently ship the newly resolved package set with an unrelated change.

### 2.12 Hevy watermark means a completed check, not the latest write time

Hevy paginated reads carry explicit completeness metadata. HTTP errors,
timeouts, malformed pages, and `max_pages` truncation are failed Lambda
invocations; they must never be interpreted as a successful empty poll or
advance `hevy_last_sync`.

An empty first page is complete when Hevy reports either `page_count: 0` or
`page_count: 1`. The zero-page envelope is valid only for an empty page;
non-empty records with invalid page metadata still fail closed.

Hevy's current empty `/v1/workouts/events` response is also a verified
compatibility case: it may use `{page, page_count, workouts: []}` rather than
the normal `events` collection. McFox accepts that alternate collection only
when it is empty on page 1 with its verified `page_count: 1`. A nonempty `workouts`
collection on the events endpoint remains malformed and leaves the watermark
unchanged, because it could have different update/deletion semantics.

The handler captures `sync_started_at` before the first vendor request and
stores that pre-fetch boundary only after workout events, writes, deletions,
derived recomputation, and body-measurement ingestion complete. Incremental
polls query from `hevy_last_sync - 48 hours`. This bounded replay covers events
near the boundary; Hevy-id-keyed workout/exercise overwrites and repeated
deletion events are idempotent.

If a later workout in a multi-workout poll hits an unsafe legacy-date lookup,
the handler stops additional workout writes, recomputes PR/e1RM, weekly volume,
and daily scores for earlier writes, leaves the watermark unchanged, then
raises so the scheduled invocation is observably failed.

A completely retrieved response can also contain one unusable workout. Valid
workouts are applied and recomputed, but the invocation raises with the bad
Hevy id/type/reason and leaves the watermark unchanged. After inspecting that
specific vendor record, an operator can acknowledge only the currently
reported bad id:

```python
{"action":"hevy_poll", "skip_invalid_workout_ids":["<reviewed-hevy-id>"]}
{"action":"hevy_backfill", "skip_invalid_workout_ids":["<reviewed-hevy-id>"]}
```

The override fails closed if an id is not present in that invocation's
record-issue list, so it cannot skip an arbitrary healthy workout. Acknowledged
ids and reasons are logged and returned as `reviewed_skips`. Unknown future
event types are logged/returned as `ignored_events`; they are not guessed to be
updates or deletions and do not block known events.

Deletion caveat: the events feed is the authoritative deletion path, and its
48-hour replay makes ordinary retries safe. A full `/workouts` backfill cannot
necessarily reconstruct a deletion after Hevy has removed the vendor record.
Do not reset or discard the event watermark as a deletion-reconciliation
strategy; broader historical reconciliation requires a separately reviewed
change.

### 2.13 OAuth refresh tokens must never come from a warm cache

Withings and Strava both rotate refresh tokens. OAuth secret reads therefore
bypass the ingest Lambda's process-local secret cache and go directly to
Secrets Manager. Do not route `withings-oauth` or `strava-oauth` back through
the generic warm cache.

`shared/oauth_service.py` serializes a provider refresh with a 45-second
conditional lease in `fitness-user-config`. After acquiring the lease it reads
the secret again before calling the provider, persists the complete rotated
secret while preserving unknown fields, and then releases the lease. If the
lease cannot be established, refresh fails closed rather than risking two
rotations from the same token.

- Strava refreshes when 3,600 seconds or less remain.
- Withings refreshes when 600 seconds or less remain.
- Webhooks keep just-in-time refresh and retry once after provider auth failure.
- The daily `oauth_credential_check` action refreshes only when due and fails
  the invocation observably if either vendor check fails.
- `oauth_status#withings` and `oauth_status#strava` contain timestamps, expiry,
  state, and sanitized failure codes only. Never write access tokens, refresh
  tokens, client secrets, or raw provider error bodies into status rows/logs.

The daily check is not a substitute for webhook processing or historical data
reconciliation. Do not add a high-frequency unconditional refresh schedule;
that increases token-rotation races without improving data completeness.

### 2.14 HAE HTTP 413 is an API Gateway loss, not a Lambda error

`POST /ingest/health` is behind the stack's API Gateway **HTTP API**, whose
request payload ceiling is a hard 10 MB. An oversized Health Auto Export (HAE)
request is rejected at API Gateway with `413 Request Entity Too Large` before
the Ingest Lambda is invoked. Therefore, clean Lambda logs (including no
`HAE_SUMMARY`) do **not** prove HAE is healthy.

Use the API access-log group `/aws/apigateway/fitness-dashboard` whenever HAE
looks incomplete. The incident PR adds `dataProcessed` (API Gateway's
byte-count context field) alongside `routeKey`, `status`, `integrationStatus`,
`error`, `userAgent`, and response length. It is only present in the live logs
after this PR is deployed:

```text
fields @timestamp, status, userAgent, integrationStatus, error
| filter routeKey = "POST /ingest/health" and status = "413"
| sort @timestamp desc
```

The current access logs do not record request `Content-Length`; `responseLength`
is the small API response body, not the rejected request size. After deployment,
`dataProcessed` is a byte-volume diagnostic, not the raw request body. The logs
also do not capture HAE's `automation-name` / `automation-id` request headers,
so group rejections by client user-agent and timing only; do not attribute a 413
to a named automation without separate phone-side evidence. Do not try to raise
the API Gateway limit or infer a rejected body from Lambda logs.

HAE configuration is Mateo-only. The supported transport mitigation is to
enable HAE **Batch Requests** and use a bounded/incremental date range for the
Health Metrics automation, then prove a clean live run before any backfill.
Keep Workouts/GPX as a separately verified automation; do not assume it shares
the Health Metrics route.

**F2 closure (2026-08-25):** the natural post-PR16 413 at approximately
14:59 PDT recorded `dataProcessed=89`. That is not useful rejected-request byte
volume, so do not infer a payload size from it or add infrastructure based on
that field. Continue using status, client user-agent, timing, and successful
neighboring requests for passive 413 diagnosis.

### 2.15 HAE PRISM source-evidence contract — two Health Metrics streams

The production contract intentionally separates **completed-day activity
totals** from **raw physiological/mobility observations**. It does **not**
create a minute-summary activity stream, ingest HAE Workouts, or establish a
general provenance framework.

#### A. PRISM Activity Daily — canonical completed-day totals

Configure one HAE REST automation with:

| Setting | Required value |
|---|---|
| Format | JSON, Export Version v2 |
| Summarize Data | **On** |
| Time Grouping | **Days** |
| Date Range | **Yesterday** |
| Batch Requests | **On** |
| Timing | One daily run after the prior day is complete |

Enable exactly these approved activity metrics:

| HAE raw metric | Canonical daily source row | Unit |
|---|---|---|
| `active_energy` | `active_cal#hae_daily_summary` | kcal |
| `apple_exercise_time` | `exercise_min#hae_daily_summary` | min |
| `step_count` | `steps#hae_daily_summary` | count |
| `walking_running_distance` | `walk_distance#hae_daily_summary` | mi |
| `apple_stand_time` | `stand_min#hae_daily_summary` | min |
| `apple_stand_hour` | `stand_hours#hae_daily_summary` | count |
| `flights_climbed` | `flights#hae_daily_summary` | count |

Each accepted summary metric must carry exactly one HAE v2 daily row. The
stored value is HAE's completed-day total; McFox must **not** reconstruct it by
summing minute or raw rows.

These rows have a separate `#hae_daily_summary` identity, never a samples
ledger. A repeat of an identical delivery overwrites the same date/metric
idempotently. A corrected delivery overwrites/supersedes the prior daily value;
it is never added to the old total. The date/metric row preserves the source
timestamp, analysis-date temporal metadata, raw metric name/units, HAE source
string, and safe automation metadata.

**Replay/correction guard.** For each `(analysis_date, automation-id)`, McFox
stores a same-table control row with the current HAE `session-id`, a bounded
history of the 16 newest superseded session IDs, and an optimistic guard
version. This is not a health-metric observation. It has these outcomes before
any canonical daily metric row is written:

- The current session is safe to replay and can repair a partial prior write.
- A known superseded session returns HTTP 200 with
  `stale_daily_summary_replay_ignored`; it changes no metric row, source
  metadata, `ingested_at`, or downstream computation.
- A previously unseen session becomes current and moves the prior current
  session into the bounded history. Its source-provided daily totals replace,
  rather than add to, the prior values.

Guard updates use conditional writes, and summary rows carry the accepted guard
version as a fence so an in-flight older request cannot overwrite a later
accepted correction. If a conditional guard update cannot be resolved after
the bounded retry loop, McFox returns an observable retryable conflict before
canonical writes.

The documented REST headers give an identity (`session-id`) but no monotonic
source-generation or correction-revision value. McFox therefore does **not**
sort session UUIDs, use request arrival time as source order, or infer order
from a daily row's midnight timestamp. It can reject a replay of a session
already known to be superseded, but cannot determine the source order of two
previously unseen session IDs; their safely serialized accepted arrival order
remains authoritative. Classified Activity Daily requests unexpectedly missing
`session-id` or `automation-id` fail closed with HTTP 422 before writes.

#### B. PRISM Vitals & Mobility — raw/disaggregated evidence

Configure a separate HAE REST automation with:

| Setting | Required value |
|---|---|
| Format | JSON, Export Version v2 |
| Summarize Data | **Off** |
| Time Grouping | **Default** (no aggregation / raw data points) |
| Date Range | **Since Last Sync** |
| Batch Requests | **On** |

Enable these metrics:

`heart_rate_variability`, `resting_heart_rate`, `blood_oxygen_saturation`,
`respiratory_rate`, `apple_sleeping_wrist_temperature`, `body_temperature`,
`vo2_max`, `cardio_recovery`, `walking_heart_rate_average`,
`walking_asymmetry_percentage`, `walking_speed`, `walking_step_length`,
`walking_double_support_percentage`, `stair_speed_up`, `stair_speed_down`,
`six_minute_walking_test_distance`, and `physical_effort`.

Raw values remain source observations:

- `walking_speed`, `walking_step_length`, double-support percentage, stair
  speeds, and `physical_effort` are observation series and use their daily mean
  only as the current compact representation; they are **not** summed.
- `cardio_recovery` and six-minute walking distance retain the latest
  observation for the date.
- Raw distance/energy/duration/count values use the established sample-ledger
  aggregation path, but must never merge with Activity Daily summary rows.
- `walking_asymmetry_percentage` is empirically confirmed to be **percentage
  points**, not a 0–1 fraction (F1 closed).
- Existing dedicated Heart Rate and Sleep HAE paths remain separate. Withings
  remains the primary direct weight/body-composition source. HAE Workouts and
  GPX routes are out of scope here.

#### Routing headers, compatibility, and diagnostics

HAE REST automations automatically attach lower-case request headers:
`automation-name`, `automation-id`, `automation-aggregation`,
`automation-period`, and `session-id`. The ingest handler normalizes header
case, preserves those five values only as bounded `hae_*` source-specific
metadata, and never records authentication headers or request bodies.

- Recognized `Days` + `Yesterday` routing is `completed_daily_summary`.
- Recognized no-grouping/raw routing is `raw_observation`.
- Requests with neither aggregation nor period retain compatibility as
  `legacy_unclassified` and follow the pre-contract raw path.
- Partial or unrecognized aggregation/period metadata returns HTTP 422 rather
  than silently treating a new summary form as raw evidence.

#### Controlled Activity Manual Export probe — 2026-08-29 PDT

A read-only production correlation proved how the automation-level Manual
Export picker behaves without changing the saved **PRISM Activity Daily**
configuration. The saved range remained **Yesterday**. In the Manual Export
picker only, `2026-08-25` through `2026-08-26` was selected once.

HAE sent two date-sharded `POST /ingest/health` requests:

| API request time (UTC) | Source/analysis date | Headers and classification | Result |
|---|---|---|---|
| `2026-08-30 01:54:00` | `2026-08-25` | 7 metrics; `Days`; `Yesterday`; `completed_daily_summary` | HTTP/integration 200; single-date response; 7 items |
| `2026-08-30 01:54:02` | `2026-08-26` | 7 metrics; `Days`; `Yesterday`; `completed_daily_summary` | HTTP/integration 200; single-date response; 7 items |

Both requests carried the same sanitized automation fingerprint
`30a0e4676c5acb51` and distinct present session fingerprints
`a1099324cc5322da` / `b576fa07a491a686`. Each request contained exactly one
point for each approved metric on its selected source-local date. The
corresponding per-date guards and seven canonical summary rows were updated,
and two Compute invocations followed. The `2026-08-28` guard, rows, and score
were not changed in the probe window.

Therefore, the Activity repair must leave the saved range at **Yesterday**,
must not save/update the automation, and must use only the automation-level
Manual Export picker. The HAE Activity Log's visible
`Yesterday · 2026-08-28` label was not the transmitted source-date evidence.
Receiving-side `Days` + `Yesterday` headers and
`completed_daily_summary` classification are mandatory stop-gate evidence.
Do not widen the accepted daily period tokens for this workflow.

CloudWatch emits bounded `HAE_STREAM_CLASSIFIED` and
`HAE_UNMAPPED_METRIC` records with metric name/count and non-secret automation
identity. It never logs health values, payload bodies, API keys, or
authorization headers.

#### Canonical daily resolution and consumer behavior

For each approved Activity Daily metric, resolve exactly once per date:

1. `hae_daily_summary` — preferred when a completed-day row exists.
2. `legacy_hae_aggregate` — current historic raw HAE aggregate when no summary
   exists.
3. `unavailable` — no source value; preserve missingness.

Stored `0` remains a genuine observation, not missing. Current compute/API
consumers use this resolver for steps and active calories without changing any
scoring formulas; the daily score records the chosen source. Baseline
calculation also resolves steps once, so raw + summary cannot double count.
Historical rows are neither re-keyed nor migrated by this contract.

#### Phone-side final configuration and live validation

Mateo-only changes (do not alter these from AWS or an agent):

1. Edit/create **PRISM Activity Daily** exactly as section A; keep Workouts and
   GPX out of this Health Metrics automation.
2. Edit/create **PRISM Vitals & Mobility** exactly as section B. To set its
   raw grouping, temporarily enable **Summarize Data** only if HAE requires it
   to expose **Time Grouping**, select **Default**, turn **Summarize Data**
   back **Off**, then Save/Update the automation. **Default = no aggregation /
   raw data points.** Confirm the first production request is classified as
   `raw_observation`.
3. Leave dedicated Heart Rate and Sleep automations unchanged. Do not create a
   production minute-summary activity stream.
4. After deploy, run one normal Activity Daily export after a day completes,
   then one Vitals & Mobility export. Verify API Gateway access logs show 200
   (not 413), Ingest logs show the expected stream classification, accepted
   rows preserve the expected metadata, all seven daily metrics are present,
   raw metric families/sample counts are plausible, and a repeat is
   idempotent.
5. Confirm the daily score/API reports `hae_daily_summary` for completed-day
   steps and active calories, and does not combine the legacy raw total.

Do **not** backfill in this validation. Targeted Health Metrics replay remains
a separate approval after routine exports are proven healthy; use Health
Metrics only, no Workouts, and split manual exports into bounded batches if the
phone's request-size behavior requires it.

#### Multi-date Activity Daily contract and repair failure semantics

Before multi-date support, `_handle_hae_daily_summary` required every approved
metric array to contain exactly one point. A legitimate historical JSON v2
export contains one point per source-local day, so each multi-date metric was
dropped and the handler returned HTTP 200 with `items_written: 0`, `date:
null`, no session guards, no canonical rows, and no recomputation.

The supported `completed_daily_summary` contract now validates the full request
before any guard or canonical metric write:

- only the seven approved Activity Daily metric names are accepted;
- a missing, null, empty, or whitespace-only unit is treated as omitted;
  a nonempty unit must match the documented canonical unit;
- every observation must be an object with a parseable source timestamp and a
  finite numeric `qty` or `value`;
- each normalized `(analysis_date, canonical metric)` pair may appear at most
  once;
- an approved metric may be absent for a date; missing stays missing and is
  never replaced with zero;
- a stored numeric zero is retained as a genuine observation.

Adding an unsupported metric to **PRISM Activity Daily**, or receiving a
contradictory nonempty unit label, intentionally rejects the whole daily
request with HTTP 422 before any session guard or canonical metric write. This
fail-closed behavior prevents a partially accepted request from corrupting the
daily semantic contract.

After validation, source-local analysis dates are processed in ascending order.
Each date independently acquires the existing `(analysis_date, automation-id)`
session guard before that date's canonical metrics are written. Current-session
replays can repair missing rows, known superseded sessions are successful
no-ops for only their affected dates, and unseen sessions replace rather than
add. Metric rows retain the accepted guard version as their conditional-write
fence. No Activity Daily value enters a raw aggregate or samples ledger.

Each fully written/corrected date triggers one `compute_day` invocation. If a
guard, conditional write, infrastructure write, or recompute trigger fails,
processing stops at that date and returns non-2xx with only bounded metadata:
completed/stale counts, items written, affected range, failed date, and reason
code. Earlier dates remain committed. Replaying the request is safe: a
same-session replay repairs the failed/partial date, while already written rows
are overwritten idempotently rather than added or duplicated.

Single-date success and known-stale response bodies remain compatible with the
deployed Activity Daily contract. Multi-date success adds bounded counts and
the affected date range; it never returns health values or an unbounded date
list.

#### Activity Daily historical-repair manifest — not executed

Repair exactly one interval:

| Chunk | Inclusive source-local range | Source-date count | Expected canonical rows |
|---|---|---:|---:|
| A1 | `2026-07-12` → `2026-08-24` | 44 | 7 per date / 308 total |

Use one automation-level Manual Export operation selecting all 44 days. The
controlled two-day probe produced one date-sharded request per selected source
date, so the operational expectation is 44 one-date requests while still
requiring only one phone operation. The receiver also safely supports a
multi-date request if HAE batches differently. The measured one-day artifact
was approximately 1.9 KB, so the linear estimate is approximately 84 KB before
small envelope overhead—comfortably below the API Gateway 10 MB request
ceiling. Per-date guards and bounded failure responses retain date-level
resumability in either transport shape.

Required HAE settings:

- existing automation: **PRISM Activity Daily**;
- leave its saved **Date Range Yesterday** unchanged;
- do not save or update the automation configuration;
- use only the automation-level **Manual Export** date picker and select the
  inclusive range `2026-07-12` through `2026-08-24`;
- format: **JSON**, Export Version **v2**;
- **Summarize Data On**;
- **Time Grouping Days**;
- **Batch Requests On**;
- exactly `active_energy`, `apple_exercise_time`, `step_count`,
  `walking_running_distance`, `apple_stand_time`, `apple_stand_hour`, and
  `flights_climbed`;
- Health Metrics only: no Workouts and no GPX.

Expected server behavior:

- every request retains `automation-aggregation: Days` and
  `automation-period: Yesterday` and classifies as
  `completed_daily_summary`; stop immediately if any classification differs;
- expected probe-grounded transport is 44 one-date requests, each preserving
  the compatible single-date response with its date and 7 items written;
  another batching shape is acceptable only when receiving-side evidence
  covers exactly the 44 selected dates with no date outside the interval;
- each date has one automation-scoped guard and up to seven canonical
  `#hae_daily_summary` rows; the expected complete result is seven rows/date;
- absent source metrics remain absent and require review; they are never
  synthesized as zero;
- genuine zero values remain zero;
- a first unseen repair session normally creates guard version 1; a
  current-session replay repairs/overwrites safely; a known superseded session
  is ignored; a later unseen correction session advances the guard and replaces
  the prior values;
- `compute_day` is triggered once for each successfully completed date;
- no `#hae` raw aggregate and no `_samples` row is created by this request.

Validate chunk A1 before considering the repair complete:

1. API Gateway access logs show the expected 44 HTTP 200 date-sharded requests,
   never 413/422/5xx. If HAE uses another batching shape, correlate every
   request and prove exact receiving-side coverage of all 44 dates.
2. Ingest logs show `Days`, `Yesterday`, and `completed_daily_summary` for
   every request. Across all bounded result records, require 44 completed
   dates, zero failed dates, zero unexpected stale dates, and no
   structural-rejection or guard-conflict record.
3. For every date, query `fitness-health-metrics` by partition key and verify
   exactly the seven expected summary identities plus one automation-scoped
   guard, matching positive guard versions, no duplicate identities, and no
   Activity `_samples` identity.
4. Query `fitness-daily-scores` for every date and verify `computed_at` moved
   after the repair request and `activity_sources.steps` /
   `activity_sources.active_cal` resolve to `hae_daily_summary`.
5. Requery the explicitly excluded boundary date `2026-08-25` and confirm the
   repair did not alter it.

Stop immediately on 413, 422, any 5xx, `partial_failure`, an unexpected metric
or unit, duplicate metric/date rejection, a guard/write conflict that does not
clear on retry, any write outside the inclusive range, or any raw/sample-ledger
Activity row. Do not advance or declare success from a partial response.

Resume rule: retain the response's `failed_date` and completed/stale counts,
then retry the same A1 interval after the server fault is understood. A
same-session transport retry repairs the failed/partial date; a new-session
manual rerun replaces existing daily rows rather than adding. Revalidate the
entire 44-date interval after a successful retry. If an actual 413 occurs,
stop and prepare a separately reviewed smaller-chunk manifest rather than
silently changing the approved operation.

If HAE receives HTTP 504 or otherwise has no bounded multi-date response body,
do not blindly repeat the repair. First inspect `HAE_DAILY_SUMMARY_RESULT`
logs, then inspect each date's session guard and canonical summary identities
to reconstruct the last completed or failed date. Only after that state is
known should an operator repeat the same full Manual Export request or resume
the operation. A verified full retry is safe because same-session guards and
metric-row write fences repair or idempotently replace prior work. Do not
change API Gateway or Lambda timeout settings for this recovery path.

Explicit exclusions: `2026-08-25` and every later date; every date before
`2026-07-12`; Sleep; raw Heart Rate; Workouts; GPX.

#### Vitals & Mobility historical-repair manifest — not executed

Keep the validated raw-observation contract:

- existing automation: **PRISM Vitals & Mobility**;
- format: **JSON**, Export Version **v2**;
- **Summarize Data Off**;
- **Time Grouping Default**;
- **Batch Requests On**;
- no Workouts and no GPX;
- exactly these 17 metrics:
  `heart_rate_variability`, `resting_heart_rate`,
  `blood_oxygen_saturation`, `respiratory_rate`,
  `apple_sleeping_wrist_temperature`, `body_temperature`, `vo2_max`,
  `cardio_recovery`, `walking_heart_rate_average`,
  `walking_asymmetry_percentage`, `walking_speed`,
  `walking_step_length`, `walking_double_support_percentage`,
  `stair_speed_up`, `stair_speed_down`,
  `six_minute_walking_test_distance`, and `physical_effort`.

Use these seven approved chunks:

| Chunk | Inclusive source-local range | Expected source dates |
|---|---|---:|
| V1 | `2026-07-12` → `2026-07-18` | 7 |
| V2 | `2026-07-19` → `2026-07-25` | 7 |
| V3 | `2026-07-26` → `2026-08-01` | 7 |
| V4 | `2026-08-02` → `2026-08-08` | 7 |
| V5 | `2026-08-09` → `2026-08-15` | 7 |
| V6 | `2026-08-16` → `2026-08-22` | 7 |
| V7 | `2026-08-23` → `2026-08-24` | 2 |

For each chunk, Batch Requests may produce one or more date-sharded requests
per source date. Every shard must return HTTP 200 and classify as
`raw_observation`; request count may exceed the source-date count. Replaying a
chunk is idempotent because raw ledgers merge by timestamp across every shard.
The aggregate is recomputed from the merged unique timestamp set rather than
adding a replayed batch.

Validate each chunk before starting the next:

1. API Gateway has only 200 responses for all date-sharded requests; Ingest
   logs show `raw_observation`, never `completed_daily_summary`.
2. The expected 7 source dates (2 for V7) are represented in the transport
   evidence. A metric or even a date can be sparse because HealthKit supplied
   no samples; sparse source absence alone is not an ingestion failure.
3. Query each represented date and verify only approved Vitals raw identities
   are attributed to this automation; Activity Daily identities remain
   separate.
4. Merge every `_samples`, `_samples#001`, `_samples#002`, … chain by base
   metric and verify sample timestamp count equals unique timestamp count.
5. Verify shard suffixes are contiguous from shard 0, every shard contains at
   most 2,000 samples, and no `ValidationException` / item-size error appears.
6. Replay validation, when needed, must leave unique timestamp counts and
   aggregate row counts unchanged.

Stop on any 413, 422, 5xx, unexpected classification, unapproved metric,
duplicate timestamp after merge, non-contiguous shard chain, shard over 2,000
samples, item-size/`ValidationException`, or a row outside the chunk. Do not
call sparse source absence a transport or ingestion failure by itself.

Resume rule: stop before the next chunk, correct the observed fault, and rerun
only the failed chunk. Date-sharded/raw timestamp deduplication makes replaying
the whole failed chunk safe. After a successful retry, repeat all checks for
that chunk before advancing.

Explicit exclusions: `2026-08-25` and every later date; every date before
`2026-07-12`; dedicated Sleep and raw Heart Rate streams; Workouts; GPX.

#### Separately authorized post-deploy Computer Use sequence

Do not perform these steps during code review or deployment. After the deployed
Ingest artifact and routine one-day traffic are verified, use iPhone Mirroring
only under separate repair authorization:

1. Open Health Auto Export → Automations. If a credential-bearing REST screen
   appears unexpectedly, stop without reading, copying, or changing it.
2. Open the existing **PRISM Activity Daily** automation. Record only its
   non-secret settings. Confirm the seven metrics, JSON v2, Summarize On, Days,
   Batch Requests On, saved Date Range **Yesterday**, and no Workouts/GPX. Do
   not save or update the automation.
3. From that automation, open **Manual Export**. In its picker only, select
   start `2026-07-12` and end `2026-08-24`, then run once. Do not change any
   saved automation setting or endpoint/authentication field.
4. Observe the HAE result. On any non-200 or uncertain result, stop. On 200,
   leave the saved **Yesterday** range untouched and complete AWS validation
   for A1. Stop immediately if receiving-side aggregation, period, or
   classification differs from `Days`, `Yesterday`,
   `completed_daily_summary`.
5. Open the existing **PRISM Vitals & Mobility** automation. Confirm the exact
   17 metrics, JSON v2, Summarize Off, Default, Batch Requests On, Since Last
   Sync as the normal range, and no Workouts/GPX.
6. For V1 through V7 in order, change only the date range to that chunk, run
   once, and wait for AWS validation before advancing. On any stop condition,
   restore `Since Last Sync`, save/update, and do not start the next chunk.
7. After V7 validates, restore `Since Last Sync`, save/update, and confirm both
   production automations retain their normal enabled cadence and settings.
8. Do not open, edit, or run the dedicated Sleep, raw Heart Rate, or Workouts
   automations.

#### AWS-side repair validation without Hermes

Use a locally authenticated AWS CLI; do not fetch secrets or payload bodies.
First resolve the live function/log target and inspect the repair time window:

```bash
REGION=us-west-2
STACK=fitness-dashboard
REPAIR_START_EPOCH_MS='REPLACE_WITH_START_EPOCH_MS'
REPAIR_END_EPOCH_MS='REPLACE_WITH_END_EPOCH_MS'
INGEST_FN="$(aws cloudformation describe-stack-resource \
  --stack-name "$STACK" --logical-resource-id IngestFunction \
  --region "$REGION" --query 'StackResourceDetail.PhysicalResourceId' \
  --output text)"
INGEST_LOG_GROUP="$(aws lambda get-function-configuration \
  --function-name "$INGEST_FN" --region "$REGION" \
  --query 'LoggingConfig.LogGroup' --output text)"

aws logs filter-log-events \
  --log-group-name /aws/apigateway/fitness-dashboard \
  --region "$REGION" --start-time "$REPAIR_START_EPOCH_MS" \
  --end-time "$REPAIR_END_EPOCH_MS" \
  --filter-pattern '{ $.path = "/ingest/health" }'

aws logs filter-log-events \
  --log-group-name "$INGEST_LOG_GROUP" \
  --region "$REGION" --start-time "$REPAIR_START_EPOCH_MS" \
  --end-time "$REPAIR_END_EPOCH_MS" \
  --filter-pattern '"HAE_STREAM_CLASSIFIED"'

aws logs filter-log-events \
  --log-group-name "$INGEST_LOG_GROUP" \
  --region "$REGION" --start-time "$REPAIR_START_EPOCH_MS" \
  --end-time "$REPAIR_END_EPOCH_MS" \
  --filter-pattern '"HAE_DAILY_SUMMARY_RESULT"'
```

For Activity A1, require every classification record to contain metric count
7, aggregation `Days`, period `Yesterday`, and semantics
`completed_daily_summary`. Correlate the result records to exactly
`2026-07-12` through `2026-08-24`; stop on an omitted or out-of-range date, a
different classification, or an unbounded/missing response until guard and
canonical-row state are reconstructed.

Activity metadata-only validation for every repair date:

```bash
python3 -c 'from datetime import date,timedelta; s=date(2026,7,12); [print((s+timedelta(days=i)).isoformat()) for i in range(44)]' |
while read -r day; do
  aws dynamodb query \
    --table-name fitness-health-metrics \
    --region us-west-2 \
    --key-condition-expression '#d = :d' \
    --expression-attribute-names '{"#d":"date"}' \
    --expression-attribute-values "{\":d\":{\"S\":\"$day\"}}" \
    --projection-expression 'metric_source,hae_semantics,hae_session_guard_version' \
    --output json |
  jq -e --arg day "$day" '
    ([.Items[]
      | select(.hae_semantics.S? == "completed_daily_summary")
     ]) as $summaries |
    ([.Items[]
      | select(.hae_semantics.S? ==
          "completed_daily_summary_session_guard")
     ]) as $guards |
    ($guards[0].hae_session_guard_version.N | tonumber) as $guard_version |
    ([$summaries[] | .metric_source.S] | sort) ==
    (["active_cal#hae_daily_summary",
      "exercise_min#hae_daily_summary",
      "flights#hae_daily_summary",
      "stand_hours#hae_daily_summary",
      "stand_min#hae_daily_summary",
      "steps#hae_daily_summary",
      "walk_distance#hae_daily_summary"] | sort)
    and
    ($guards | length == 1)
    and
    ($guard_version > 0)
    and
    ($summaries
      | all((.hae_session_guard_version.N | tonumber) == $guard_version))
  ' >/dev/null || { echo "activity validation failed: $day"; exit 1; }

  aws dynamodb get-item \
    --table-name fitness-daily-scores \
    --region us-west-2 \
    --key "{\"date\":{\"S\":\"$day\"}}" \
    --projection-expression 'computed_at,activity_sources' \
    --output json |
  jq -e '
    .Item.computed_at.S and
    .Item.activity_sources.M.steps.S == "hae_daily_summary" and
    .Item.activity_sources.M.active_cal.S == "hae_daily_summary"
  ' >/dev/null || { echo "score validation failed: $day"; exit 1; }
done
```

For each Vitals chunk, run the metadata-only validator below before advancing.
The DynamoDB response is reduced inside the pipe and never printed:

```bash
set -o pipefail

validate_vitals_chunk() {
  chunk_start="$1"
  chunk_days="$2"
  python3 -c '
from datetime import date, timedelta
import sys
start = date.fromisoformat(sys.argv[1])
for offset in range(int(sys.argv[2])):
    print((start + timedelta(days=offset)).isoformat())
' "$chunk_start" "$chunk_days" |
  while read -r day; do
    aws dynamodb query \
      --table-name fitness-health-metrics \
      --region us-west-2 \
      --key-condition-expression '#d = :d' \
      --expression-attribute-names '{"#d":"date"}' \
      --expression-attribute-values "{\":d\":{\"S\":\"$day\"}}" \
      --projection-expression \
        'metric_source,hae_semantics,hae_automation_name,samples' \
      --output json |
    jq -e '
      def approved:
        ["hrv#hae", "rhr#hae", "spo2#hae", "resp#hae",
         "wrist_temp#hae", "body_temp#hae", "vo2_max#hae",
         "cardio_recovery#hae", "walk_hr#hae",
         "walking_asymmetry#hae", "walking_speed#hae",
         "walking_step_length#hae", "walking_double_support#hae",
         "stair_speed_up#hae", "stair_speed_down#hae",
         "six_min_walk_distance#hae", "physical_effort#hae"];
      [.Items[]
       | select(.hae_automation_name.S? == "PRISM Vitals & Mobility")
       | .metric_source.S as $source
       | ($source | sub("_samples(#[0-9]{3})?$"; "")) as $base
       | {source: $source,
          base: $base,
          semantics: .hae_semantics.S?,
          samples: (.samples.L? // [])}
      ] as $rows |
      ($rows | all(.semantics == "raw_observation")) and
      ($rows | all(.base as $base | (approved | index($base)) != null)) and
      ([$rows[]
        | select(.source | test("_samples(#[0-9]{3})?$"))
        | . + {
            shard_index:
              (if (.source | endswith("_samples")) then 0
               else (.source | capture("#(?<n>[0-9]{3})$").n | tonumber)
               end),
            timestamps:
              [.samples[]?.M.ts.S? | select(. != null)]
          }
       ]
       | group_by(.base)
       | all(
           ((sort_by(.shard_index) | map(.shard_index)) as $indices |
             $indices == [range(0; ($indices | length))]) and
           (all((.samples | length) <= 2000)) and
           (([.[].timestamps[]] | length) ==
             ([.[].timestamps[]] | unique | length))
         ))
    ' >/dev/null || { echo "vitals validation failed: $day"; exit 1; }
  done
}

validate_vitals_chunk 2026-07-12 7
validate_vitals_chunk 2026-07-19 7
validate_vitals_chunk 2026-07-26 7
validate_vitals_chunk 2026-08-02 7
validate_vitals_chunk 2026-08-09 7
validate_vitals_chunk 2026-08-16 7
validate_vitals_chunk 2026-08-23 2
```

Also require that no API/Lambda log in the chunk window contains 413, 422, 5xx,
`ValidationException`, or `Item size has exceeded the maximum allowed size`.
The date may have zero selected rows when HealthKit supplied no samples; that
sparse source absence is not, by itself, an ingestion failure.

Finally query `2026-08-25` metadata before and after the separately authorized
repair and require no repair-session change. These checks validate the intended
live rows; a successful deploy, HTTP response, or HAE UI completion alone is
not repair proof.

### 2.16 Coach model changes require a Bedrock protocol check

`CoachFunction` uses Bedrock ConverseStream so its messages, tool calls, and
stream events stay on Bedrock's common content-block format. Model-specific
inference fields remain explicit. The intended production configuration is in
`template.yaml`:

- `COACH_MODEL_ID=us.openai.gpt-5.6-sol`
- `COACH_REASONING_EFFORT=low`

GPT-5.6 Sol does not accept the legacy Anthropic Messages request body that the
Coach previously sent through `InvokeModelWithResponseStream`. Keep the main
tool loop, persisted history, images, tool results, and conversation summarizer
on Converse/ConverseStream content blocks. Pass `reasoning.effort` through
`additionalModelRequestFields`, and keep `maxTokens` explicit on every call.

Before deployment, verify the profile is active in `us-west-2`, then run a
small authenticated compatibility canary for text and one inert tool schema.
After deployment, require all of the following before calling the migration
healthy: Lambda state `Active` / update status `Successful`; environment values
match the two settings above; `/health` returns 200; an authenticated Coach
request streams visible text and its feedback trailer; a controlled read-only
Coach question does not call a write tool; and the Coach log window contains no
`AccessDeniedException`, `ValidationException`, traceback, timeout, or stream
parser error. Preserve the prior Coach artifact hash and stack template as the
rollback target.

---

### 2.17 A successful Today refresh does not imply morning sources arrived

Verified 2026-09-12: all four authenticated refresh reads can succeed while
the current-day health-metrics partition contains Withings rows and raw
Heart Rate only. `hr#hae_samples` / `hr_avg#hae` do not substitute for
`sleep#hae`, `hrv#hae`, or `rhr#hae`. In this state, missing recovery and sleep
are source-availability evidence; do not manufacture scores or change scoring.

Today initially shows the age of the backend `updatedAt`. After all four
manual refresh reads and cache updates succeed, it separately shows the
client check age and source age, for example `checked just now · data 13m
ago`. Both clocks advance while the screen is mounted. Failure of any refresh
retains `refresh failed · retry`; a successful check never rewrites backend
`updatedAt`. The source timestamp can advance because another feed arrived,
so it is not proof of Sleep or recovery-input completeness.

For a morning incident, query only the current date's source identities,
ingest timestamps, and score null/presence state. Raw Sleep Analysis is
assigned to its wake-up morning by the existing ingest path; recovery needs
HRV or Resting Heart Rate. Under explicit, bounded phone-operation
authorization, inspect the live dedicated Sleep/HR automations and
**PRISM Vitals & Mobility** before changing them. Verify enabled state,
raw JSON v2, batching, date range, cadence, and selected metrics without
opening endpoint/authentication screens. A historical screenshot or upload
completion alone is insufficient evidence.

After an authorized current-day foreground export, correlate API upload
status, raw stream classification, the expected current-day source rows,
Compute invocation/computed timestamp, and `/api/today` null/presence state.
Record phone settings before and after for rollback. If Mirroring cannot
connect, a physical unlock is required; do not infer current settings from
older screenshots. If no source rows arrive, distinguish unavailable phone
access from verified absence in HealthKit. This workflow does not authorize
historical Activity repair, Workouts/GPX, or other automation changes.

---

## 3. Deploy

### Isolated PRISM Steps reader (working manual pilot; daily expansion gated)

`backend/prism-steps.template.yaml` is an independent stack, **not** an update
to `fitness-dashboard`. See [`backend/PRISM_STEPS_READ.md`](backend/PRISM_STEPS_READ.md)
for the contract, secure provisioning boundary, build/change-set procedure and
acceptance gates. It grants only exact-record reads in one allowed source-day
partition and access to its own hashed-token secret. The handler restricts
reads to the two Steps aggregate identities and reuses the shared resolver.
It has no shared McFox API/ingest credential, writes, compute invocation,
phone configuration or schedule. The initial allowed day is 2026-10-23.

Do not deploy the main stack or rebuild Coach to ship this pilot. PR #25 was
explicitly approved and merged at `a7b1e82e05579397a838721fd77093057aa1c495`.
The separate stack reached CREATE_COMPLETE on October 24, 2026 Pacific.
The live integration handoff subsequently records the October 23 Site import,
repeat and durable reload passing. Natural HAE recurrence remains unverified.
Further scope changes require approval.
The patch continuation's Python 3.13 validation and isolated release/provisioning
procedure are recorded in [`backend/PRISM_STEPS_RELEASE_REVIEW.md`](backend/PRISM_STEPS_RELEASE_REVIEW.md).
Legacy source provenance uses bounded lists; the pilot preserves those shapes
and rejects a serialized response over 16 KiB without exposing partial data.

Scoped live verification (October 24, 2026): six additions only, tested handler
and all 656 layer files byte-matched, single GET route and exact inline IAM
verified. Endpoint:
`https://t3pylufe31.execute-api.us-west-2.amazonaws.com/api/prism/steps`.
AllowedDate remains `2026-10-23`. IAM simulation denies other dates,
query/scan/write, unrelated secrets and compute invocation; sort-key isolation
is application-enforced. Live auth checks returned 401 with the verifier
disabled/missing credentials and 403 for a valid credential on the wrong day.
No health-response body was read. Existing five McFox artifacts and shared
layer 44 were unchanged; no phone access or exports occurred.

Both stores were provisioned in one owner-approved session. The dedicated
verifier was activated after deployment checks and was unexpired at the final
check. Its 24-hour lifetime is deliberate; do not fetch or print its contents.
The latest handoff and native Site inspection supersede the earlier disabled
snapshot: Site version 13 uses environment revision 5 with the approved source
URL and `PRISM_STEPS_ENABLED=true`. This is the fixed-day manual pilot.
`PRISM_STEPS_DAILY_ENABLED` remains absent/false; no schedule exists. Do not
rotate or extend the live 24-hour pilot credential while preparing expansion.

#### Daily expansion review and rollback

See [`backend/PRISM_STEPS_DAILY_REVIEW.md`](backend/PRISM_STEPS_DAILY_REVIEW.md)
for frozen parameters, tests and secure rotation. `AccessMode=pilot` remains
the template default and keeps the original IAM partition. `daily` requires
an explicit reviewed anchor and all 92 exact date keys; runtime permits only
three completed Pacific days and refuses operation outside the 90-day term.
Regenerate and review the anchor if release timing makes it stale. Merge and
deploy this permissions expansion as a NEW `prism-steps-daily-read` stack
only after Mateo's approval. Preserve the original pilot stack/URL/token.
Do not deploy `fitness-dashboard`, rebuild Coach, alter phone workflows,
create a schedule, or enable Site daily mode during preparation.

The Site migration is schema-only/additive and leaves the pilot's tables,
receipts, Hevy and training history intact. First successful daily run copies
the old pilot snapshot as date-keyed evidence transactionally; failure cannot
publish a partial window. The service updater requires unique verified pilot
owner evidence and the unchanged owner-private Sites boundary. Do not make
that route public. Disable only daily mode for rollback; preserve pilot and
additive tables/receipts. Do not drop migrations after publication.

Documentation reconciliation: this PR incorporates the release evidence from
unmerged docs-only PR #26 (`67092f3`) and corrects its superseded Site-disabled
state using the live handoff/native metadata. PR #26 itself is not merged;
reviewers should supersede it with this documentation after accepting this PR.

**Non-obvious prerequisite:** Lambdas are python3.13; the box default is 3.12 and there's no Docker. `sam build` fails without the PATH export.

```bash
# Always deploy from a FRESH clone — never a stale working checkout
git clone https://github.com/91mateot/mcfoxhealth.git /tmp/mcfox-deploy && cd /tmp/mcfox-deploy

# SAM CLI, if absent
python3 -m venv /tmp/sam-venv && /tmp/sam-venv/bin/pip install -q aws-sam-cli

# REQUIRED: put python3.13 on PATH
export PATH="/home/ubuntu/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin:$PATH"

cd backend
/tmp/sam-venv/bin/sam build
/tmp/sam-venv/bin/sam deploy --stack-name fitness-dashboard --region us-west-2 \
  --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset
```

**Verify — a stack saying `UPDATE_COMPLETE` is not proof the code is live.** Confirm each Lambda's `LastModified` actually moved and the SharedLayer version incremented:
```python
call_boto3(service_name='lambda', operation_name='GetFunctionConfiguration',
           region_name='us-west-2',
           params={'FunctionName':'fitness-dashboard-IngestFunction-RYfFZRORN8J2'})
# check LastModified, Layers[].version, CodeSha256
```

**⚠️ If a PR changes `template.yaml` IAM grants, merge and deploy TOGETHER.** Merging alone leaves the live Lambda hitting `AccessDenied`. (PR #3 added IngestFunction CRUD on `fitness-exercises` / `fitness-user-config` / `fitness-daily-scores`.)

---

## 4. Common operations

### 4.1 Poll Hevy (incremental — the normal path)
```python
call_boto3(service_name='lambda', operation_name='Invoke', region_name='us-west-2',
  params={'FunctionName':'fitness-dashboard-IngestFunction-RYfFZRORN8J2',
          'InvocationType':'RequestResponse',
          'Payload': json.dumps({'action':'hevy_poll'})})
```
Returns `mode: incremental|cold_start`, `fetched`, `workouts_written`, `backfilled`, `exercise_rows_written`, `deleted`, `measurements_written`, `measurements_status`, `canonicals_touched`, `dates`.

### 4.2 Full Hevy backfill
```python
{'action':'hevy_backfill'}                                  # ignores watermark, full page-walk
{'action':'hevy_backfill', 'page_size':10, 'max_pages':4}    # bounded chunk
```
Expect `Sandbox.Timedout` (§2.7). Re-invoke until date coverage is complete, then verify with §5.3.

### 4.3 Sync state lives in `fitness-user-config`
| Key | Purpose |
|---|---|
| `hevy_last_sync` | Incremental watermark. Present ⇒ incremental mode; absent ⇒ cold-start page-walk. |
| `hevy_exercise_templates` | ~226 templates cached, refreshed if >7 days stale (forced on backfill). Provides real `primary_muscle_group`. |
| `oauth_refresh_lease#withings`, `oauth_refresh_lease#strava` | Short-lived conditional refresh leases; expired rows are harmless. |
| `oauth_status#withings`, `oauth_status#strava` | Sanitized credential health, expiry, attempt/success/check timestamps, and failure code. |
| `scoring` | Scoring weights — **hot-swappable, no deploy needed.** |

### 4.4 EventBridge schedules
| Rule | Schedule (UTC) |
|---|---|
| `IngestFunctionOAuthCredentialCheck` | `cron(0 8 * * ? *)` daily |
| `IngestFunctionHevyPoll` | `cron(30 8 * * ? *)` daily |
| `ComputeFunctionDailyBaselines` | `cron(0 9 * * ? *)` daily |
| `ComputeFunctionWeeklyCorrelations` | `cron(0 13 ? * SUN *)` |

### 4.5 Check OAuth credentials (safe to rerun)

```python
call_boto3(service_name='lambda', operation_name='Invoke', region_name='us-west-2',
  params={'FunctionName':'fitness-dashboard-IngestFunction-RYfFZRORN8J2',
          'InvocationType':'RequestResponse',
          'Payload': json.dumps({'action':'oauth_credential_check'})})
```

The response contains only `valid` / `refreshed` state and access-token expiry
per vendor. Provider failures raise a Lambda error so EventBridge retry and
Lambda error metrics can observe them. Inspect the `oauth_status#vendor` rows
for sanitized state; inspect Secrets Manager only to confirm version metadata,
never to print token values.

---

## 5. Health checks

### 5.1 Feed freshness (run this first on any "data looks wrong")
Per-day metric counts from `fitness-health-metrics`, grouped by source suffix (`#hae`, `#withings`, `#hevy`). **Healthy HAE ≈ 13–17 metrics/day.** A day with only 3–4 (HR only, no HRV/steps/sleep) means HAE is degraded phone-side — especially if Withings kept landing the same day.

### 5.2 Scores computed
`fitness-daily-scores` should have a row per day with non-null `recovery`, `strain`, `sleep_score`, `hrv`, `rhr`. Null `recovery`/`hrv` almost always traces upstream to an HAE gap, not to the scoring engine.

### 5.3 Hevy set-level coverage (the completeness check)
Every `source: hevy` date in `fitness-workouts` must have matching rows in `fitness-exercises`. Compute the set difference — **empty means complete.** This is the authoritative backfill check because the Lambda's own summary is unreadable when it times out.

### 5.4 Known-good reference state (2026-07-27)
| Metric | Value |
|---|---|
| `fitness-exercises` rows | 303 (256 Hevy-sourced) |
| Hevy dates covered | 28 / 28, zero missing |
| Rows with PR flags / e1RM | 55 / 104 |
| Rows with superset data | 31 (8 groups) |
| Set types | 525 `normal`, 147 `warmup`, 0 dropset/failure |
| Test suite | 224 passing |

---

## 6. Current state & open items

| Item | Status |
|---|---|
| Hevy sessions + set-level detail | ✅ Live and fully backfilled |
| Withings | ✅ Live |
| Strava (incl. HR streams → Edwards TRIMP zones) | ✅ Live |
| Lift engine (e1RM, PR, stall detection, weekly volume) | ✅ Live |
| **Apple Health / HAE** | ⚠️ PR16 server-side transport remediation is deployed. The two-stream source-evidence contract in §2.15 remains pending review/deploy, and HAE remains unvalidated until Mateo applies the bounded Activity Daily + raw Vitals & Mobility configuration and completes a clean live run. |
| Historical HAE backfill (6/29 → present) | ⏸️ Blocked on a manual export from the HAE iPhone app |
| HAE metric coverage | ⚠️ PR16 deployed `walking_asymmetry_percentage` and `vo2_max` source observations. This contract PR adds the approved Activity Daily identities plus Tier 1/2 raw physiology/mobility mappings; unknown names remain unpersisted and emit sanitized `HAE_UNMAPPED_METRIC` diagnostics. |
| Nutrition | ⚪ Frozen 2026-05-09, no automated feed |
| Per-session lifting calories | ⏸️ Design exists: join Apple-Health workout active energy to the Hevy session by `start_time`/`end_time`, mirroring the `hr#hae_samples` sleep-window intersection. Not built. |
| Non-weighted load metric | ⏸️ `duration_seconds`/`distance_meters` are now persisted per set, so a real load metric for timed/distance work is available to build. Not built. |
| Unbounded `.scan(Limit=N)` sweep | ⏸️ Deferred (PR list, correlations, coach-context) |
| Strava per-km splits | ❌ **Dropped by decision.** HR *streams* are already fetched and converted to zone-minutes — splits add little. Don't rebuild this. |
| `fitness-hae-2026` ingest key | ⚠️ Plaintext in Ingest Lambda env vars. Rotation to Secrets Manager is Mateo's call. |
| HAE freshness watchdog | ⏸️ Proposed, not built. `compute_day` only fires on health writes, so a silent HAE stop goes undetected — this is how a 6-week May→June gap passed unnoticed. |
| Historical temporal repair | ⏸️ Explicitly deferred. New writes use centralized temporal semantics, while pre-change Hevy rows retain their existing `date` keys. Do not re-key or recompute historical scores without a separately reviewed migration. |

---

## 7. Hard rules for agents

1. **READ-ONLY against third-party APIs.** Never POST/PUT to Mateo's Hevy, Strava, or Withings accounts.
2. **Never fabricate health data.** No invented metrics, doses, or calibration values. If you can't verify it, say so.
3. **Do not attempt to fix HAE.** It's phone-side; surface it to Mateo.
4. **Verify, don't trust.** A tool call returning `success` isn't proof of effect. Query the data. This applies to Lambda summaries, stack status, and subagent self-reports alike.
5. **Report unexplained zeros as unexplained.** Don't attach a causal story to an empty field without evidence — two wrong conclusions on 2026-07-27 (phantom duplicates, "he doesn't use supersets") both came from this.
6. **PR-only by default.** Merge and deploy need Mateo's explicit approval. Merge + deploy together when IAM changes.
7. **Don't reuse a stale local checkout** for deploys or agent work — clone fresh.

---

## 8. Keeping this current

This file is only useful if it stays true. **Update it in the same PR that changes behavior** — treat it like `ARCHITECTURE.md`.

Update when you:
- discover a trap, wrong vendor field name, or silent-failure mode → **§2** (the highest-value section; every entry saves a future rediscovery)
- change deploy steps or add a Lambda action → **§3** / **§4**
- resolve or add an open item → **§6**
- verify live state after a significant change → refresh **§5.4** and the header's *Last verified* date

Keep entries **specific and falsifiable** — exact field names, exact commands, exact numbers with dates. A vague warning is nearly worthless; "the live API returns `superset_id`, not the spec's `supersets_id`" prevents a real bug.

Related docs: `CLAUDE.md` (stack + conventions) · `ARCHITECTURE.md` + `architecture.json` (data flows) · `HANDOFF.md` (product + API contract) · `SCORING-ALGORITHMSfromClaudeChat.md` (scoring reference).
