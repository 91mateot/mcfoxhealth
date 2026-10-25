# PRISM Steps pilot release review

Release update: PR #25 was subsequently explicitly approved and merged at
`a7b1e82e05579397a838721fd77093057aa1c495`. The isolated AWS stack is deployed;
both stores were provisioned through the owner-approved same-session native
secret-input procedure, superseding the older broker/approval gates below.
PRISM importing remains disabled. See the scoped live evidence in
[`RUNBOOK.md`](../RUNBOOK.md); the remainder preserves the original review
package, not a new request to execute or provision anything.

Prepared October 24, 2026. **Not merged, deployed, or provisioned.** This is an
approval package, not permission to execute the commands below. The PRISM site
is still unconnected; source availability in McFox is not a PRISM import.

## Patch provenance and continuation

- Repository base: `c9e96109e0dd30ac6e845eb7aa4d987159bc852d`.
- Drive artifact: `PRISM-Steps-Read-Pilot.patch`, file ID
  `1Bb105HLn8qRFT07s0tErl3SW1E-PWVlN`.
- SHA-256: `68f98546ac3707fa4b0f032ec13b092d70ada9d13630fcf2ce91029261ce4b75`.
- Original unpublished commit: `367916c4ad46ceb2e6f1cb9d73ab2371283186b6`.
- Applied unchanged with `git am` as `7721dfc8e903f786c754a5bc1ebd60985d9fb696`;
  both have stable patch ID `1e3fa69d4c3f91b0ab5f3267f9469a4acf9bf120`.
- An independent read-only review found that the existing raw/legacy writer
  stores provenance lists. A follow-up fix accepts the writer's bounded
  `hae_raw_units`, `hae_raw_metric_names`, and `hae_sources` lists for legacy
  rows, preserving scalar summary provenance and the 16 KiB wire-response cap.
  Tests cover valid stored zero, malformed/oversized lists, and JSON escaping.
  The endpoint and template were not recreated.

## Completed local validation

- Python 3.13.13; SAM CLI 1.158.0.
- Focused suite: **52 passed**. Prescribed offline suite: **426 passed,
  21 deselected**, one unrelated Starlette/httpx deprecation warning.
- Tests disabled EC2 metadata, removed inherited profile selection, used
  synthetic credentials with empty config files, and blocked socket connects.
  No live source, API, secret, or health value was used. An initial broad run
  failed because an inherited `personal` profile was absent from the isolated
  configuration; the corrected harness passed without code changes for that
  issue.
- `sam validate --lint --region us-west-2 --template-file prism-steps.template.yaml`
  passed. Isolated `sam build` succeeded with Python 3.13 on PATH, including
  the shared-layer Makefile's `python3`. Only the pilot template was built.
- JSON parsing, Python compilation, whitespace, and source/build byte checks
  passed. Build output stays ignored under `backend/.aws-sam/prism-steps`.
- Offline SAM expansion and IAM assertions confirm the plan below. This is
  not a live CloudFormation change set. No package was uploaded.
- cfn-guard compliance was not run: neither the CLI nor Python binding was
  available. SAM lint and scoped IAM tests are not a substitute for a full
  compliance ruleset. Service-side validation, live IAM denial checks, and
  actual Lambda execution remain post-approval checks.

## Isolated resource/change plan

Read-only preflight confirmed the `personal` account (suffix **7207**) and
`us-west-2`: `fitness-dashboard` remains `UPDATE_COMPLETE` at its September 12
update; `fitness-health-metrics` is ACTIVE; `prism-steps-read` does not exist.
No source table contents were read during this preparation.

The template expands into six new resources: one HTTP API, default stage,
Lambda, Lambda role, API-to-Lambda permission, and independent shared layer.
It references the existing health table by name without acquiring ownership.
The generated role has only `dynamodb:GetItem` on that table constrained by
`LeadingKeys=2026-10-23`, the dedicated secret's `GetSecretValue`, and standard
Lambda execution logging permissions. Exact Steps sort keys and metadata
projection remain application-enforced. No table, schedule, existing API,
ingest/Coach artifact, or phone configuration is updated. A default Lambda log
group can be created on invocation by the execution logging policy.

Required parameters: `HealthMetricsTableName=fitness-health-metrics`,
`AllowedDate=2026-10-23`, and a same-account dedicated `StepsSecretArn`.
The endpoint is a new origin from output `StepsUrl`; it must never be confused
with the current `fitness-dashboard` origin or the direct PRISM phone receiver.

## Secure provisioning gate and procedure

