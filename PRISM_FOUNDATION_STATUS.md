# PRISM Foundation Status — September 12, 2026 UTC

**Milestone:** current-state reconciliation complete; foundation closeout blocked.
**Evidence cutoff:** `2026-09-12T05:43:12Z` (September 11, 22:43 PDT).
Later read-only detail queries corroborated this baseline; they did not trigger
new source traffic. **PR5 may not begin.** This is a dated evidence record,
not a live health dashboard. Reverify before operational actions.

## Verified deployment and repository

- GitHub `main`: `9a87c15cdb516bc3dd5eaf9d3350bfc953eb8623` (PR #22).
- Stack `fitness-dashboard`, `us-west-2`: `UPDATE_COMPLETE`; last stack update
  began `2026-08-30T02:52:17.964Z`.
- All five Lambda functions are `Active` / `Successful`; shared layer remains
  `fitness-shared:43`.
- Ingest is 300 seconds / 512 MB. Downloaded deployment artifact was inspected
  in memory; `handler.py` matches current main byte-for-byte, SHA-256
  `990664937a00ef7f54ce71f2cd0db2caacd63ed1249a543fa1244a48b6f6e76d`.
- API, Compute, Coach, Nutrition, and shared-layer hashes match the prior
  deployment baseline. This check did not invoke any Lambda or API handler.
- PR #15 is the only open PR; there are no open GitHub issues. Refresh #15 in
  place, retaining documentation-only scope and independent review. No merge
  or deployment is authorized by this status record.

| Artifact | AWS CodeSha256 |
|---|---|
| Ingest | `pkMoQUV2fAiGVTWT2Pg9YAMZfDttnIRKU86SYKohCHs=` |
| API | `FnDhAv9RAE2Lho7XA725LHHI0sasdRdfwOmZUGfGGSI=` |
| Compute | `+avXI4Tm2r3SF0IQXSlDhREWfRYwmIVWh6rrmBsMkok=` |
| Coach | `hTnBMJicB26ivq2Nq15u0AK1iHc8yXD5ye+fbr6xWlY=` |
| Nutrition | `keG66nKRA1xGE2c80mu7PXjtdjfIs9JilJ5eix/wkwo=` |
| Shared layer 43 | `mmjlZlFplIy7gpyGg1/S/w1JMOnBY4yCtwcEzDYadms=` |

## Source and historical-completeness matrix

| Source | Current evidence | Historical completeness / limitation |
|---|---|---|
| Activity Daily | Delivering. Latest request `2026-09-12T04:45:07.219Z`, seven rows for September 10, Days/Yesterday/completed_daily_summary; all seven canonical sources resolve to hae_daily_summary; score computed `04:45:11.680406Z`. | July 12–August 24: all 44 dates still lack all seven summary rows and guards. Additional August 31 gap: no summaries/guard and all Activity source selectors unavailable. August 25–30 and September 1–10 have all seven summaries. September 11 is an incomplete local day, not a missing completed-day summary. |
| Vitals & Mobility | Delivering. Latest request `2026-09-12T00:09:24.484Z`, Default/Since Last Sync/raw_observation; latest inspected source timestamp September 11 16:27 PDT. | Original July 12–August 24 repair is not evidenced as executed. Named-stream historical rows exist only August 20–24, with latest receipt August 26; legacy observations are not proof of repaired coverage. Sparse absence remains valid. |
| Dedicated HR | No accepted request after controlled export `2026-08-31T06:03:22.411Z` (August 30 local); latest stored date August 30. | Missing completed dates August 26–29 and August 31–September 10: 15 dates. September 11 also has no HR row at cutoff. Current recurrence is unresolved. |
| Dedicated Sleep | No accepted request after controlled export `2026-08-31T06:09:56.643Z` (August 30 local); latest stored date August 30. | Same 15 completed-date gaps as HR; September 11 also lacks a row. Current recurrence is unresolved. Historical gaps earlier than the scoped catch-up require separate assessment. |
| Hevy | Twelve successful daily scheduled polls August 31–September 11 UTC. Latest completed `2026-09-11T08:30:28.650Z`; watermark `08:30:17.998060Z`; body-measurement phase successful. Schedule enabled at 08:30 UTC. | July 12–September 11 partition queries found 22 Hevy workout rows, zero duplicate Hevy IDs. Latest stored workout date August 29 is an observation, not an outage claim. Exercise completeness and full history were not re-audited. No accepted-empty-alias log appeared; that passive branch remains non-blocking. |
| Withings | Stored observation dates through September 10; latest scheduled OAuth check succeeded September 11 08:00 UTC. | Observation absence is not evidence of a missed measurement without source comparison. Previously recorded healthy OAuth state does not prove a token is unexpired now. |
| Strava | Stored workout date September 11; scheduled OAuth check succeeded September 11 08:00 UTC and a later refresh succeeded September 12 01:56 UTC. | Vendor-wide history/completeness was not re-audited. |
| Nutrition | No automated feed contract; historical runbook records manual import only. | Not re-queried; no current freshness or completeness claim. Absence of a health check must remain unknown. |

## Transport and storage evidence

CloudWatch query window: August 31 00:00 UTC through the reconciliation cutoff.

- API Gateway: **25 HAE requests, all HTTP 200 / integration 200**, zero
  413/422/5xx in that window.
- Classified requests: Activity 12; Vitals 11; HR 1; Sleep 1. The window includes
  the three August 30 local controlled exports; do not count those as natural
  runs. Repeated subsequent Activity/Vitals delivery is established, but logs
  alone do not prove phone execution mode or current iOS settings.
- Every Activity result reports one completed date, seven writes, zero stale
  dates. Current coverage still excludes August 31.
- Vitals requests contain 11, 13, or 14 present families from the 17 configured
  families; received count alone does not establish completeness.
- Inspected Vitals ledgers on August 31 and September 9–11 have zero duplicate
  timestamps and contiguous shards. Largest inspected shard: 472 samples.
  These four dates are a bounded integrity sample, not a full-history audit.
- Ingest/Compute error-pattern queries returned no matches for the recorded
  runtime/error patterns. This does not establish absence of every possible
  warning or source outage.
- Hevy and OAuth rules are enabled with their expected action inputs; daily and
  weekly Compute rules are also enabled. No schedules were changed.

No health measurements, raw payloads, credentials, or source sample values are
included in this record. Sample timestamps were inspected in memory only to
produce bounded uniqueness/count/freshness evidence.

## Reproducible evidence locators

- Repository: [main at evidence SHA](https://github.com/91mateot/mcfoxhealth/tree/9a87c15cdb516bc3dd5eaf9d3350bfc953eb8623),
  [PR #15](https://github.com/91mateot/mcfoxhealth/pull/15),
  [PR #22](https://github.com/91mateot/mcfoxhealth/pull/22).
- AWS profile `personal`, region `us-west-2`; STS identity checked before reads.
- CloudFormation `DescribeStacks` / `ListStackResources`; Lambda `GetFunction`
  and `GetLayerVersionByArn`, selecting configuration/hashes without printing
  environment variables or signed download URLs.
- Logs: `/aws/apigateway/fitness-dashboard`,
  `/aws/lambda/fitness-dashboard-IngestFunction-RYfFZRORN8J2`, and
  `/aws/lambda/fitness-dashboard-ComputeFunction-J6MPwp1zKSae`.
- API status query ID: `52fce320-1322-4e93-a7c1-e7d93a04e0d3`.
  Filter HAE route/path, then count by `status` and `integrationStatus`.
- Stream classification query ID: `012aea02-c8d8-4719-9d45-0a2616ed49c4`.
  Filter `HAE_STREAM_CLASSIFIED`, then group by automation name, semantics,
  metric count, aggregation, and period.
- Activity results query ID: `8885efe0-9783-48ea-be99-3720e1bcb27a`.
  Filter `HAE_DAILY_SUMMARY_RESULT`, inspect bounded dates/counts/status.
- Hevy completion query ID: `75029730-758a-4eaf-898d-45047ecf98ab`;
  empty-alias query ID: `a005c408-de53-499e-a52b-1a100a0b3314`.
- Ingest error query ID: `26273995-c8ad-4766-9e61-9556e868d376`;
  Compute error query ID: `eea75236-0f4a-4ba9-b688-f679e54a40a7`.
  Patterns: ERROR, Traceback, Task timed out, Sandbox.Timedout,
  ValidationException; Ingest also HAE_UNMAPPED_METRIC,
  HAE_STREAM_REJECTED, partial_failure.
- DynamoDB `Query` on each `fitness-health-metrics` date partition July 12–
  September 11 inclusive, with pagination and consistent reads. Projection:
  identity, semantics, guard version, automation name, raw metric names,
  ingestion/source dates, temporal metadata; no scalar health values.
- `GetItem` on `fitness-daily-scores` for August 31 and September 9–11,
  projecting `computed_at` and `activity_sources` only. Ledger checks on the
  same four dates retain only derived counts and latest timestamps.
- `GetItem` for `hevy_last_sync`, `oauth_status#withings`, and
  `oauth_status#strava`; these are sanitized control/status rows, not secrets.

Query IDs are convenience locators with limited retention; replay the named
filters and date/partition boundaries to refresh evidence.

## Remaining gates and sequence

1. Inspect existing HR/Sleep configuration on the phone; enable the two existing
   automations in place only if their validated contracts still match. Obtain
   current background-setting evidence without changing system settings.
2. Correlate the first subsequent natural HR/Sleep runs in AWS and validate
   dedicated raw rows, unique timestamps, sleep intervals/window, temporal
   attribution, safe fuller-session preservation, and Compute outcome.
3. Complete the separately bounded Activity and seven-chunk Vitals historical
   repairs with validation between operations. Do not silently fold the new
   August 31 Activity gap into the original July 12–August 24 authorization.
4. Before HR/Sleep historical catch-up, review one historical-day picker probe
   for each stream; exclude dates already present. Confirm authorization for
   those probes and any iOS system-setting changes separately.
5. Close or explicitly defer historical gaps with the user; resolve current
   outages. Update this matrix from new evidence and complete independent
   documentation review before starting the focused PR5 implementation.

## PHONE ACTION REQUIRED — HR/Sleep restoration

Copy this into the phone-capable Computer Use surface. If iPhone Mirroring or
safe controls are unavailable, stop and report the limitation rather than
substituting a different device/account.

```text
Use Computer Use with iPhone Mirroring for the existing Health Auto Export
(HAE) automations Mateo HR and Mateo sleep only.

Goal: inspect both saved contracts and enable their existing recurring
switches in place. AWS has no accepted request from either after August 30
local controlled validation. Do not assume the current switches are Off.

Before changing either automation, verify both safely:
- Destination/data type: existing REST Health Metrics automation.
- JSON, export version v2.
- Summarize Data Off; Time Grouping Default.
- Saved Date Range Today; Batch Requests On.
- Every 1 Hours.
- Mateo HR: Heart Rate only, one selected metric.
- Mateo sleep: Sleep Analysis only, one selected metric.
- No Workouts or GPX.

Record each labeled recurring Enabled switch and last visible activity time.
If either contract differs or grouping cannot be verified without modifying
settings, stop and report the exact safe mismatch/unknown. Do not normalize,
recreate, duplicate, delete, or change the saved configuration to fit this
prompt. Do not navigate through credential-bearing settings to obtain proof.

If both contracts match, change only each recurring Enabled switch from Off
to On where necessary. If already On, leave it On. Save only if the app
requires saving this exact enable-state change and the saved contract was
verified unchanged. Record exact local timestamps and timezone for each
change and any export that starts automatically. Do not run Manual Export,
select historical dates, or retry any failed/ambiguous request.

Read current Background App Refresh (global and HAE-specific) and Low Power
Mode only if safely accessible. Do not change iOS settings. Their earlier
values are historical, not current proof. Do not change Activity Daily,
Vitals & Mobility, Apple Health permissions/source priority, credentials,
other automations, or unrelated settings.

Do not expose or retain credentials, headers, endpoint secrets, health values,
or screenshots containing them. Return only safe settings, before/after
switches, exact timestamps/timezone, visible success/error status, and any
unknowns. Use credential-free screenshots only when helpful.

Return after the bounded operation. No background monitoring task, historical
export, or retry is authorized by this prompt. AWS verification continues in
the existing Codex task after I paste your result.
```

An export triggered immediately by enabling is controlled-delivery evidence
only. To establish recurrence, correlate phone timestamps with a later
scheduled/natural request per stream, separate from the enable operation.
Do not close the foundation gate from the enable-triggered export alone.

AWS ingestion criteria for each observed request:
HTTP/integration 200, `raw_observation`, Default/Today, and exactly its named
metric; HR aggregate/ledger integrity; valid or safely preserved Sleep record;
no summary guards, unexpected source writes, 413/422/5xx, or runtime errors;
expected Compute outcome. Recurrence additionally requires the later natural
request described above; an enabled switch alone does not close the gate.

## Change and verification record

This reconciliation made no AWS resource, source-system, schedule, credential,
health-data, or phone changes and invoked no Lambda. Documentation updates
have no backend deployment effect. JSON parsing, documentation links, diff
scope, and independent review validate the documentation change; they do not
substitute for runtime acceptance tests or foundation closeout.
