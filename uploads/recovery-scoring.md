---
name: recovery-scoring
triggers: recovery score, morning briefing, readiness, "how recovered am I", "should I train hard today", HRV check, daily health
---

# Recovery Scoring

Whoop-style recovery (0-100%) using HRV-heavy weighting.
This is the first check every morning before deciding training intensity.

## Data Sources
- Apple Health (via Shortcuts bridge JSON): HRV, resting HR, respiratory rate, SpO2, wrist temp
- Sleep data: total duration, efficiency, stage distribution
- Withings (via MCP): latest weight, body fat for context

## Algorithm

### Weights
| Component | Weight | Green | Yellow | Red |
|-----------|--------|-------|--------|-----|
| HRV vs 30d baseline (48ms) | 50% | >5% above | +/-5% | >5% below |
| Resting HR vs 30d baseline (64bpm) | 25% | >3% below | +/-3% | >3% above |
| Sleep quality | 15% | >7h, >90% eff | 6-7h or <90% eff | <6h or <80% eff |
| Respiratory rate | 10% | 12-20 normal | slightly elevated | significantly elevated |

### Score Ranges
- **67-100% (Green):** Train hard
- **34-66% (Yellow):** Train smart
- **0-33% (Red):** Rest

## Morning Briefing Template
Write to `Inputs/Health/Daily/YYYY-MM-DD.md`:

```markdown
# Daily Health — YYYY-MM-DD

## Recovery: XX% [Green/Yellow/Red]

| Metric | Today | Baseline | Delta | Signal |
|--------|-------|----------|-------|--------|
| HRV | XX ms | 48 ms | +X% | green/yellow/red |
| Resting HR | XX bpm | 64 bpm | -X% | green/yellow/red |
| Resp Rate | XX /min | ~14 /min | — | green/yellow/red |
| Sleep | Xh Xm | 7h 30m need | — | green/yellow/red |

**Insight:** [One sentence]
**Recommendation:** [Train hard / Train smart / Rest]
**Nutrition note:** [Protein target reminder, reta status]
```

## Cross-References
- Red 2+ days → flag overtraining
- HRV trending down 3+ days → recommend deload
- Check Withings for weight spikes (water retention = inflammation)
- After alcohol days, expect yellow/red next morning (confirmed: April 19 = 31ms after drinking)
- With reta active: monitor if recovery patterns change over the 4-week protocol

## Real Baseline Data Points
- HRV 49ms = above baseline, green (April 20-21)
- HRV 43ms = 10% below, yellow (April 17)
- HRV 31ms = critical low, red (April 19 — alcohol + undereating + high strain)
- RHR 60.5 = best observed (full rest day)
- RHR 66 = worst observed (post-alcohol)
