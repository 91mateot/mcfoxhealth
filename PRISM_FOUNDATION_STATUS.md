# PRISM Foundation Status — September 12, 2026 UTC

**Milestone:** current-state reconciliation complete; foundation closeout blocked.
**Evidence cutoff:** `2026-09-12T06:23:15Z` (September 11, 23:23 PDT).
The initial read-only baseline ended at `05:43:12Z`; the later cutoff includes
the authorized HR/Sleep enable operation and the bounded unintended sync
described below, followed by a read-only delayed-delivery check. **PR5 may not
begin.** This is a dated evidence record, not a live health dashboard. Reverify
before operational actions.

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
| Activity Daily | Delivering repeatedly before the phone operation. An unintended current-range sync at `2026-09-12T06:16:03.897Z` repeated the saved Yesterday export: seven September 10 rows, Days/Yesterday/completed_daily_summary, HTTP/integration 200. Guard version advanced to 3, all seven canonical sources remain hae_daily_summary, and Compute completed at `06:16:05.689603Z`. | July 12–August 24: all 44 dates still lack all seven summary rows and guards. Additional August 31 gap: no summaries/guard and all Activity source selectors unavailable. August 25–30 and September 1–10 have all seven summaries. September 11 is an incomplete local day, not a missing completed-day summary. |
| Vitals & Mobility | Delivering. Latest AWS request remains `2026-09-12T00:09:24.484Z`, Default/Since Last Sync/raw_observation; latest inspected source timestamp September 11 16:27 PDT. The phone list timestamp advanced during the stopped sync-all attempt, but no corresponding API request or AWS write was observed by cutoff. | Original July 12–August 24 repair is not evidenced as executed. Named-stream historical rows exist only August 20–24, with latest receipt August 26; legacy observations are not proof of repaired coverage. Sparse absence remains valid. |
| Dedicated HR | Existing automation enabled in place at 23:14 PDT after its visible contract matched. Enable-triggered and unintended sync-all requests arrived at `06:14:45Z` and `06:16:04Z`, both HTTP/integration 200, Default/Today/raw_observation. The latest row set has min/average/maximum plus one ledger containing 120 unique timestamps and zero duplicates; Compute completed. These are controlled/current-range delivery evidence, not natural recurrence. | Missing completed dates August 26–29 and August 31–September 10 remain 15 dates. September 11 is now present. A later scheduled/natural request is still required to prove recurrence. |
| Dedicated Sleep | Existing automation enabled in place at 23:13 PDT after its visible contract matched. No corresponding API request or stored Sleep row arrived by cutoff, including during the stopped sync-all attempt. | The 15 previously completed-date gaps remain, and September 11 is still absent at cutoff. Controlled delivery and later natural recurrence are both unresolved. Historical gaps earlier than the scoped catch-up require separate assessment. |
| Hevy | Twelve successful daily scheduled polls August 31–September 11 UTC. Latest completed `2026-09-11T08:30:28.650Z`; watermark `08:30:17.998060Z`; body-measurement phase successful. Schedule enabled at 08:30 UTC. | July 12–September 11 partition queries found 22 Hevy workout rows, zero duplicate Hevy IDs. Latest stored workout date August 29 is an observation, not an outage claim. Exercise completeness and full history were not re-audited. No accepted-empty-alias log appeared; that passive branch remains non-blocking. |
| Withings | Stored observation dates through September 10; latest scheduled OAuth check succeeded September 11 08:00 UTC. | Observation absence is not evidence of a missed measurement without source comparison. Previously recorded healthy OAuth state does not prove a token is unexpired now. |
| Strava | Stored workout date September 11; scheduled OAuth check succeeded September 11 08:00 UTC and a later refresh succeeded September 12 01:56 UTC. | Vendor-wide history/completeness was not re-audited. |
| Nutrition | No automated feed contract; historical runbook records manual import only. | Not re-queried; no current freshness or completeness claim. Absence of a health check must remain unknown. |

## Transport and storage evidence

Initial CloudWatch query window: August 31 00:00 UTC through `05:43:12Z`.

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

Post-baseline phone action at 23:13–23:16 PDT:

- Global Background App Refresh was observed as Wi-Fi & Cellular Data; the
  Auto Export app-specific switch was On. Low Power Mode was Off; Adaptive
  Power was On. No iOS system setting was changed.
- The existing Sleep and HR automations were each disabled initially. Visible
  settings matched Health Metrics, one correct selected metric, JSON v2,
  Today, Summary Off, Batch On, hourly, reminders Off, and no Workouts/GPX.
  Their last accepted AWS headers independently established Default grouping.
  Only the recurring Enabled switches were changed and saved successfully.
- At 23:16 PDT, the top circular-arrow control was mistaken for activity
  history and initiated **sync all automations**. Interaction stopped
  immediately. AWS proved that only Activity Daily and HR reached the service:
  two current-range requests, both HTTP/integration 200. Sleep and Vitals had
  no corresponding request by cutoff. No date picker or historical range was
  opened, and no saved automation setting changed.
- Together with the enable-triggered HR delivery, the post-baseline window had
  three requests, all HTTP/integration 200. Ingest and Compute error-pattern
  checks returned no matches. This raises the full window total from 25 to 28
  successful HAE requests. A final read-only query through `06:23:15Z` found
  no later API request or stream classification.

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

1. Wait for and correlate the first **later scheduled/natural** HR and Sleep
   runs in AWS, separate from the enable operation and stopped sync-all attempt.
   Do not manually export or invoke sync all for this gate. Validate
   dedicated raw rows, unique timestamps, sleep intervals/window, temporal
   attribution, safe fuller-session preservation, and Compute outcome.
2. Complete the separately bounded Activity and seven-chunk Vitals historical
   repairs with validation between operations. Do not silently fold the new
   August 31 Activity gap into the original July 12–August 24 authorization.
3. Before HR/Sleep historical catch-up, review one historical-day picker probe
   for each stream; exclude dates already present. Confirm authorization for
   those probes and any iOS system-setting changes separately.
4. Close or explicitly defer historical gaps with the user; resolve current
   outages. Update this matrix from new evidence and complete independent
   documentation review before starting the focused PR5 implementation.

## PHONE ACTION RESULT — HR/Sleep restoration

The bounded enable operation is complete. Both existing automations are On;
their saved non-secret settings were preserved. Current iOS background
conditions were inspected read-only and require no change. HR controlled
delivery passed. Sleep delivery and natural recurrence for both streams remain
open AWS evidence gates. Do not repeat this enable operation or use sync all as
a recurrence test.

## Change and verification record

The initial reconciliation invoked no Lambda and made no change. The subsequent
phone operation changed only the two existing recurring Enabled switches. HAE
then invoked existing endpoints; the enable-triggered HR request and stopped
sync-all attempt caused bounded current-range DynamoDB overwrites and Compute
invocations described above. No AWS resource, schedule, credential, historical
repair, or saved export contract changed. Documentation updates have no backend
deployment effect. JSON parsing, documentation links, diff scope, and
independent review validate the documentation change; they do not substitute
for runtime acceptance tests or foundation closeout.
