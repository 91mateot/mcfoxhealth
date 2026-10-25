# PRISM Steps read pilot

Status: AWS pilot deployed October 24, 2026 after explicit approval of PR #25.
Dedicated credentials were provisioned in the same session and the verifier
activated after scoped deployment checks. PRISM importing remains disabled;
no Site canary/import/display or natural HAE recurrence is established.

This is a separate SAM stack (`prism-steps-read`) in the same AWS account and
`us-west-2`. Build **only** `prism-steps.template.yaml`. Do not deploy it as
`fitness-dashboard` or build/deploy the main stack for this feature. It creates
one HTTP API, one read-only Lambda and its own shared-code layer. It imports
the existing health-table name, not ownership of the table. This avoids
unrelated Coach dependency drift and leaves all four phone workflows in place.

## Contract

`GET <StepsUrl>?date=2026-10-23` with `x-prism-steps-key`. `StepsUrl` is the
new stack output, **not** the existing McFox API origin. This deliberately
changes the earlier same-origin route proposal to isolate credentials and
deployment. The site adapter must allowlist that exact new origin and path.

The handler accepts one canonical calendar date, no other query parameters,
and no request body. Both application policy and DynamoDB `LeadingKeys` IAM
restrict it to `AllowedDate`; the initial canary is October 23, 2026. Unknown
paths, duplicate dates, ranges, metrics, and write methods are rejected.
API Gateway exposes only the GET route; the handler also checks its path and
method when invoked directly.

Source selection reuses `shared.hae_daily`: strongly consistent exact-key read
of `steps#hae_daily_summary`, then `steps#hae` only when the summary has no
value. It never sums either representation or reads sample ledgers. Invalid
present values fail closed. IAM allows `GetItem` on the permitted partition;
the exact two sort-key and metadata projection restrictions are enforced by
the handler (IAM LeadingKeys cannot restrict sort-key values). The execution
role cannot query/scan/write tables, invoke compute, or read other secrets.

Response v1 identifies `backend: mcfox`, `transport: health_auto_export`,
`metric: step_count`, the requested date, availability, and `observation`.
A missing observation is `null`; stored zero is numeric zero. Available
observations include count units, source policy, aggregate semantics, nullable
stored provenance, and a deterministic `content_fingerprint`. Original units
are in `provenance.hae_raw_units`; recording-app provenance is
`provenance.hae_source` when retained. No named zone, update timestamp, or
recording app is inferred when absent. Daily bucket timestamps are preserved
as source labels; they are not upload times. `quality: stored_value_valid`
checks storage shape only, not Apple Health completeness or clinical quality.
Legacy aggregates preserve the writer's `hae_raw_units`,
`hae_raw_metric_names`, and `hae_sources` lists (at most 16 bounded strings),
without flattening them into summary-style scalar provenance.

`completeness.lookup_complete` means both required exact-key lookups are
resolved (or the preferred summary was found); `next_cursor` is null and
`phone_data_complete` stays `unknown`. A content fingerprint is not a monotonic
source revision. Responses are bounded by projected fields (512 characters
each; legacy list members retain the writer's 64/128/256-character limits),
a 16 KiB total JSON body ceiling, a JavaScript-safe integer count, and no-store headers. Dependencies or
invalid storage yield sanitized 503 without a partial response or logged data.

## Secure provisioning (future authorized local execution)

Generate a distinct random token with at least 32 bytes of entropy using the
approved secure in-memory provisioning flow. Never reuse any McFox/HAE API
key. Store **only its SHA-256 digest** in a dedicated Secrets Manager secret
whose name starts `prism-steps-read-`, with this schema:

- `enabled`: boolean (must be true)
- `token_sha256`: lowercase 64-character hex digest
- `expires_at`: timezone-aware ISO timestamp with a bounded pilot lifetime

The token is base64url without padding (43–128 characters). Raw token material
belongs only in PRISM's server-side runtime secret store. Never expose it in
browser code, setup responses, chat, handoffs, shell arguments, logs, or files.
The secret ARN is a non-secret deployment parameter. Do not fetch the shared
`fitness-api-key`, rotate existing credentials or copy a personal AWS session.
Secrets Manager is read on each authenticated request; disabling, expiry and
rotation therefore have no process-local stale-key cache. Missing, malformed
or unavailable auth configuration fails closed. Customer-managed KMS keys
would require a separately reviewed exact-key decrypt grant; the template
does not include one.

The owner explicitly approved normal native secret-marked tool input for the
October 24 release, superseding the earlier zero-tool-trace broker requirement.
The release generated a fresh token and provisioned both stores in one local
session; no masked token readback or cross-chat transfer was used. This does
not promise zero tool traces. Keep values out of documents, source, files,
application logs and browser bundles. Never substitute a shared key or transfer
the broader Sites service token to the phone. Further provisioning needs its
own applicable authorization.

## Build and deployment gate

Merge and deployment require Mateo's approval under AGENTS.md. From a fresh
clone, inspect current account identity (expected account suffix 7207), region
and existing table before provisioning. With Python 3.13 and SAM available:

```text
cd backend
sam validate --lint --template-file prism-steps.template.yaml
sam build --template-file prism-steps.template.yaml --build-dir .aws-sam/prism-steps
```

Prepare a change set for **new** stack `prism-steps-read`, using that built
template, `AllowedDate=2026-10-23`, and the dedicated secret ARN. Review that it
creates only the isolated pilot resources and touches no existing McFox
resource. Do not execute a change set based on this document alone. Record
the deployed function artifact hash, IAM role policy and exact StepsUrl.

## Acceptance and next handoff

Offline checks: `python -m pytest tests/test_prism_steps.py -q`, then the
repository's normal offline regression suite. Synthetic tests are contract
cases, never invented personal observations or claimed live measurements.

After deployment approval and secure provisioning, verify the restricted
credential against wrong dates, broad routes, methods and revoked/expired
state. Confirm live IAM denies other partitions, scans, writes, unrelated
tables and secrets, in addition to application tests. Use only the October 23
Steps canary; report receipt IDs/counts and metadata without measurement
values. An unauthenticated 404/405 from this dedicated API proves route
absence, not validation of auth on the existing dashboard API.

Implement PRISM's server-side adapter separately: fixed origin/path, redirects
rejected, timeout/body bounds, strict response/date/metric/unit validation,
atomic durable replace keyed by backend/date/metric/source policy. Persist
fetch time separately from source/ingest timestamps. Identical content must
not add totals; changed content replaces the current snapshot with an audit
record. A fetch/auth/storage failure must preserve the prior snapshot.
Never replay these rows through the phone receiver as HAE receipts.

Verify display, repeated import and changed-state behavior before scheduling.
Browser-closed fetching and a later **natural** HAE upload are separate gates.
The fixed-day IAM policy must be deliberately reviewed before enabling any
daily rolling window; this pilot cannot claim ongoing daily synchronization.
Rollback is to disable the dedicated secret or remove only the new pilot
stack; the source table and existing phone workflows remain untouched.
