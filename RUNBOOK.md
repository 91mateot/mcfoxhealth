# McFox Health — Operations Runbook

> **Read this before touching the ingest pipeline.** It exists so that any agent (Hermes, Claude Code, Codex, Cursor) or any human — including Mateo six months from now — can operate this system without rediscovering the traps below. Every entry here was paid for with a real bug.
>
> **Audience:** primarily AI coding tools; secondarily Mateo on periodic review.
> **Scope:** the AWS backend + data pipeline. Frontend/product docs live in `HANDOFF.md`, architecture in `ARCHITECTURE.md` / `architecture.json`, stack conventions in `CLAUDE.md`.
> **Last verified against live AWS:** 2026-07-27

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

Deletion caveat: the events feed is the authoritative deletion path, and its
48-hour replay makes ordinary retries safe. A full `/workouts` backfill cannot
necessarily reconstruct a deletion after Hevy has removed the vendor record.
Do not reset or discard the event watermark as a deletion-reconciliation
strategy; broader historical reconciliation requires a separately reviewed
change.

---

## 3. Deploy

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
| `scoring` | Scoring weights — **hot-swappable, no deploy needed.** |

### 4.4 EventBridge schedules
| Rule | Schedule (UTC) |
|---|---|
| `IngestFunctionHevyPoll` | `cron(30 8 * * ? *)` daily |
| `ComputeFunctionDailyBaselines` | `cron(0 9 * * ? *)` daily |
| `ComputeFunctionWeeklyCorrelations` | `cron(0 13 ? * SUN *)` |

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
| **Apple Health / HAE** | 🔴 **Degraded — Mateo's to fix.** 2026-07-26 landed 3 metrics vs 13–14 normal. Phone-side. |
| Historical HAE backfill (6/29 → present) | ⏸️ Blocked on a manual export from the HAE iPhone app |
| HAE metric coverage | ⚠️ `HAE_NAME_MAP` recognizes ~24 names; **unmapped metrics are silently dropped at ingest** (`if not mapping: continue`). Candidates: VO2 Max, blood pressure, blood glucose, body fat %, lean mass, waist, walking speed/asymmetry, mobility metrics, symptoms, state of mind. Deferred until HAE is healthy — and match names against a real export, not Apple's docs (see §2.1's lesson). |
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
