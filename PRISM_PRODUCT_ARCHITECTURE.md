# PRISM Product Architecture

**Status:** Approved product direction; future implementation remains gated by
the roadmap below.
**Scope:** Product capability ownership, future evidence architecture, and
reference requirements. Current runtime topology remains documented in
[`ARCHITECTURE.md`](ARCHITECTURE.md) and [`architecture.json`](architecture.json).

## Product north star

McFox Health is evolving into **PRISM**, the primary personal performance
operating surface. PRISM is not merely a workout tracker, Apple Health
dashboard, readiness-score clone, peptide tracker, or replacement for Hevy or
Bevel.

PRISM combines physiological evidence, workouts and activity, recovery, body
composition, symptoms, exposures, interventions, reported context,
longitudinal history, provenance, completeness, derived signals, and reasoning
to answer:

- What matters today?
- What should I do, and why?
- What has been changing over time?
- What exposures consistently precede symptoms?
- What activities are repeatedly tolerated?
- Which intervention/outcome associations are plausible, unsupported, or
  still uncertain?

Scores such as recovery, strain, readiness, and ACWR are contextual signals.
They do not govern the decision by themselves. Trustworthy evidence,
capability over time, uncertainty, and actionable synthesis are the product.

## Current interface and source ownership

Chat remains the current PRISM Coach interface. McFox is the long-term
integrated application and persistent intelligence/data layer. The deployed
McFox Bedrock Coach remains a runtime component; its existence does not change
this operating split. ChatGPT Work is not the permanent Coach surface.

Apple Health/HAE owns physiological and movement evidence; Hevy owns detailed
strength-training evidence; Strava provides cardio/GPS enrichment; Withings
provides direct body-composition evidence. User reports provide subjective
context. Derived scores remain interpretations, never replacements for source
evidence. Nutrition has no automated source contract today.

The PRISM Canonical Specification governs Coach reasoning. The user-provided
September 1 Coach TXT is a pointer to that specification and a full handoff,
not their contents or the codebase specification. Its historical `sandbox:`
links are not repository files. Obtain and inspect the actual canonical
specification before claiming alignment with it; do not reconstruct it from
this architecture document.

## Capability ownership policy

> Do not replicate an external application merely to consolidate screens.
> PRISM should own a capability when owning it materially improves evidence
> quality, longitudinal reasoning, actions, or user friction.

Classify product capabilities as:

### Own

PRISM directly owns capabilities central to its differentiated intelligence:

- evidence and provenance semantics
- source health and data completeness
- longitudinal reasoning
- symptom and exposure history
- intervention timelines
- derived associations and inferences
- cross-domain context
- the Daily Operating Picture and decision synthesis

### Integrate

Keep an external application as the execution or source system when it already
works well and recreating it would not currently add differentiated value.
Current examples are Hevy for resistance-training execution, Apple Health via
HealthAutoExport (HAE) for physiological observations, Strava for cardio and
activity observations, and Bevel as an external interpretation/reference
layer.

### Eventually absorb

A capability may remain external today while PRISM preserves a path to native
ownership if that would materially improve evidence, reasoning, action, or
friction. Workout execution is the primary current example.

PRISM must not rebuild Hevy now. Reevaluate native execution when direct
capture of planned versus actual work, RPE/RIR, symptoms during training,
substitutions, progression intent, target rationale, and immediate or
post-session feedback would create a meaningful advantage.

## Evidence architecture

Preserve three logical layers. Do not create one universal event table solely
for implementation convenience.

1. **Observations/evidence** — measured and user-reported facts, retaining raw
   source identity, timestamps, units, provenance, completeness, and
   uncertainty.
2. **Interventions** — what was deliberately done or administered, with its
   own durable history and without using the TTL-based telemetry event table.
3. **Derivations/inferences** — computations, associations, hypotheses, and
   reasoned conclusions that cite their input evidence and computation or
   reasoning version.

Epistemic status belongs in structured data, not prose reconstructed by an
LLM. Within the appropriate layer, important information must be
distinguishable as measured, user-reported, intervention/logged, derived,
inference, or uncertain/incomplete. Do not recycle a prior PRISM inference as
new measured evidence.

Keep these statements distinct:

- **Fact:** an intervention happened.
- **Fact:** a symptom occurred.
- **Derived association:** symptom frequency changed during a period.
- **Inference:** an intervention may be associated with that change.

Temporal proximity never establishes causation.

## Longitudinal evidence requirements

### Symptoms

First-class symptom evidence may include pain, numbness, tingling, weakness,
fatigue, and soreness, with severity, distribution, neurologic features,
start/end, and user confidence where applicable.

### Exposures

First-class exposure evidence may include prolonged sitting, travel, long
walking days, unusual physical load, festival/event activity, and exercise
exposure.