**Current blocker:** native Sites `update_environment_variables` requires a
literal string `value`. Its `is_secret=true` masks later readback but does not
establish a secret-reference or local in-memory transfer mechanism that keeps
the input out of tool traces. No supported broker from a local cryptographic
generator to that tool has been established. Do not generate a token, create
a secret, or substitute a shared credential while this gate is closed.

After separate approval and establishment of an owner-operated or supported
secret-reference broker that does not expose plaintext to agent context,
tool traces, logs, shell arguments, files, clipboard, or browser bundles:

1. Reconfirm the exact owner-private PRISM Site/workspace identity from its
   saved hosting metadata. Preserve its audience and all unrelated variables.
2. Generate at least 32 random bytes in that broker's memory; encode base64url
   without padding. Set a deliberate pilot expiry (proposed: 24 hours).
3. Calculate SHA-256 in the same process. Create a NEW dedicated secret named
   `prism-steps-read-<pilot-id>` in the verified AWS account/region containing
   only `{enabled:false, token_sha256:<digest>, expires_at:<aware timestamp>}`.
   Raw token material must never be stored in AWS. Return only its ARN and
   version identifier. Use the AWS-managed secret encryption key unless an
   exact CMK grant has been separately reviewed.
4. The same broker writes the raw token directly to the confirmed Site's
   server-only runtime secret store (proposed adapter key
   `PRISM_STEPS_READ_TOKEN`, `is_secret=true`). This key is a proposed adapter
   contract, not a claim that the adapter already exists. Return only key name,
   secret flag, and environment revision. No token readback is permitted.
5. On either write failure, leave or restore the AWS verifier disabled and
   halt. Do not fall back to a file, chat message, tool literal, shared
   `fitness-api-key`, Sites service token, or personal AWS session. Document
   only sanitized state and identifiers. After success, discard the raw
   process buffer; ordinary managed-runtime memory cleanup is best effort.
6. Keep the verifier disabled until the reviewed pilot stack and separate
   PRISM adapter are ready. Activation is a separately approved update of
   the dedicated verifier. Disabling/expiry are checked every request.

No raw token, digest, secret version, or Site environment revision was created
in this task. Runtime SDK secret resolution belongs to the Lambda; operators
must not retrieve the secret value into an agent transcript.

## Future deployment sequence — approval required

1. Review the PR and approve merge explicitly. Merging `main` can also trigger
   the repository's existing Vercel automation; it has not been performed here.
2. Resolve the provisioning gate above. Use a fresh clone of the approved
   commit and repeat the isolated build. The secret ARN and artifact bucket
   below are non-secret identifiers, supplied from the approved environment.
3. After approval for AWS preparation, upload only pilot artifacts to an
   approved existing artifact bucket and create an **unexecuted** change set:

   ```bash
   cd backend
   sam deploy --profile personal --region us-west-2 \
     --template-file .aws-sam/prism-steps/template.yaml \
     --stack-name prism-steps-read --capabilities CAPABILITY_IAM \
     --s3-bucket "$PRISM_ARTIFACT_BUCKET" --s3-prefix prism-steps-read/pilot \
     --parameter-overrides HealthMetricsTableName=fitness-health-metrics \
       AllowedDate=2026-10-23 StepsSecretArn="$PRISM_STEPS_SECRET_ARN" \
     --no-execute-changeset
   ```

   This is a future command, not one that ran here. Do not use `--resolve-s3`
   to create an unreviewed packaging stack or deploy as `fitness-dashboard`.
4. Inspect actual changes and service validation: expect only new pilot
   resources. Stop on any modification/removal of an existing McFox resource,
   table ownership, date-scope expansion, broad IAM, unexpected secret, or
   Coach build. Record the actual change-set ARN; no ARN exists yet.
5. Obtain Mateo's approval to execute the concrete change set. Then verify
   new Lambda artifact hash/layer, exact IAM role and API route, output
   `StepsUrl`, and absence of changes to the existing stack. An infrastructure
   completion status alone is not end-to-end acceptance.
6. Perform only separately authorized October 23 Steps canary reads and
   denial/revocation checks. Sanitize output before it reaches logs or tools.
   Verify no query/scan/write/compute authority or unrelated secret/date access.
   Other sort keys in the allowed partition are application-restricted, not
   IAM-restricted; do not claim an IAM sort-key deny.
7. Connect PRISM through its separate fixed-origin server adapter, validate
   atomic repeat-safe import and display, then review browser-closed fetching
   separately. Natural HAE recurrence and any rolling-day IAM expansion remain
   later gates. No phone export or settings change is part of this release.

Rollback after an approved release is to disable only the dedicated verifier
or remove only the new pilot stack after approval. Source records and all four
existing HAE workflows stay intact. No rollback action is needed or authorized
by the preparation in this document.
