---
name: weekly-review
triggers: weekly review, weekly report, training summary, "how was my week", "what should I do next week", training load, volume analysis
---

# Weekly Review

Aggregate 7 days of training, recovery, sleep, nutrition, and body composition into a report with adaptive recommendations.

## Data Sources
- **Strava MCP:** all activities, HR streams, volume
- **Withings MCP:** weight, body comp trend
- **Apple Health (vault JSON):** sleep, HRV, resting HR
- **Nutrition logs:** from vault `Inputs/Health/Nutrition/`
- **Workout logs:** from vault `Inputs/Health/Workouts/`

## Report Template
Write to `Inputs/Health/Weekly/Week-of-YYYY-MM-DD.md`:

```markdown
# Weekly Health Report — Week of [Monday date]

## Score Summary
| Metric | This Week | Last Week | Trend |
|--------|-----------|-----------|-------|
| Avg Recovery | XX% | XX% | arrow |
| Total Strain | XX | XX | arrow |
| Avg Sleep | Xh Xm | Xh Xm | arrow |
| Weight | XXX lbs | XXX lbs | arrow |
| Body Fat | XX.X% | XX.X% | arrow |
| Avg Protein | XXXg | XXXg | arrow |
| Reta dose | X of 4 | — | — |

## Training Volume
- Sessions: X (target: 4-5)
- Total minutes: X
- Distribution: X strength / X cardio / X mobility / X rest
- Avg strain/session: X

## Workout Log
| Day | Type | Duration | Avg HR | Strain |
|-----|------|----------|--------|--------|

## Recovery Trend
[7-day HRV values with green/yellow/red classification]
- Days green: X | yellow: X | red: X

## Sleep Summary
- Avg duration | Avg efficiency | Sleep debt | Bedtime range

## Nutrition Summary
- Days logged: X/7
- Avg calories | Avg protein | Protein hit rate (days >=180g)
- Days under 100g protein: X (escalate if >1)

## Key Observations
1. [Most important finding]
2. [Second finding]
3. [Third finding]

## Next Week Recommendations
### Training Plan
[Mon-Sun with type + intensity based on recovery/strain balance]
- Avg recovery green + moderate strain → increase volume slightly
- Avg recovery yellow + high strain → deload (reduce 30%)
- Avg recovery red → 2 mandatory rest days
- Always include >=1 mobility session and >=1 rest day

### Nutrition Adjustments
[Based on patterns — protein consistency, calorie adherence]

### Reta Monitoring
- Weight change this week: X lbs
- Rate: X lbs/week (alert if >1.5)
- Appetite observations
- Any side effects noted
```

## Adaptive Logic
- Reference previous weekly reports for trend context
- If same issue appears 2+ weeks (e.g., low protein), escalate
- Track if last week's recommendations were followed
- Adjust strain targets based on multi-week recovery trends
- With reta: track weight loss rate carefully, adjust calories if too aggressive

## Tone
Head coach reviewing the week. Honest, specific, forward-looking.
Celebrate wins (PRs, consistency) but don't gloss over issues.