### Interventions

Durable intervention evidence may include protocol doses,
medication/supplement interventions, workout modifications, mobility work, and
recovery interventions.

### Capability milestones and outcomes

Durable outcomes may include return-to-activity milestones, symptom-free
exposures, sport readiness, performance changes, and other dated evidence that
capability is expanding or contracting. A milestone is an observed or reported
outcome, not proof that a nearby intervention caused it.

### Event-aware reasoning

Symptoms, exposures, interventions, activities, and outcomes must be linkable
without asserting causation. The future system must support time-window and
comparison questions such as:

- Show prolonged-sitting exposures followed by neurologic symptoms within six
  hours.
- Compare symptom incidence after prolonged sitting with incidence after
  loaded posterior-chain training over six months.
- Identify activities that are repeatedly tolerated without symptoms.

This event-aware longitudinal reasoning is more central to PRISM than adding
another daily readiness score.

## Workout and activity evidence requirements

The future source-neutral model must represent more than `exercise + weight +
reps`. Where applicable, it must be able to preserve:

- workout/session identity and activity type
- exercise identity, sets, reps, load, duration, distance, and speed
- bodyweight work and added external load
- unilateral/per-side semantics
- warm-up versus working sets
- timed exercises and loaded carries
- supersets or linked exercise blocks
- cardio work
- RPE and RIR
- exercise substitutions
- progression targets and the rationale for a changed target
- planned versus actual performance
- exercise/session notes
- PR and estimated-1RM state
- symptoms during or after activity
- user-reported session tolerance

These are forward-compatibility requirements, not fields approved for current
implementation.

### Total physical load

A day without a structured workout is not necessarily a rest or detraining
day. Preserve independent source evidence for:

- structured resistance training
- structured cardio
- walking and steps/locomotion
- travel or event movement
- prolonged standing
- other meaningful non-workout physical activity

Do not collapse these observations into one canonical raw `total_load` value.
Derived layers may later estimate `structured_training_load`,
`cardiovascular_load`, `locomotion_load`, `musculoskeletal_load`, subjective
exertion, or `total_contextual_load`. These remain secondary/contextual
evidence with explicit inputs and uncertainty.

## Roadmap and gates

PR1–PR4 established Temporal Semantics, Hevy Sync Integrity,
Missingness-Safe API Semantics, and OAuth Reliability. Subsequent foundation
changes shipped through GitHub PRs #16 and #19–#22. Roadmap labels **PR5/PR6/PR7**
are capability milestones, not GitHub pull-request numbers.

### Foundation gate — before PR5

The dated [foundation status](PRISM_FOUNDATION_STATUS.md) is the current
reconciliation record. As of September 12, 2026 UTC, the backend matches PR #22,
but foundation closeout is **blocked** by unproven HR/Sleep recurrence, absent
post-enable Sleep delivery, and incomplete repair work. Documentation may be
refreshed while phone work is pending; that does not open the implementation
gate.

Before PR5, record and verify separately:

- deployed artifacts and current API contracts;
- configuration, controlled ingestion, and subsequent natural delivery for
  Activity Daily, Vitals & Mobility, dedicated Heart Rate, and dedicated Sleep;
- source-specific units, timestamps, timezone, aggregation, and sample-density
  expectations, distinguishing source absence from transport failure;
- historical repair coverage, or an explicit user decision to defer bounded
  historical gaps; no active source outage may remain hidden;
- healthy Hevy synchronization and scheduled OAuth checks;
- refreshed authoritative documentation and independent review readiness.

A real HAE workout payload is a **PR7 workout-ingestion gate only**. It does
not block PR5 metric provenance. No HAE Workouts support is authorized here.

### PR5 — Provenance, Metric Semantics & Source Health

Add a missingness-safe metric evidence and source-health contract. Before
coding, enumerate the exact initial metric keys and API response paths on
current main; the proposed first surface is the existing Today read contract
and its daily-score inputs. Record the accepted inventory and tests in the
implementation PR rather than expanding to all endpoints implicitly.

The additive metric envelope must represent value, unit, semantic status,
source feed/raw metric, source timestamp, ingestion timestamp, as-of time,
sample count, aggregation/derivation method, time window and timezone,
algorithm version for derivations, structured completeness/quality reasons,
and evidence-grounded confidence. Distinguish observed, derived, configured
target, fallback, unavailable, and insufficient history without conflating
semantic origin with availability.

Preserve legacy scalar fields and existing `metricSemantics` during migration.
Missing stays missing; genuine zero stays zero; history retains its calendar
slots. Legacy rows without metadata remain unknown where evidence is absent.
Do not fabricate source timestamps, sample counts, confidence, or windows.

