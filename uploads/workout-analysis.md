---
name: workout-analysis
triggers: workout review, Strava analysis, training breakdown, HR zones, "how was my workout", "analyze my last run/ride/session", exercise performance, post-workout log
---

# Workout Analysis

Deep-dive analysis of Strava workouts and multi-session training patterns.

## MCP: strava
- `get-activity-details` — activity metadata
- `get-activity-streams` — second-by-second HR, cadence, GPS
- `get-activity-laps` — split analysis
- `get-recent-activities` — multi-session pattern analysis

## Single Workout Analysis
1. Pull activity via Strava MCP (most recent or by ID)
2. Pull HR streams for zone distribution
3. Calculate:
   - Time in each HR zone (Z1-Z5)
   - TRIMP (training impulse): weighted time x zone intensity
   - Estimated strain on 0-21 scale
   - Avg HR as % of max (est max = 220 - age)
   - Workout efficiency: output vs cardiac cost
4. Compare against same-type workouts (last 4 weeks)
5. Flag: unusual max HR, cardiac drift, poor inter-set recovery

## Post-Workout Logging
When Mateo describes exercises after a workout:
1. Match to today's most recent Strava activity
2. Merge HR/duration from Strava with exercise descriptions
3. Write to `Inputs/Health/Workouts/YYYY-MM-DD.md`

### Workout Note Template
```markdown
# Workout — YYYY-MM-DD

**Type:** [Pull / Push / Legs / HIIT / Run / etc.]
**Duration:** [from Strava] | **Avg HR:** [from Strava] | **Max HR:** [from Strava]
**Active Cal:** [from Strava/HealthKit] | **Strain:** [calculated /21]

## Exercises
- Exercise: sets x reps @ weight
- [note supersets with "superset w/"]

## HR Zone Distribution
- Z1 (recovery): X min | Z2 (endurance): X min | Z3 (tempo): X min
- Z4 (threshold): X min | Z5 (max): X min

## Notes
[Observations, PRs, flags, recovery recommendations]
```

## Strava Activity Type Mapping
- "Workout" / "Other" = Weight training / HIIT / mixed
- Mateo's common Strava choices: Workout, Outdoor Walk, HIIT, Outdoor Run, Weight Training, Pilates, Yoga, Hike

## Training Patterns (observed)
- Supersets are common (e.g., T-bar rows + push-ups)
- Uses ascending weight on cables (40/43/47 progressive loading)
- Often finishes with incline walk and/or 15-20 min sauna
- Training 4-5x/week consistently

## Tone
Coach reviewing game film. Specific, evidence-based, actionable.
Tell Mateo what it means and what to do next, not just what happened.