Source health initially uses only `ok`, `degraded`, and `unknown`, with
structured reasons separate from state. No health evidence means `unknown`,
never `ok`. Track Activity Daily, Vitals & Mobility, Heart Rate, Sleep, Hevy,
Strava, Withings, Nutrition, and other feeds independently. A recent successful
check or receipt cannot make an old observation fresh. Partial current days
and completed-day summaries have different expected windows. Unknown inputs
must reduce confidence in dependent derived states.

Daily scores need an input/provenance snapshot sufficient to explain derived
values. Preserve canonical source selection and existing temporal semantics;
provenance does not authorize a scoring change or historical recomputation.

Acceptance cases must cover observed zero; missing metric; insufficient
history; incomplete day; stale observation with a fresh receipt; absent legacy
metadata; mixed source coverage; unavailable source-health evidence; late
correction/replay; raw versus daily-summary aggregation; timezone boundaries;
and additive compatibility for existing API consumers.

Excluded from PR5: watchdog/alerts/schedules, intervention tables, universal
event backbone, Daily Operating Picture generation, HAE Workouts, workout
identity v2, frontend redesign, scoring changes, and historical migrations.
Use a dedicated implementation branch/PR. Independent review and explicit
merge/deploy approval remain required.

### PR6 — Source Watchdog

Use PR5 semantics to detect stale sources, missing expected metric families,
unexpected metric-count degradation, partial-day ingestion, token/source
failures, and suspicious completeness changes.

### PR7 — Workout & Activity Evidence Model

Build a source-neutral evidence model capable of reconciling Hevy, HAE/Apple
Health workouts, Strava, and possible future native PRISM execution. Preserve
duplicate source observations and resolve identity, load, and canonicalization
at the appropriate layer instead of deleting provenance. A real HAE workout
payload is a hard gate for HAE workout semantics.

### PR8 — Longitudinal Evidence, Exposures, Symptoms & Interventions

Support durable longitudinal reasoning across observations, exposures,
symptoms, interventions, and outcomes while maintaining the distinction
between association and causality.

### PR9 — PRISM Reasoning / Daily Operating Picture

Consume trustworthy evidence, source health, completeness/confidence,
longitudinal patterns, training/activity context, symptoms, exposures,
interventions, and derived signals to produce an objective, rationale,
actions, watchouts, evidence, confidence, and uncertainty.

### Future phase — PRISM Training Execution

Native execution remains future product scope. Candidate capabilities include
guided workouts, prior-load prefill, progression recommendations,
why-this-target explanations, timers, supersets, RPE/RIR, symptom check-ins,
adaptive substitutions, per-side tracking, planned versus actual results,
PR/e1RM feedback, and muscle-load visualization. At that point, explicitly
reevaluate whether Hevy still creates enough value to remain in the
architecture.

## Product reference register

References inform requirements; they do not replace PRISM's architecture.

| Product | Role | Disposition | Boundary |
|---|---|---|---|
| [openGym](https://github.com/arvids-unavailable/openGym) | Training execution and product/UX reference | **ADAPT / EVENTUALLY ABSORB** selected concepts | Reference guided execution, prior-load prefill, timers, supersets, progression explanations, e1RM/PR feedback, RPE/RIR, bodyweight/per-side/timed/carry/cardio semantics, muscle-load views, exercise libraries and substitutions, portability, and phone-first PWA interaction. Do not copy its architecture or meaningful implementation code. |
| Hevy | Current resistance-training execution and source system | **INTEGRATE** today | Reevaluate only if native PRISM execution materially improves evidence, action, or friction. |
| Apple Health / HAE | Primary physiological/raw HealthKit evidence transport | **INTEGRATE** | PRISM owns interpretation and provenance, not raw-health collection UX. |
| Strava | Current cardio/activity observation source | **INTEGRATE** | Preserve while it remains necessary for cardio evidence; future reconciliation belongs in PR7. |
| Bevel | External physiology/recovery interpretation and product reference | **REFERENCE / INTEGRATE** where useful | Compare and learn; do not clone its dashboards merely for consolidation. |
| Whoop / Oura | Existing scoring and interpretation references | **REFERENCE** | Existing repository scoring documents already use their conventions; they are not required source-system dependencies. |

### openGym licensing boundary

openGym is licensed under AGPL-3.0. Treat it as product and UX inspiration for
this work. Do not copy meaningful source code into McFox/PRISM unless a later,
deliberate licensing review approves the implications.

## Current non-goals

This product record does not authorize runtime fields, tables, IAM, APIs,
ingestion changes, scoring changes, historical migrations, native workout
execution, PR5 implementation, or deployment. Each roadmap PR requires its
own evidence, design, tests, approval, and rollback plan.
